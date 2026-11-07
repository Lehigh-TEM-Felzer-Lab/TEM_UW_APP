# tem_output_nc.py
"""Convert the text output of a TEM core (HIST/) to NetCDF files in OUTPUT/."""

import datetime
import logging
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

import tem_case
import tem_config
import tem_xml

log = logging.getLogger("CONVERT")

# columns before the statistics (total, max, avg, min) and the 12, 365 or 366 values of a row
OUT_HEAD = [
    "lon", "lat", "varname", "cohort", "standage", "potveg", "currentveg", "subtype", "cmnt",
    "psiplusc", "qlcon", "carea", "subarea", "year",
]  # fmt: skip
CLM_HEAD = ["lon", "lat", "varname", "carea", "year"]
META = ["standage", "potveg", "currentveg", "subtype", "cmnt", "carea", "subarea"]
INTEGERS = {"standage", "potveg", "currentveg", "subtype", "cmnt", "carea", "subarea"}
MAX_VALUES = 366


def output_files(case: Path) -> tuple[list[Path], list[Path], list[Path]]:
    """Model output files and climate files named by the XML, and the other files of HIST/."""
    xml = case / tem_case.XML_NAME
    hist = case / "HIST"

    def named(tag: str) -> list[Path]:
        names = tem_xml.text(xml, tag).split(",")
        return [
            hist / Path(n.strip()).name
            for n in names
            if n.strip() not in ("", "missing")
        ]

    tem, clm = named("temoutfiles"), named("clmoutfiles")
    absent = [p.name for p in [*tem, *clm] if not p.exists()]
    if absent:
        log.warning(
            "Listed in the XML but not in HIST (the run may have stopped early): %s",
            absent,
        )
    tem, clm = [p for p in tem if p.exists()], [p for p in clm if p.exists()]
    other = sorted(p for p in hist.iterdir() if p.is_file() and p not in {*tem, *clm})
    return tem, clm, other


def read_file(path: Path, head: list[str], keys: list[str]):
    """(variable name, step kind, DataArray(keys..., month|day), metadata rows) of one output file."""
    first = len(head) + 4
    raw = pd.read_csv(
        path, header=None, names=range(first + MAX_VALUES + 1), skipinitialspace=True
    )
    values = raw.iloc[:, first:].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    n = int(np.isfinite(values).any(axis=0).nonzero()[0].max()) + 1
    kind = "month" if n <= 12 else "day"
    n = 12 if kind == "month" else MAX_VALUES
    values = np.where(
        values[:, :n] < -9998, np.nan, values[:, :n]
    )  # -999999.9 marks missing
    table = raw.iloc[:, : len(head)].set_axis(head, axis=1)
    frame = pd.DataFrame(
        values, columns=range(1, n + 1), index=pd.MultiIndex.from_frame(table[keys])
    )
    keep = ~frame.index.duplicated(keep="last")
    da = frame[keep].to_xarray().to_array(kind)
    meta = table[keep].set_index(keys)[[m for m in META if m in table]].to_xarray()
    return str(table["varname"].iloc[0]).strip(), kind, da, meta


def stamp(ds: xr.Dataset, kind: str) -> xr.Dataset:
    """Replace year and month (or day of year) by a time coordinate, the start of each period."""
    ds = ds.transpose("year", kind, ...).stack(time=("year", kind))
    years = ds.indexes["time"].get_level_values("year")
    step = ds.indexes["time"].get_level_values(kind) - 1
    start = pd.to_datetime(years.astype(str), format="%Y")
    if kind == "month":
        time = pd.DatetimeIndex(
            [s + pd.DateOffset(months=int(m)) for s, m in zip(start, step, strict=True)]
        )
    else:
        time = start + pd.to_timedelta(step, unit="D")
    valid = np.flatnonzero(
        time.year == years
    )  # day 366 of a common year does not exist
    ds = (
        ds.isel(time=valid)
        .reset_index("time", drop=True)
        .assign_coords(time=time[valid])
    )
    return ds.transpose("time", ..., "lat", "lon", missing_dims="ignore")


def describe(
    da: xr.DataArray, name: str, table: pd.DataFrame, kind: str
) -> xr.DataArray:
    """Attach long_name and units from tables/tem_variables.csv (monthly rates become daily for daily output)."""
    long_name, units = (
        table.loc[name, ["long_name", "units"]] if name in table.index else (name, "")
    )
    if kind == "day":
        units = units.replace("month-1", "day-1")
    return da.assign_attrs(long_name=long_name, units=units)


def aggregate(ds: xr.Dataset, freq: str, step: str) -> xr.Dataset:
    """Resample to months (MS) or years (YS): rates (units ending day-1 or month-1) are summed, states averaged."""
    out = xr.Dataset()
    for name, da in ds.data_vars.items():
        units = da.attrs.get("units", "")
        rate = units.endswith(("day-1", "month-1"))
        grouped = da.resample(time=freq)
        res = grouped.sum(skipna=False) if rate else grouped.mean()
        base = units.rsplit(" ", 1)[0] if rate else units
        out[name] = res.assign_attrs(
            long_name=da.attrs["long_name"],
            units=f"{base} {step}-1" if rate else units,
            cell_methods=f"time: {'sum' if rate else 'mean'}",
        )
    return out


def write(ds: xr.Dataset, stem: str, title: str, period: str, cfg: dict) -> None:
    """OUTPUT/<stem>_<case>_<period>.nc: CF attributes, float32, compressed."""
    path = cfg["case_dir"] / "OUTPUT" / f"{stem}_{cfg['case_name']}_{period}.nc"
    ds = ds.assign_attrs(
        title=title,
        Conventions="CF-1.8",
        institution="Lehigh University, Felzer Lab",
        source=f"TEM core {cfg['profile']['name']}; case prepared with TUP",
        case_name=cfg["case_name"],
        time_convention="time is the start of the year, month or day; values cover the whole period",
        history=f"{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%dT%H:%M:%SZ} created by src/driver.py convert",
    )
    ds["lat"].attrs = {
        "long_name": "latitude of cell centre",
        "units": "degrees_north",
        "standard_name": "latitude",
    }
    ds["lon"].attrs = {
        "long_name": "longitude of cell centre",
        "units": "degrees_east",
        "standard_name": "longitude",
    }
    encoding = {}
    for name, da in ds.data_vars.items():
        encoding[name] = {"zlib": True, "complevel": 4}
        if name in INTEGERS:
            encoding[name].update(dtype="int32", _FillValue=-1)
        elif da.dtype.kind == "f":
            encoding[name]["dtype"] = "float32"
    ds.to_netcdf(path, encoding=encoding)
    log.info("Wrote %s", path)


def collect(files: list[Path], head: list[str], keys: list[str], table: pd.DataFrame):
    """Datasets by step kind (month, day) of all files, and the cohort attributes of the first file."""
    parts: dict[str, list[xr.DataArray]] = {"month": [], "day": []}
    attrs = None
    for path in files:
        name, kind, da, meta = read_file(path, head, keys)
        parts[kind].append(describe(da, name, table, kind).rename(name.lower()))
        attrs = meta if attrs is None else attrs
    sets = {k: xr.merge(v, join="outer") for k, v in parts.items() if v}
    return {k: stamp(v, k) for k, v in sets.items()}, attrs


def run(cfg: dict) -> None:
    """Convert every file of HIST/ to NetCDF; HIST/ is deleted afterwards unless keep_hist is true."""
    case = cfg["case_dir"]
    (case / "OUTPUT").mkdir(exist_ok=True)
    tem_files, clm_files, other = output_files(case)
    if not tem_files:
        raise FileNotFoundError(
            f"No model output files named by the XML in {case / 'HIST'}"
        )
    if other:
        log.warning("Not converted (not named by the XML): %s", [p.name for p in other])
    table = pd.read_csv(
        tem_config.ROOT / "tables" / "tem_variables.csv",
        keep_default_na=False,
        index_col="name",
    )
    y0, y1 = cfg["start_year"], cfg["end_year"]
    periods = {
        "year": f"{y0}-{y1}",
        "month": f"{y0}01-{y1}12",
        "day": f"{y0}0101-{y1}1231",
    }

    sets, attrs = collect(tem_files, OUT_HEAD, ["year", "cohort", "lat", "lon"], table)
    cohorts = None
    if (
        attrs is not None
    ):  # cohort attributes as an annual dataset on the same time axis
        cohorts = attrs.rename(year="time").assign_coords(
            time=pd.to_datetime(attrs.year.astype(str).values, format="%Y")
        )
    for kind, ds in sets.items():
        if kind == "day":
            write(ds, "tem_daily", "TEM daily output by cohort", periods["day"], cfg)
            suffix = "_from_daily"
        else:
            write(
                ds, "tem_monthly", "TEM monthly output by cohort", periods["month"], cfg
            )
            suffix = ""
        if kind == "day":
            month = aggregate(ds, "MS", "month")
            write(
                month,
                f"tem_monthly{suffix}",
                "TEM monthly output by cohort, aggregated from daily output",
                periods["month"],
                cfg,
            )
            source = month
        else:
            source = ds
        year = aggregate(source, "YS", "yr")
        year = year.merge(cohorts) if cohorts is not None else year
        write(
            year,
            f"tem_annual{suffix}",
            "TEM annual output by cohort",
            periods["year"],
            cfg,
        )

    clm_sets, _ = collect(clm_files, CLM_HEAD, ["year", "lat", "lon"], table)
    for kind, ds in clm_sets.items():
        stem = "tem_climate_daily" if kind == "day" else "tem_climate_monthly"
        write(ds, stem, "Climate echoed by the TEM core", periods[kind], cfg)

    if not cfg["keep_hist"]:
        shutil.rmtree(case / "HIST")
        log.info("Removed %s", case / "HIST")
