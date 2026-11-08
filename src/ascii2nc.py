"""Convert the old TEM ASCII (CSV) input files to the NetCDF files of TEM_2026.

Kinds and the records they read (fields comma separated, as written by the old preprocessors):
    clm    lon,lat, VAR ,area,year,total,max,ave,min,jan..dec, region   monthly; year -999 is a climatology (month)
    daily  lon,lat, VAR ,area,year,month,day,value, region              daily; written with a time axis of days
    elev   lon,lat, ELEV ,area,elev, region
    soil   lon,lat, SOIL ,area,sand,silt,clay,wsoil, source , region
    ndep   lon,lat,year,value                                           year -999 or one year: no time axis
    co2    year,ppmv
    lulc   lon,lat, VAR ,year,cohort,srccohort,standage,chrtarea,potveg,currentveg,subtype,agstate,agprevstate,
           tillflag,fertflag,irrgflag,disturbflag,disturbmonth,FRI,slashpar,vconvert,prod10par,prod100par,vrespar,sconvert, region

    ascii2nc.py clm cru_tair.csv cru_prec.csv -o climate.nc
    ascii2nc.py clm wind.csv aot40.csv -o static.nc       # repeated calls add to an existing file
    ascii2nc.py elev elev.csv -o static.nc
    ascii2nc.py soil soil.csv -o static.nc
    ascii2nc.py ndep ndep.csv -o static.nc
    ascii2nc.py co2 co2.csv -o co2.nc
    ascii2nc.py lulc lulc.csv -o lulc.nc --grid climate.nc   # the ASCII files list only cells with data: --grid restores the empty ones
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

NAMES = {
    "cldiness": "clouds",
    "dtairrng": "dtr",
    "vprpress": "vpr",
    "aot40": "ozone",
}
UNITS = {
    "tair": "degC",
    "dtr": "degC",
    "prec": "mm month-1",
    "nirr": "W m-2",
    "girr": "W m-2",
    "par": "W m-2",
    "vpr": "hPa",
    "wind": "m s-1",
    "elev": "m",
    "co2": "ppmv",
}
DAYS = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
MIDS = np.cumsum(DAYS) - DAYS / 2
INT_FILL = -9999
LULC = [
    "year",
    "cohort",
    "srccohort",
    "standage",
    "chrtarea",
    "potveg",
    "currentveg",
    "subtype",
    "agstate",
    "agprevstate",
    "tillflag",
    "fertflag",
    "irrgflag",
    "disturbflag",
    "disturbmonth",
    "FRI",
    "slashpar",
    "vconvert",
    "prod10par",
    "prod100par",
    "vrespar",
    "sconvert",
]
LULC_INT = LULC[5:15]
MONTHS = [
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
]


def read(path: str, names: list[str]) -> pd.DataFrame:
    df = pd.read_csv(path, header=None, names=names, skipinitialspace=True)
    for c in ("lon", "lat"):
        if c in df:
            df[c] = df[c].round(4)
    return df


def var(df: pd.DataFrame) -> str:
    name = df["var"].iloc[0].strip().lower()
    return NAMES.get(name, name)


def days_since(year: pd.Series, y0: int) -> np.ndarray:
    return ((year - y0) * 365 + 182).to_numpy().astype("float64")


def clm(path: str) -> xr.Dataset:
    df = read(
        path,
        [
            "lon",
            "lat",
            "var",
            "area",
            "year",
            "total",
            "max",
            "ave",
            "min",
            *MONTHS,
            "region",
        ],
    )
    name = var(df)
    df = df.melt(
        id_vars=["lon", "lat", "year"], value_vars=MONTHS, var_name="month"
    ).assign(month=lambda d: d.month.map(MONTHS.index) + 1)
    if (df.year == -999).all():
        da = (
            df.drop(columns="year").set_index(["month", "lat", "lon"]).value.to_xarray()
        )
    else:
        y0 = int(df.year.min())
        df["time"] = (df.year - y0) * 365 + MIDS[df.month - 1]
        da = df.set_index(["time", "lat", "lon"]).value.to_xarray()
        da.time.attrs = {"units": f"days since {y0}-01-01", "calendar": "noleap"}
    return (
        da.astype("float32")
        .rename(name)
        .assign_attrs(units=UNITS.get(name, ""))
        .to_dataset()
    )


def daily(path: str) -> xr.Dataset:
    df = read(
        path, ["lon", "lat", "var", "area", "year", "month", "day", "value", "region"]
    )
    name = var(df)
    y0 = int(df.year.min())
    start = (df.year - y0) * 365 + np.cumsum(DAYS)[df.month - 1] - DAYS[df.month - 1]
    df["time"] = start + df.day - 1 + 0.5
    da = df.set_index(["time", "lat", "lon"]).value.to_xarray()
    da.time.attrs = {"units": f"days since {y0}-01-01", "calendar": "noleap"}
    return (
        da.astype("float32")
        .rename(name)
        .assign_attrs(units=UNITS.get(name, ""))
        .to_dataset()
    )


def elev(path: str) -> xr.Dataset:
    df = read(path, ["lon", "lat", "var", "area", "elev", "region"])
    ds = df.set_index(["lat", "lon"])[["elev"]].to_xarray().astype("float32")
    ds.elev.attrs = {"units": "m"}
    return ds


def soil(path: str) -> xr.Dataset:
    df = read(
        path,
        [
            "lon",
            "lat",
            "var",
            "area",
            "sand",
            "silt",
            "clay",
            "wsoil",
            "source",
            "region",
        ],
    )
    return (
        df.set_index(["lat", "lon"])[["sand", "silt", "clay"]]
        .to_xarray()
        .astype("float32")
    )


def ndep(path: str) -> xr.Dataset:
    df = read(path, ["lon", "lat", "year", "value"])
    if df.year.nunique() == 1:
        return (
            df.set_index(["lat", "lon"])
            .value.to_xarray()
            .astype("float32")
            .rename("ndep")
            .to_dataset()
        )
    y0 = int(df.year.min())
    df["time"] = days_since(df.year, y0)
    da = (
        df.set_index(["time", "lat", "lon"])
        .value.to_xarray()
        .astype("float32")
        .rename("ndep")
    )
    da.time.attrs = {"units": f"days since {y0}-01-01", "calendar": "noleap"}
    return da.to_dataset()


def co2(path: str) -> xr.Dataset:
    df = pd.read_csv(path, header=None, names=["year", "co2"], skipinitialspace=True)
    y0 = int(df.year.min())
    ds = xr.Dataset(
        {"co2": ("time", df.co2.to_numpy().astype("float32"), {"units": "ppmv"})}
    )
    ds["time"] = (
        "time",
        days_since(df.year, y0),
        {"units": f"days since {y0}-01-01", "calendar": "noleap"},
    )
    return ds


def lulc(path: str) -> xr.Dataset:
    df = read(path, ["lon", "lat", "var", *LULC, "region"])
    keys = ["cohort", "lat", "lon"]
    if df.year.nunique() > 1:
        y0 = int(df.year.min())
        df["time"] = days_since(df.year, y0)
        keys = ["time", *keys]
    ds = df.set_index(keys)[LULC[3:]].to_xarray()
    for k in LULC_INT:
        ds[k] = ds[k].fillna(INT_FILL).astype("int64")
        ds[k].encoding["_FillValue"] = np.int64(INT_FILL)
    for k in LULC[3:5] + LULC[15:]:
        ds[k] = ds[k].astype("float32")
    ds["cohort"] = ds["cohort"].astype("int64")
    if "time" in ds:
        ds["time"].attrs = {"units": f"days since {y0}-01-01", "calendar": "noleap"}
    return ds


def regular(ds: xr.Dataset, grid: str | None) -> xr.Dataset:
    """Put the data on the lat/lon axes of grid, or fill the axes to a regular grid (cells without a record drop out)."""
    if grid:
        with xr.open_dataset(grid) as g:
            return ds.reindex(lat=g.lat.values.round(4), lon=g.lon.values.round(4))
    new = {}
    for c in ("lat", "lon"):
        if c in ds.coords and ds[c].size > 1:
            step = np.diff(np.sort(ds[c].values)).min()
            new[c] = np.round(np.arange(ds[c].min(), ds[c].max() + step / 2, step), 4)
    return ds.reindex(new)


KINDS = {
    "clm": clm,
    "daily": daily,
    "elev": elev,
    "soil": soil,
    "ndep": ndep,
    "co2": co2,
    "lulc": lulc,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kind", choices=KINDS)
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument(
        "--grid",
        help="NetCDF file whose lat and lon axes are used, for example climate.nc",
    )
    a = ap.parse_args()
    ds = regular(xr.merge([KINDS[a.kind](f) for f in a.files]), a.grid)
    for c in ("lat", "lon"):
        if c in ds.coords:
            ds[c] = ds[c].astype("float32")
    out = Path(a.output)
    if out.exists():
        with xr.open_dataset(out) as old:
            ds = xr.merge([old.load(), ds])
    ds.to_netcdf(out)
    print(out)


if __name__ == "__main__":
    main()
