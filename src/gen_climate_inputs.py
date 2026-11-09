"""Download climate forcing and write one daily NetCDF file for the app (netcdf_climate_in_file).

The file holds the variables tmin, tmax, prec, nirr and dewpoint or huss (tair as well for ERA5) with the units of the source,
on the time axis of the source, cut to --bbox LON_MIN LON_MAX LAT_MIN LAT_MAX and the years --start..--end.
The varmap for run_config.yaml is written next to it. Set netcdf_climate_in_frequency: daily; the app averages to months.

    python src/gen_climate_inputs.py --out INPUT --bbox -125 -110 32 49 --start 2000 --end 2019 era5
    python src/gen_climate_inputs.py ... gridmet
    python src/gen_climate_inputs.py ... maca --model BNU-ESM --scenario rcp85
    python src/gen_climate_inputs.py ... cmip6 --model MPI-ESM1-2-HR --scenario ssp245
"""

import argparse
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path

import pandas as pd
import xarray as xr

ERA5 = {  # daily statistic: {ERA5 variable: (name in the CDS file, name written)}
    "daily_mean": {
        "2m_temperature": ("t2m", "tair"),
        "2m_dewpoint_temperature": ("d2m", "dewpoint"),
    },
    "daily_maximum": {"2m_temperature": ("t2m", "tmax")},
    "daily_minimum": {"2m_temperature": ("t2m", "tmin")},
    "daily_sum": {
        "total_precipitation": ("tp", "prec"),
        "surface_solar_radiation_downwards": ("ssrd", "nirr"),
    },
}
ERA5_UNITS = {"tair": "K", "dewpoint": "K", "tmax": "K", "tmin": "K"}
GRIDMET = "https://www.reacchpna.org/thredds/dodsC/MET/{v}/{v}_{y}.nc"
GRIDMET_VARS = {
    "tmax": "tmmx",
    "tmin": "tmmn",
    "prec": "pr",
    "nirr": "srad",
    "huss": "sph",
}
MACA = "https://www.reacchpna.org/thredds/dodsC/agg_macav2metdata_{v}_{m}_{r}_{s}_{y0}_{y1}_CONUS_daily.nc"
MACA_VARS = {
    "tmax": "tasmax",
    "tmin": "tasmin",
    "prec": "pr",
    "nirr": "rsds",
    "huss": "huss",
}
PANGEO = "https://storage.googleapis.com/cmip6/pangeo-cmip6.csv"
CMIP6_VARS = {
    "tair": "tas",
    "tmax": "tasmax",
    "tmin": "tasmin",
    "prec": "pr",
    "nirr": "rsds",
    "huss": "huss",
}


def cut(da: xr.DataArray | xr.Dataset, a: argparse.Namespace):
    """Names lat and lon, longitudes -180..180 and ascending, cut to the box and years before anything is loaded."""
    da = da.rename(
        {
            k: v
            for k, v in {"latitude": "lat", "longitude": "lon"}.items()
            if k in da.dims
        }
    )
    da = da.assign_coords(lon=((da.lon + 180) % 360) - 180).sortby("lon").sortby("lat")
    lon_min, lon_max, lat_min, lat_max = a.bbox
    return da.sel(lon=slice(lon_min, lon_max), lat=slice(lat_min, lat_max)).sel(
        time=slice(f"{a.start}-01-01", f"{a.end}-12-31")
    )


def era5_month(stat: str, year: int, month: int, a: argparse.Namespace) -> xr.Dataset:
    import cdsapi

    lon_min, lon_max, lat_min, lat_max = a.bbox
    request = {
        "product_type": "reanalysis",
        "variable": list(ERA5[stat]),
        "year": str(year),
        "month": f"{month:02d}",
        "day": [f"{d:02d}" for d in range(1, 32)],
        "daily_statistic": stat,
        "time_zone": "utc+00:00",
        "frequency": "1_hourly",
        "area": [
            min(lat_max + 1, 90),
            max(lon_min - 1, -180),
            max(lat_min - 1, -90),
            min(lon_max + 1, 180),
        ],
    }
    with tempfile.TemporaryDirectory() as tmp, ExitStack() as inputs:
        target = Path(tmp) / "r.nc"
        for grid in (a.grid, None) if a.grid else (None,):
            try:
                cdsapi.Client(quiet=True).retrieve(
                    "derived-era5-single-levels-daily-statistics",
                    {**request, **({"grid": grid} if grid else {})},
                    str(target),
                )
                break
            except Exception as error:
                if grid is None:
                    raise
                print(f"ERA5 request with grid {grid} failed ({str(error)[:100]})")
        if zipfile.is_zipfile(target):
            datasets = []
            with zipfile.ZipFile(target) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    try:
                        ds = xr.open_dataset(
                            archive.extract(member, tmp), engine="netcdf4"
                        )
                    except OSError as error:
                        if error.errno != -51:  # libnetcdf NC_ENOTNC
                            raise
                    else:
                        datasets.append(inputs.enter_context(ds))
            if not datasets:
                raise ValueError("ERA5 archive contains no readable NetCDF datasets")
        else:
            datasets = [inputs.enter_context(xr.open_dataset(target, engine="netcdf4"))]
        return (
            xr.merge(datasets)
            .rename(valid_time="time")
            .drop_vars(["expver", "number"], errors="ignore")
            .load()
        )


def era5(a: argparse.Namespace) -> xr.Dataset:
    """ERA5 daily statistics (CDS dataset derived-era5-single-levels-daily-statistics); needs ~/.cdsapirc."""
    jobs = [
        (s, y, m) for s in ERA5 for y in range(a.start, a.end + 1) for m in range(1, 13)
    ]
    with ThreadPoolExecutor(4) as pool:
        parts = list(pool.map(lambda j: era5_month(*j, a), jobs))
    out = {}
    for stat, names in ERA5.items():
        ds = xr.concat(
            [p for p, j in zip(parts, jobs, strict=True) if j[0] == stat], "time"
        )
        for src, dst in names.values():
            out[dst] = ds[src].assign_attrs(
                units=ds[src].attrs.get("units", ERA5_UNITS.get(dst, ""))
            )
    return xr.Dataset(out).sortby("time")


def gridmet(a: argparse.Namespace) -> xr.Dataset:
    """gridMET 4 km daily surface meteorology of the conterminous United States (Abatzoglou 2013), read by OPeNDAP."""
    out = {}
    for name, v in GRIDMET_VARS.items():
        years = [
            cut(xr.open_dataset(GRIDMET.format(v=v, y=y)).rename(day="time"), a)
            for y in range(a.start, a.end + 1)
        ]
        out[name] = xr.concat(
            [y[next(k for k in y.data_vars if k != "crs")] for y in years], "time"
        )
    return xr.Dataset(out)


def maca(a: argparse.Namespace) -> xr.Dataset:
    """MACAv2-METDATA 4 km daily downscaled CMIP5 of the conterminous United States, read by OPeNDAP; --scenario rcp45 or rcp85."""
    out = {}
    for name, v in MACA_VARS.items():
        parts = []
        for s, y0, y1 in (("historical", 1950, 2005), (a.scenario, 2006, 2099)):
            if a.start <= y1 and a.end >= y0:
                ds = xr.open_dataset(
                    MACA.format(v=v, m=a.model, r=a.member, s=s, y0=y0, y1=y1)
                )
                parts.append(cut(ds, a)[next(k for k in ds.data_vars if k != "crs")])
        out[name] = xr.concat(parts, "time")
    return xr.Dataset(out)


def cmip6(a: argparse.Namespace) -> xr.Dataset:
    """CMIP6 daily output of the Pangeo Google Cloud archive; --model, --member (default: the first listed), --scenario for years after 2014."""
    import gcsfs

    cat = pd.read_csv(PANGEO)
    cat = cat[(cat.table_id == "day") & (cat.source_id == a.model)]
    out = {}
    for name, v in CMIP6_VARS.items():
        parts = []
        for exp, y0, y1 in (("historical", 1850, 2014), (a.scenario, 2015, 2100)):
            if a.start <= y1 and a.end >= y0:
                c = cat[(cat.experiment_id == exp) & (cat.variable_id == v)]
                member = a.member or c.member_id.iloc[0]
                z = c[c.member_id == member].zstore.iloc[-1]
                parts.append(
                    cut(
                        xr.open_zarr(
                            gcsfs.GCSFileSystem(token="anon").get_mapper(z),
                            consolidated=True,
                            use_cftime=True,
                        ),
                        a,
                    )[v]
                )
        if parts:
            out[name] = xr.concat(parts, "time")
    return xr.Dataset(out)


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--out", default="INPUT")
    p.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        default=[-180, 179, -89, 89],
        metavar=("LON_MIN", "LON_MAX", "LAT_MIN", "LAT_MAX"),
    )
    p.add_argument("--start", type=int, required=True)
    p.add_argument("--end", type=int, required=True)
    sub = p.add_subparsers(dest="src", required=True)
    c = sub.add_parser("era5")
    c.add_argument("--grid", help='CDS grid such as "1.0/1.0"; default the native 0.25')
    c.set_defaults(f=era5)
    sub.add_parser("gridmet").set_defaults(f=gridmet)
    for name, f in (("maca", maca), ("cmip6", cmip6)):
        c = sub.add_parser(name)
        c.add_argument("--model", required=True)
        c.add_argument("--scenario", required=True)
        c.add_argument("--member", default="r1i1p1" if name == "maca" else None)
        c.set_defaults(f=f)
    a = p.parse_args()
    ds = cut(a.f(a), a)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ds = ds.drop_vars([v for v in ds.coords if v not in ds.dims]).astype("float32")
    for v in ds.data_vars:
        ds[v].encoding = {"zlib": True, "complevel": 1}
    ds.load().to_netcdf(out / f"climate_{a.src}.nc")
    lines = "\n".join(f"  {k}: {k}" for k in ds.data_vars)
    (out / f"varmap_{a.src}.yaml").write_text(f"varmap:\n{lines}\n")
    print("wrote", out / f"climate_{a.src}.nc", "and", out / f"varmap_{a.src}.yaml")


if __name__ == "__main__":
    main()
