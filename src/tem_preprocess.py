# tem_preprocess.py
"""Preprocess NetCDF climate and static data into the CSV files read by a TEM core."""

import filecmp
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

import tem_climate as clim
from tem_io import (
    link,
    subset_csv,
    write_daily_csv,
    write_elev_csv,
    write_monthly_csv,
)

log = logging.getLogger("PREPROCESS")

TRANSIENT = ["tair", "dtr", "prec", "nirr", "vpr"]
NEEDS = {
    "tair": ["tair", "tmin+tmax"],
    "dtr": ["dtr", "tmin+tmax"],
    "prec": ["prec"],
    "nirr": ["nirr"],
    "vpr": ["vpr", "dewpoint", "huss"],
    "wind": ["wind", "u10+v10"],
    "elev": ["elev"],
}
STATIC_NAMES = {
    "texture": "texture_grid.csv",
    "co2": "co2.data",
    "ozone": "ozone_grid.csv",
    "ndep": "ndep_grid.csv",
    "max_cohorts": "mxcohort_grid.csv",
    "cohorts": "cohort_grid.csv",
}


def candidate_cells(cfg: dict) -> pd.DataFrame:
    """All points of the lon/lat box on the resolution grid with area (km2) and region."""
    res = cfg["resolution"]
    lons = np.arange(cfg["lon_min"], cfg["lon_max"] + res / 2, res).round(4)
    lats = np.arange(cfg["lat_min"], cfg["lat_max"] + res / 2, res).round(4)
    cells = pd.MultiIndex.from_product([lons, lats], names=["lon", "lat"]).to_frame(
        index=False
    )
    cells["area"] = clim.cell_area_km2(cells["lat"].values, res).round()
    cells["region"] = cfg["region"]
    if cells["area"].min() < 10:
        log.warning(
            "Cell area is %d km2 at the smallest: TEM reads the area as an integer",
            cells["area"].min(),
        )
    return cells


def pick(name: str, cfg: dict, ds: xr.Dataset) -> xr.DataArray:
    """TEM input name from the file(s) on the time step of the core; error if netcdf_varmap cannot supply it."""
    frequency = cfg["netcdf_input_frequency"]
    da = clim.derive(
        name, ds, cfg["netcdf_varmap"], frequency, cfg["surface_pressure_hpa"]
    )
    if da is None:
        raise ValueError(
            f"netcdf_varmap cannot supply TEM input '{name}': list {' or '.join(NEEDS[name])} "
            "(see README, Variable map)"
        )
    return clim.to_step(da, name, frequency, cfg["profile"]["time_step"])


def land_cells(cfg: dict, ds: xr.Dataset) -> pd.DataFrame:
    """Candidate cells whose elevation in the input file is valid; ocean cells are dropped."""
    cells = candidate_cells(cfg)
    elev = clim.to_cells(
        pick("elev", cfg, ds), cells, cfg["resolution"], cfg["regrid_method"]
    ).load()
    cells = cells[elev.notnull().values].reset_index(drop=True)
    if cells.empty:
        raise ValueError("No cell of the box has valid data in the input file")
    log.info("Grid: %d land cells of %g degrees", len(cells), cfg["resolution"])
    return cells


def check_complete(da: xr.DataArray, name: str) -> None:
    missing = int(da.isnull().any([d for d in da.dims if d != "cell"]).sum())
    if missing:
        raise ValueError(f"{name}: {missing} cells have missing data after regridding")


def file_tags(spec: list, directory: str, filename: str, tags: dict[str, str]) -> None:
    """XML tags of a file: a complete name, or a name without extension plus the extension tag."""
    name_tag, end_tag = spec
    path = Path(filename)
    if end_tag is None:
        tags[name_tag] = f"./INPUT/{directory}/{filename}"
    else:
        tags[name_tag] = f"./INPUT/{directory}/{path.stem}"
        tags[end_tag] = path.suffix


def run(cfg: dict) -> dict[str, str]:
    """Write all TEM input files into <case>/INPUT and return the XML tags that point to them."""
    profile = cfg["profile"]
    step = profile["time_step"]
    case_input = cfg["case_dir"] / "INPUT"
    climate_out, static_out = case_input / "climate", case_input / "static"
    for sub in (climate_out, static_out):
        sub.mkdir(parents=True, exist_ok=True)
    res = cfg["resolution"]
    pad = max(2.0, 2 * res)
    bbox = (
        cfg["lon_min"] - pad,
        cfg["lon_max"] + pad,
        cfg["lat_min"] - pad,
        cfg["lat_max"] + pad,
    )
    y0, y1 = cfg["start_year"], cfg["end_year"]
    if y1 - y0 + 1 < 40:
        log.warning(
            "Only %d transient years: the cores equilibrate over 40 years from start_year and a 10-year run returned NaN",
            y1 - y0 + 1,
        )
    tags: dict[str, str] = {}
    ds = clim.open_dataset(
        cfg["netcdf_input_file"], bbox, cfg["netcdf_input_frequency"]
    )
    cells = land_cells(cfg, ds)
    cells.to_csv(case_input / "grids.csv", index=False)

    write = write_monthly_csv if step == "monthly" else write_daily_csv
    n_steps = (
        12 * (y1 - y0 + 1)
        if step == "monthly"
        else (pd.Timestamp(y1, 12, 31) - pd.Timestamp(y0, 1, 1)).days + 1
    )
    for name in [*profile["climate_inputs"], "wind", "elev"]:
        da = pick(name, cfg, ds)
        transient_wind = name == "wind" and profile.get("wind_transient", False)
        if name == "wind" and "time" in da.dims and not transient_wind:
            da = da.groupby("time.month").mean()
        elif name in profile["climate_inputs"] or (
            name == "wind" and "time" in da.dims
        ):
            da = da.sel(time=slice(f"{y0}-01-01", f"{y1}-12-31"))
            if da.time.size != n_steps:
                raise ValueError(
                    f"{name}: {da.time.size} {step} values found, {n_steps} needed for {y0}-{y1}"
                )
        elif transient_wind:
            raise ValueError(
                "wind: this core reads transient wind but the NetCDF wind has no time dimension"
            )
        da = clim.to_cells(da, cells, res, cfg["regrid_method"]).load()
        check_complete(da, name)
        if name == "elev":
            write_elev_csv(climate_out / "elev.csv", da, cells)
            file_tags(profile["climate_tags"]["elev"], "climate", "elev.csv", tags)
        else:
            write(climate_out / f"{name}.csv", name, da, cells)
            file_tags(profile["climate_tags"][name], "climate", f"{name}.csv", tags)
    ds.close()

    for key, spec in profile["static_tags"].items():
        source, fname = cfg[f"{key}_file"], STATIC_NAMES[key]
        if key == "co2" and profile.get("co2_daily", False):
            days = pd.date_range(f"{y0}-01-01", f"{y1}-12-31", freq="D")
            table = pd.read_csv(source, sep=r"\s+", header=None, index_col=0)[1]
            da = xr.DataArray(
                table.reindex(days.year).to_numpy()[None].repeat(len(cells), 0),
                coords={"cell": range(len(cells)), "time": days},
                dims=("cell", "time"),
            )
            write_daily_csv(climate_out / "co2.csv", "co2", da, cells)
            file_tags(profile["climate_tags"]["co2"], "climate", "co2.csv", tags)
            continue
        if key == "ozone" and profile.get("ozone_daily", False):
            rows = static_out / ".ozone_subset.csv"
            subset_csv(source, rows, cells)
            table = pd.read_csv(rows, header=None).iloc[:, 9:21].to_numpy()
            rows.unlink()
            days = pd.date_range("2014-01-01", "2014-12-31", freq="D")
            da = xr.DataArray(
                table[:, days.month - 1],
                coords={"cell": range(len(cells)), "time": days},
                dims=("cell", "time"),
            )
            write_daily_csv(climate_out / "ozone.csv", "ozone", da, cells)
            file_tags(profile["climate_tags"]["ozone"], "climate", "ozone.csv", tags)
            continue
        target = static_out / fname
        if key == "co2":
            link(source, target)
        else:  # TEM reads these files cell by cell, so they must hold exactly the grid cells
            subset = static_out / f".{fname}"
            subset_csv(source, subset, cells)
            if filecmp.cmp(source, subset, shallow=False):
                subset.unlink()
                link(source, target)
            else:
                subset.replace(target)
        file_tags(spec, "static", fname, tags)

    tags["mxnumgrid"] = str(len(cells))
    log.info("Wrote %s inputs for %d cells to %s", step, len(cells), case_input)
    return tags
