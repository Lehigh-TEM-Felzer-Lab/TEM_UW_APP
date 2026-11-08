# driver.py
"""Build the TEM_2026 case of the current directory (INPUT/*.nc, tem_config.yaml) and run it."""

import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import xarray as xr

import tem_climate as clim
import tem_config

log = logging.getLogger("DRIVER")
CLIMATE = {
    "tair": "degC",
    "dtr": "degC",
    "prec": "mm month-1",
    "nirr": "W m-2",
    "vpr": "hPa",
}
NEAREST = {
    "mxcohort",
    "lulc",
    "chrtarea",
    "potveg",
    "currentveg",
    "subtype",
    "agstate",
    "agprevstate",
}
FILE_KEYS = {  # tem_config.yaml key: file in INPUT/
    "inirrfname": "climate.nc",
    "itairfname": "climate.nc",
    "iprecfname": "climate.nc",
    "itrangefname": "climate.nc",
    "ivprfname": "climate.nc",
    "ico2fname": "co2.nc",
    "io3fname": "static.nc",
    "ndepfname": "static.nc",
    "iws10fname": "static.nc",
    "imxcohrtfname": "static.nc",
    "fstexture": "static.nc",
    "felev": "static.nc",
    "ilulcfname": "lulc.nc",
}


def grid(cfg: dict) -> tuple[np.ndarray, np.ndarray]:
    res = cfg["horizontal_resolution"]
    lon = np.arange(cfg["lon_min"], cfg["lon_max"] + res / 2, res).round(4)
    lat = np.arange(cfg["lat_min"], cfg["lat_max"] + res / 2, res).round(4)
    return lon, lat


def regrid_file(path: Path, cfg: dict, lon: np.ndarray, lat: np.ndarray) -> xr.Dataset:
    """Every lat/lon variable of a NetCDF file on the model grid."""
    ds = xr.open_dataset(path)
    ds = ds.rename(
        {k: v for k, v in clim.RENAME.items() if k in ds.dims or k in ds.coords}
    )
    ds = ds.assign_coords(lon=((ds.lon + 180) % 360) - 180).sortby("lon").sortby("lat")
    out = {}
    for name, da in ds.data_vars.items():
        if {"lat", "lon"} <= set(da.dims):
            method = "nearest" if name in NEAREST else cfg["regrid_method"]
            out[name] = clim.to_grid(
                da, lon, lat, method, cfg["horizontal_resolution"]
            ).load()
    return xr.Dataset(out)


def climate(cfg: dict, lon: np.ndarray, lat: np.ndarray) -> tuple[xr.Dataset, dict]:
    """climate.nc (monthly, noleap) and the time-independent fields wind and elev, if mapped."""
    res, y0, y1 = cfg["horizontal_resolution"], cfg["start_year"], cfg["end_year"]
    pad = max(2.0, 2 * res)
    ds = clim.open_dataset(
        cfg["netcdf_input_file"],
        (lon[0] - pad, lon[-1] + pad, lat[0] - pad, lat[-1] + pad),
        cfg["netcdf_input_frequency"],
    )
    fields = {}
    for name in [*CLIMATE, "wind", "elev"]:
        da = clim.derive(
            name,
            ds,
            cfg["netcdf_varmap"],
            cfg["netcdf_input_frequency"],
            cfg["surface_pressure_hpa"],
        )
        if da is None:
            if name in CLIMATE:
                raise ValueError(
                    f"netcdf_varmap cannot supply '{name}' (see config/run_config.yaml)"
                )
            continue
        if name in CLIMATE or (name == "wind" and "time" in da.dims):
            da = clim.monthly(da, name, cfg["netcdf_input_frequency"])
        if name == "wind" and "time" in da.dims:
            da = da.groupby("time.month").mean()
        elif "time" in da.dims:
            da = da.sel(time=slice(f"{y0}-01-01", f"{y1}-12-31"))
            if da.time.size != 12 * (y1 - y0 + 1):
                raise ValueError(
                    f"{name}: {da.time.size} months found, {12 * (y1 - y0 + 1)} needed"
                )
        fields[name] = clim.to_grid(da, lon, lat, cfg["regrid_method"], res).load()
    time = np.array(
        [(y - y0) * 365 + d for y in range(y0, y1 + 1) for d in MIDMONTH], dtype=float
    )
    attrs = {"units": f"days since {y0}-01-01", "calendar": "noleap"}
    out = xr.Dataset(
        {
            n: (("time", "lat", "lon"), fields[n].values, {"units": u})
            for n, u in CLIMATE.items()
        },
        coords={"time": ("time", time, attrs), "lat": lat, "lon": lon},
    )
    return out, {k: v for k, v in fields.items() if k in ("wind", "elev")}


MIDMONTH = [15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349]


def write_config(cfg: dict, written: set[str]) -> None:
    """tem_config.yaml from the TEM_2026 template: years, file names, parameter paths, varmap, overrides."""
    root = cfg["tem2026_dir"]
    text = (root / "templates" / "tem_config.yaml").read_text()
    y0, y1 = cfg["start_year"], cfg["end_year"]
    lon, lat = grid(cfg)
    values = {
        "region": cfg["region"],
        "clmstartyr": y0,
        "de_startyear": y0,
        "startyr": y0,
        "endyr": y1,
        "transtime": y1 - y0 + 1,
        "lulclastyr": y1,
        "mxnumgrid": lon.size * lat.size,
        **{k: f"./INPUT/{f}" for k, f in FILE_KEYS.items() if f in written},
        **cfg["tem"],
    }
    if cfg["tem"].get("veg_fire"):
        values |= {
            "flashfname": "./INPUT/lightning.nc",
            "popdensfname": "./INPUT/population.nc",
        }
    for key, value in values.items():
        text, n = re.subn(
            rf"^{key}:.*$",
            lambda _, k=key, v=value: f"{k}: {v}",
            text,
            flags=re.MULTILINE,
        )
        if n != 1:
            raise KeyError(f"tem_config.yaml of {root} has no key '{key}'")
    text = text.replace("../../params/", f"{root}/params/")
    for key, name in cfg["tem_varmap"].items():
        text, n = re.subn(
            rf"^  {key}:.*$", f"  {key}: {name}", text, flags=re.MULTILINE
        )
        if n != 1:
            raise KeyError(f"varmap of tem_config.yaml has no key '{key}'")
    (cfg["case_dir"] / "tem_config.yaml").write_text(text)


def build(cfg: dict) -> None:
    case = cfg["case_dir"]
    for sub in ("INPUT", "OUTPUT", "logs"):
        (case / sub).mkdir(parents=True, exist_ok=True)
    lon, lat = grid(cfg)
    written = {"climate.nc"}
    clim_ds, extra = climate(cfg, lon, lat)
    clim_ds.to_netcdf(case / "INPUT" / "climate.nc")
    static = (
        regrid_file(cfg["static_file"], cfg, lon, lat)
        if cfg["static_file"]
        else xr.Dataset()
    )
    for name, da in extra.items():
        if name not in static:
            static[name] = da.assign_attrs(units="m s-1" if name == "wind" else "m")
    if static.data_vars:
        static.to_netcdf(case / "INPUT" / "static.nc")
        written.add("static.nc")
    if cfg["lulc_file"]:
        regrid_file(cfg["lulc_file"], cfg, lon, lat).to_netcdf(
            case / "INPUT" / "lulc.nc"
        )
        written.add("lulc.nc")
    if cfg["co2_file"]:
        shutil.copy(cfg["co2_file"], case / "INPUT" / "co2.nc")
        written.add("co2.nc")
    if cfg["tem"].get("veg_fire"):
        for key, name in (
            ("flashes_file", "lightning.nc"),
            ("popdens_file", "population.nc"),
        ):
            regrid_file(cfg["fire"][key], cfg, lon, lat).to_netcdf(
                case / "INPUT" / name
            )
    write_config(cfg, written)
    log.info(
        "Built %s: %d x %d cells of %g degrees",
        case,
        lon.size,
        lat.size,
        cfg["horizontal_resolution"],
    )


def run(cfg: dict) -> int:
    cmd = [str(cfg["tem_exe"])]
    if cfg["mpi_tasks"] > 1:
        cmd = ["mpirun", "-n", str(cfg["mpi_tasks"]), *cmd]
    log.info("Running %s", " ".join(cmd))
    with open(cfg["case_dir"] / "logs" / "tem.out", "w") as out:
        return subprocess.run(
            cmd, cwd=cfg["case_dir"], stdout=out, stderr=subprocess.STDOUT, check=False
        ).returncode


def main() -> int:
    cfg = tem_config.load()
    (cfg["case_dir"] / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(cfg["case_dir"] / "logs" / "tup.log"),
        ],
    )
    build(cfg)
    return run(cfg) if cfg["run_model"] else 0


if __name__ == "__main__":
    sys.exit(main())
