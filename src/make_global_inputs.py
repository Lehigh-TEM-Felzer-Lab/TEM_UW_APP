"""Download global datasets and write the TEM_2026 input files for a region.

Each subcommand writes one file of INPUT/ on the grid given by --lon-min/--lon-max/--lat-min/--lat-max/--res
(cell centres on multiples of res from the minimum). See docs/global_data.md of TEM_UW_APP for the sources, units and caveats.

    python src/make_global_inputs.py --out INPUT --lon-min -125 --lon-max -110 --lat-min 32 --lat-max 49 co2 --start 2015 --end 2100
    python src/make_global_inputs.py ... fire --fire-file tem_biogeography/static/fire.nc
    python src/make_global_inputs.py ... soil elev wind
    python src/make_global_inputs.py ... lulc --luh2 states.nc --luh2-static staticData_quarterdeg.nc --year 2015
    python src/make_global_inputs.py ... static
"""

import argparse
import io
import subprocess
import tarfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

NOAA_CO2 = "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_annmean_mlo.txt"
POTVEG = "https://sage-public-files.s3.amazonaws.com/global-potential-vegetation/potveg_nc.tar.gz"
SOILGRIDS = "https://files.isric.org/soilgrids/latest/data_aggregated/5000m"
ETOPO = "https://www.ngdc.noaa.gov/thredds/fileServer/global/ETOPO2022/60s/60s_surface_elev_netcdf/ETOPO_2022_v1_60s_N90W180_surface.nc"
WORLDCLIM_WIND = (
    "https://geodata.ucdavis.edu/climate/worldclim/2_1/base/wc2.1_10m_wind.zip"
)
LAYERS = {
    "0-5cm": 5,
    "5-15cm": 10,
    "15-30cm": 15,
}  # SoilGrids layers of the top 30 cm and their thickness [cm]
# Ramankutty and Foley (1999) potential vegetation class -> TEM potveg (params/biogeography/tcomm50_lulc.yaml)
POTVEG_TO_TEM = {
    1: 16,
    2: 18,
    3: 33,
    4: 9,
    5: 10,
    6: 4,
    7: 4,
    8: 8,
    9: 14,
    10: 13,
    11: 15,
    12: 15,
    13: 3,
    14: 21,
    15: 2,
}
NATURAL = ("primf", "primn", "secdf", "secdn", "range")
CROPS = ("c3ann", "c4ann", "c3per", "c4per", "c3nfx")
COHORTS = {
    1: (NATURAL, None),
    2: (CROPS, 50),
    3: (("pastr",), 51),
}  # cohort: (LUH2 states, TEM currentveg)
# TEM vegetation types and names, from params/biogeography/tcomm50_lulc.yaml (attributes of lulc.nc)
VEG_TYPES = list(range(1, 57))
VEG_NAMES = (
    "Ice",
    "Alpine_Tundra_Polar_Desert",
    "Moist_Wet_Tundra",
    "Boreal_Forest",
    "Forested_Boreal_Wetlands",
    "Boreal_Woodlands",
    "Non_forested_Boreal_Wetlands",
    "Mixed_Temperate_Forests",
    "Temperate_Coniferous_Forests",
    "Temperate_Deciduous_Forests",
    "Temperate_Forested_Wetlands",
    "Tall_Grasslands",
    "Short_Grasslands",
    "Tropical_Savannas",
    "Arid_Shrublands",
    "Tropical_Evergreen_Forests",
    "Tropical_Forested_Wetlands",
    "Tropical_Deciduous_Forests",
    "Xeromorphic_Forests_and_Woodlands",
    "Tropical_Forested_Floodplains",
    "Deserts",
    "Tropical_Non_forested_Wetlands",
    "Tropical_Non_forested_Floodplains",
    "Temperate_Non_forested_Wetlands",
    "Temperate_Forested_Floodplains",
    "Temperate_Non_forested_Floodplain",
    "Wet_Savannas",
    "Salt_Marsh",
    "Mangroves",
    "Tidal_Freshwater_Marshes",
    "Temperate_Savannas",
    "Reserved",
    "Temperate_Broadleaved_Evergreen_Forests",
    "Reserved2",
    "Mediterranean_Shrublands",
    "Reserved3",
    "Reserved4",
    "Reserved5",
    "Reserved6",
    "Reserved7",
    "Reserved8",
    "Reserved9",
    "Reserved10",
    "Reserved11",
    "Reserved12",
    "Suburban",
    "Rodale_Pasture",
    "Turflawn",
    "Vegetable_Farm",
    "Crops",
    "Pasture",
    "Maize",
    "Wheat",
    "Rice",
    "Soybean",
    "Potato",
)
INT_FILL = -9999


def fetch(url: str, cache: Path) -> Path:
    """Download into the cache once; an interrupted transfer is resumed with wget -c."""
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / url.rsplit("/", 1)[1]
    if not path.exists():
        part = path.with_name(path.name + ".part")
        for _ in range(10):
            if (
                subprocess.run(
                    ["wget", "-q", "-c", "-O", str(part), url], check=False
                ).returncode
                == 0
            ):
                part.rename(path)
                return path
        raise SystemExit(f"download failed: {url}")
    return path


def target(a: argparse.Namespace) -> tuple[np.ndarray, np.ndarray]:
    lon = np.arange(a.lon_min, a.lon_max + a.res / 2, a.res).round(4)
    lat = np.arange(a.lat_min, a.lat_max + a.res / 2, a.res).round(4)
    return lon, lat


def box_mean(
    da: xr.DataArray, lon: np.ndarray, lat: np.ndarray, res: float
) -> xr.DataArray:
    """Mean of the source cells that fall in each target cell (source names lon and lat, lon in -180..180)."""
    for name, c in (("lon", lon), ("lat", lat)):
        i = np.floor((da[name].values - (c[0] - res / 2)) / res).astype(int)
        keep = (i >= 0) & (i < c.size)
        da = (
            da.isel({name: keep})
            .groupby(xr.DataArray(i[keep], dims=name, name="i" + name))
            .mean(skipna=True)
        )
        da = (
            da.rename({"i" + name: name})
            .assign_coords({name: c[np.unique(i[keep])]})
            .reindex({name: c})
        )
    return da.astype("float32")


def write(ds: xr.Dataset, a: argparse.Namespace, name: str) -> None:
    Path(a.out).mkdir(parents=True, exist_ok=True)
    ds = ds.assign_coords(lon=ds.lon.astype("float32"), lat=ds.lat.astype("float32"))
    for v in ds.data_vars:
        if ds[v].dtype.kind == "f":
            ds[v] = ds[v].astype("float32")
    ds.lon.attrs.update(units="degrees_east")
    ds.lat.attrs.update(units="degrees_north")
    ds.to_netcdf(Path(a.out) / name)
    print("wrote", Path(a.out) / name)


def co2(a: argparse.Namespace) -> None:
    """Annual CO2 [ppmv] for start..end from NOAA GML (observed) and a two-column scenario file (year ppmv) after it."""
    raw = pd.read_csv(
        fetch(NOAA_CO2, Path(a.cache)),
        sep=r"\s+",
        comment="#",
        names=["year", "mean", "unc"],
    )
    series = raw.set_index("year")["mean"]
    if a.scenario:
        scen = pd.read_csv(
            a.scenario,
            sep=r"[,\s]+",
            comment="#",
            names=["year", "mean"],
            engine="python",
        )
        series = (
            pd.concat([series, scen.set_index("year")["mean"]]).groupby(level=0).last()
        )
    series = series.loc[a.start : a.end]
    if series.index.size != a.end - a.start + 1:
        raise SystemExit(
            f"CO2 missing for {sorted(set(range(a.start, a.end + 1)) - set(series.index))}; pass --scenario"
        )
    t = pd.to_datetime([f"{y}-01-01" for y in series.index])
    days = (t - pd.Timestamp(f"{a.start}-01-01")).days.values.astype("float64")
    ds = xr.Dataset(
        {"co2": ("time", series.values.astype("float32"), {"units": "ppmv"})},
        coords={
            "time": (
                "time",
                days,
                {"units": f"days since {a.start}-01-01", "calendar": "noleap"},
            )
        },
    )
    Path(a.out).mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(Path(a.out) / "co2.nc")
    print("wrote", Path(a.out) / "co2.nc")


def fire(a: argparse.Namespace) -> None:
    """Lightning (km-2 month-1) and population density (km-2) from the 0.5 degree fire.nc of TEM_Biogeography."""
    src = xr.open_dataset(a.fire_file, decode_times=False).rename(time="month")
    lon, lat = target(a)
    src = src.assign_coords(lon=((src.lon + 180) % 360) - 180).sortby("lon")
    fl = box_mean(src["lightning_flashes"], lon, lat, a.res).assign_attrs(
        units="km-2 month-1"
    )
    pop = box_mean(src["population_density"], lon, lat, a.res).assign_attrs(
        units="km-2"
    )
    write(fl.to_dataset().assign_coords(month=np.arange(1, 13)), a, "flash.nc")
    write(pop.to_dataset(), a, "popdens.nc")


def soil(a: argparse.Namespace) -> None:
    """Sand, silt and clay [percent], thickness weighted mean of the top 30 cm of SoilGrids 2.0 at 5 km."""
    import rioxarray as rx
    from rasterio.enums import Resampling

    lon, lat = target(a)
    tmpl = xr.DataArray(
        np.zeros((lat.size, lon.size), "float32"),
        coords={"y": lat, "x": lon},
        dims=("y", "x"),
    ).rio.write_crs("EPSG:4326")
    out = {}
    for var in ("sand", "silt", "clay"):
        acc = 0
        for layer, thick in LAYERS.items():
            tif = fetch(f"{SOILGRIDS}/{var}/{var}_{layer}_mean_5000.tif", Path(a.cache))
            g = (
                rx.open_rasterio(tif, masked=True).squeeze(drop=True) / 10
            )  # g/kg -> percent
            acc = acc + thick * g.rio.reproject_match(
                tmpl, resampling=Resampling.average
            )
        out[var] = (
            (acc / sum(LAYERS.values()))
            .rename(x="lon", y="lat")
            .drop_vars("spatial_ref", errors="ignore")
            .assign_attrs(units="percent")
        )
    write(xr.Dataset(out), a, "soil.nc")


def elev(a: argparse.Namespace) -> None:
    """Elevation [m], ETOPO 2022 1 arc-minute ice surface, mean of the source cells in each target cell."""
    da = xr.open_dataset(fetch(ETOPO, Path(a.cache)))["z"].rename(lon="lon", lat="lat")
    lon, lat = target(a)
    da = da.sel(
        lon=slice(lon[0] - a.res, lon[-1] + a.res),
        lat=slice(lat[0] - a.res, lat[-1] + a.res),
    )
    write(
        box_mean(da, lon, lat, a.res)
        .clip(min=0)
        .rename("elev")
        .assign_attrs(units="m")
        .to_dataset(),
        a,
        "elev.nc",
    )


def wind(a: argparse.Namespace) -> None:
    """Monthly mean wind [m s-1] of WorldClim 2.1 (1970-2000, 10 arc-minutes). The height is 2 m, see docs/global_data.md."""
    import rioxarray as rx

    lon, lat = target(a)
    zf = zipfile.ZipFile(fetch(WORLDCLIM_WIND, Path(a.cache)))
    months = []
    for m in range(1, 13):
        with zf.open(f"wc2.1_10m_wind_{m:02d}.tif") as f:
            g = (
                rx.open_rasterio(io.BytesIO(f.read()), masked=True)
                .squeeze(drop=True)
                .rename(x="lon", y="lat")
            )
        months.append(
            box_mean(g.drop_vars("spatial_ref", errors="ignore"), lon, lat, a.res)
        )
    da = (
        xr.concat(months, dim="month")
        .assign_coords(month=np.arange(1, 13))
        .rename("wind")
        .assign_attrs(units="m s-1")
    )
    write(da.to_dataset(), a, "wind.nc")


def climatology(
    a: argparse.Namespace,
    file: str,
    var: str,
    scale: float,
    name: str,
    units: str,
    monthly: bool,
) -> None:
    ds = xr.open_dataset(file)
    da = ds[var].rename(
        {
            k: v
            for k, v in (("longitude", "lon"), ("latitude", "lat"))
            if k in ds[var].dims
        }
    )
    da = da.assign_coords(lon=((da.lon + 180) % 360) - 180).sortby("lon").sortby("lat")
    if "time" in da.dims:
        da = da.groupby("time.month").mean() if monthly else da.mean("time")
    lon, lat = target(a)
    write(
        (box_mean(da, lon, lat, a.res) * scale)
        .rename(name)
        .assign_attrs(units=units)
        .to_dataset(),
        a,
        f"{name}.nc",
    )


def ozone(a: argparse.Namespace) -> None:
    """AOT40 climatology (month, lat, lon) from a gridded ozone NetCDF that you downloaded (docs/global_data.md)."""
    climatology(a, a.file, a.var, a.scale, "ozone", "ppb h", True)


def ndep(a: argparse.Namespace) -> None:
    """Annual N deposition [mg N m-2 yr-1] from a NetCDF that you downloaded; --scale converts the file units."""
    climatology(a, a.file, a.var, a.scale, "ndep", "mg N m-2 yr-1", False)


def lulc(a: argparse.Namespace) -> None:
    """Cohorts of each cell from LUH2 states of one year and the Ramankutty and Foley potential vegetation."""
    lon, lat = target(a)
    pv_tar = fetch(POTVEG, Path(a.cache))
    with tarfile.open(pv_tar) as t:
        pv = xr.open_dataset(io.BytesIO(t.extractfile("vegtype_0.5.nc").read()))[
            "vegtype"
        ].squeeze(drop=True)
    pv = pv.rename(longitude="lon", latitude="lat")
    pv = (
        pv.sortby("lat")
        .interp(lon=lon, lat=lat, method="nearest")
        .round()
        .fillna(0)
        .astype(int)
    )
    pot = xr.apply_ufunc(
        lambda x: np.vectorize(lambda k: POTVEG_TO_TEM.get(int(k), 0))(x), pv
    )
    st = xr.open_dataset(a.luh2, decode_times=False)
    units = st["time"].attrs["units"]
    base = int(units.split("since")[1].strip().split("-")[0])
    st = st.isel(time=a.year - base).rename(lon="lon", lat="lat")
    stat = xr.open_dataset(a.luh2_static)
    area = (stat["carea"] * (1 - stat["icwtr"])).rename(lon="lon", lat="lat")
    n = len(COHORTS)
    shape = (n, lat.size, lon.size)
    out = {
        k: np.full(shape, INT_FILL, "int64")
        for k in ("potveg", "currentveg", "subtype", "agstate", "agprevstate", "mxc")
    }
    chrt = np.full(shape, np.nan, "float32")
    for c, (names, veg) in COHORTS.items():
        km2 = sum(st[s].fillna(0) for s in names) * area
        km2 = km2.sel(
            lon=slice(lon[0] - a.res, lon[-1] + a.res),
            lat=slice(lat[0] - a.res, lat[-1] + a.res),
        )
        tot = km2.assign_coords(lon=km2.lon.values, lat=km2.lat.values)
        i = np.floor((tot.lon.values - (lon[0] - a.res / 2)) / a.res).astype(int)
        j = np.floor((tot.lat.values - (lat[0] - a.res / 2)) / a.res).astype(int)
        ok_i, ok_j = (i >= 0) & (i < lon.size), (j >= 0) & (j < lat.size)
        s = (
            tot.isel(lon=ok_i, lat=ok_j)
            .groupby(xr.DataArray(i[ok_i], dims="lon", name="i"))
            .sum()
            .groupby(xr.DataArray(j[ok_j], dims="lat", name="j"))
            .sum()
        )
        grid = np.zeros((lat.size, lon.size))
        grid[np.ix_(np.unique(j[ok_j]), np.unique(i[ok_i]))] = s.transpose(
            "j", "i"
        ).values
        has = (grid > 1e-3) & (pot.values > 0)
        v = pot.values if veg is None else np.full_like(pot.values, veg)
        chrt[c - 1] = np.where(has, grid, np.nan)
        out["potveg"][c - 1] = np.where(has, pot.values, INT_FILL)
        out["currentveg"][c - 1] = np.where(has, v, INT_FILL)
        out["subtype"][c - 1] = np.where(has, v, INT_FILL)
        out["agstate"][c - 1] = np.where(has, int(veg is not None), INT_FILL)
        out["agprevstate"][c - 1] = np.where(has, int(veg is not None), INT_FILL)
    has = ~np.isnan(chrt)
    dims = ("cohort", "lat", "lon")
    ds = xr.Dataset(
        {
            "standage": (
                dims,
                np.where(
                    has,
                    np.where(np.arange(1, n + 1)[:, None, None] == 1, 3000.0, 1.0),
                    np.nan,
                ).astype("float32"),
            ),
            "chrtarea": (dims, chrt, {"units": "km2"}),
            **{
                k: (dims, out[k])
                for k in ("potveg", "currentveg", "subtype", "agstate", "agprevstate")
            },
            "FRI": (dims, np.where(has, 2000.0, np.nan).astype("float32")),
        },
        coords={"cohort": np.arange(1, n + 1, dtype="int64"), "lat": lat, "lon": lon},
    )
    for k in ("potveg", "currentveg", "subtype", "agstate", "agprevstate"):
        ds[k].encoding["_FillValue"] = np.int64(INT_FILL)
    ds["cohort"].attrs = {
        "long_name": "cohort index within the cell",
        "flag_values": np.array(sorted(COHORTS), dtype="int32"),
        "flag_meanings": "natural_vegetation crops pasture",
    }
    for k in ("potveg", "currentveg"):
        ds[k].attrs = {
            "long_name": f"TEM {k} type",
            "flag_values": np.array(VEG_TYPES, dtype="int32"),
            "flag_meanings": " ".join(VEG_NAMES),
        }
    ds["agstate"].attrs = {
        "flag_values": np.array([0, 1], dtype="int32"),
        "flag_meanings": "natural_vegetation agriculture",
    }
    write(ds, a, "lulc.nc")


def static(a: argparse.Namespace) -> None:
    """static.nc from the pieces written before: elev, soil, wind, ozone and ndep."""
    parts = [
        xr.open_dataset(Path(a.out) / f)
        for f in ("elev.nc", "soil.nc", "wind.nc", "ozone.nc", "ndep.nc")
        if (Path(a.out) / f).exists()
    ]
    ds = xr.merge(parts)
    ds.to_netcdf(Path(a.out) / "static.nc")
    print("wrote", Path(a.out) / "static.nc")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--out", default="INPUT")
    p.add_argument("--cache", default="downloads")
    p.add_argument("--res", type=float, default=0.5)
    for k in ("lon_min", "lon_max", "lat_min", "lat_max"):
        p.add_argument("--" + k.replace("_", "-"), type=float, required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("co2")
    c.add_argument("--start", type=int, required=True)
    c.add_argument("--end", type=int, required=True)
    c.add_argument(
        "--scenario",
        help="text file with year and ppmv per line for the years after the observations",
    )
    c.set_defaults(f=co2)
    c = sub.add_parser("fire")
    c.add_argument("--fire-file", required=True)
    c.set_defaults(f=fire)
    for name, f in (("soil", soil), ("elev", elev), ("wind", wind), ("static", static)):
        sub.add_parser(name).set_defaults(f=f)
    for name, f in (("ozone", ozone), ("ndep", ndep)):
        c = sub.add_parser(name)
        c.add_argument("--file", required=True)
        c.add_argument("--var", required=True)
        c.add_argument(
            "--scale", type=float, default=1.0, help="factor from the units of the file"
        )
        c.set_defaults(f=f)
    c = sub.add_parser("lulc")
    c.add_argument("--luh2", required=True, help="LUH2 states.nc")
    c.add_argument("--luh2-static", required=True, help="LUH2 staticData_quarterdeg.nc")
    c.add_argument("--year", type=int, required=True)
    c.set_defaults(f=lulc)
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
