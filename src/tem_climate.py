# tem_climate.py
"""Read the input NetCDF file(s) and convert its variables to TEM inputs (monthly or daily) on the model grid."""

import logging
import re
from glob import glob
from pathlib import Path

import metpy.calc as mpcalc
import metpy.xarray  # noqa: F401  registers the .metpy accessor
import numpy as np
import pandas as pd
import xarray as xr
from metpy.units import units
from pint import DimensionalityError

log = logging.getLogger("PREPROCESS")

RENAME = {
    "latitude": "lat",
    "longitude": "lon",
    "valid_time": "time",
    "x": "lon",
    "y": "lat",
}
STEP_SECONDS = {"hourly": 3600.0, "daily": 86400.0}


def open_dataset(
    path: Path | list[Path],
    bbox: tuple[float, float, float, float],
    frequency: str = "monthly",
) -> xr.Dataset:
    """Open the input file(s) (paths or globs), merge them by coordinates, normalise names and longitudes, subset to bbox."""
    paths = sorted(
        {f for p in (path if isinstance(path, list) else [path]) for f in glob(str(p))}
    )
    if not paths:
        raise FileNotFoundError(
            f"No file matches netcdf_input_file: {[str(p) for p in (path if isinstance(path, list) else [path])]}"
        )
    log.info("Reading %d input file(s)", len(paths))
    ds = xr.open_mfdataset(paths, combine="by_coords", chunks={})
    ds = ds.rename({k: v for k, v in RENAME.items() if k in ds.dims or k in ds.coords})
    ds = ds.assign_coords(lon=((ds.lon + 180) % 360) - 180).sortby("lon").sortby("lat")
    if "time" in ds.coords and not isinstance(ds.indexes["time"], pd.DatetimeIndex):
        # model calendars (noleap, 360_day): map to the standard calendar, repeating the value
        # before a missing day (29 February) so that every calendar day has a value
        ds = ds.convert_calendar(
            "standard", dim="time", missing=np.nan, use_cftime=False
        )
        if frequency in ("daily", "hourly"):
            ds = ds.ffill("time", limit=24 if frequency == "hourly" else 1)
    lon_min, lon_max, lat_min, lat_max = bbox
    return ds.sel(lon=slice(lon_min, lon_max), lat=slice(lat_min, lat_max))


def get(ds: xr.Dataset, varmap: dict, key: str) -> xr.DataArray | None:
    """Variable of the input file that netcdf_varmap assigns to key, or None if key is not mapped."""
    if key not in varmap:
        return None
    name = varmap[key]
    if name not in ds:
        raise KeyError(
            f"netcdf_varmap: '{name}' (TEM input '{key}') is not in the input file"
        )
    if "units" not in ds[name].attrs:
        raise ValueError(f"Input variable '{name}' has no 'units' attribute")
    return ds[name]


def convert(da: xr.DataArray, unit: str) -> xr.DataArray:
    """Convert da to unit using its units attribute (MetPy/pint, offset units included)."""
    try:
        out = da.metpy.quantify().metpy.convert_units(unit).metpy.dequantify()
    except DimensionalityError as error:
        raise ValueError(
            f"Input variable '{da.name}' has units '{da.attrs['units']}', not convertible to {unit}"
        ) from error
    return out.assign_attrs(units=unit)


def temperature(da: xr.DataArray, delta: bool = False) -> xr.DataArray:
    """Degrees Celsius, or a temperature difference in K when delta is true."""
    if delta:
        da = da.assign_attrs(
            units=re.sub(r"\bdegC\b|degree_Celsius", "delta_degC", da.attrs["units"])
        )
        return convert(da, "delta_degC")
    return convert(da, "degC")


def precipitation(da: xr.DataArray) -> xr.DataArray:
    """Precipitation as mm per day (kind 'rate') or mm per step (kind 'amount')."""
    unit = da.attrs["units"]
    per_month = re.sub(r"\s*(/\s*month|month-1)", "", unit)
    if per_month != unit:  # amount per calendar month, e.g. "mm month-1"
        return convert(da.assign_attrs(units=per_month), "mm").assign_attrs(
            kind="amount"
        )
    dim = units.Quantity(1.0, unit).dimensionality
    if (
        dim == units.Quantity(1.0, "kg m-2 s-1").dimensionality
    ):  # 1 kg m-2 = 1 mm of water
        return convert(da, "kg m-2 day-1").assign_attrs(kind="rate")
    if dim == units.Quantity(1.0, "kg m-2").dimensionality:
        return convert(da, "kg m-2").assign_attrs(kind="amount")
    if dim == units.Quantity(1.0, "m").dimensionality:
        return convert(da, "mm").assign_attrs(kind="amount")
    return convert(da, "mm day-1").assign_attrs(kind="rate")


def radiation(da: xr.DataArray, frequency: str) -> xr.DataArray:
    """Downward shortwave radiation in W m-2; energy per step (J m-2) is divided by the step length."""
    if (
        units.Quantity(1.0, da.attrs["units"]).dimensionality
        == units.Quantity(1.0, "J m-2").dimensionality
    ):
        return convert(da, "J m-2") / STEP_SECONDS[frequency]
    return convert(da, "W m-2")


def derive(
    name: str, ds: xr.Dataset, varmap: dict, frequency: str, surface_pressure_hpa: float
) -> xr.DataArray | None:
    """TEM variable name in TEM units on the file's native time step, or None if netcdf_varmap lacks it."""

    def has(*keys: str) -> bool:
        return all(k in varmap for k in keys)

    def var(key: str) -> xr.DataArray:
        return get(ds, varmap, key)

    if name == "tair":
        if has("tair"):
            return temperature(var("tair"))
        if has("tmin", "tmax"):
            return (temperature(var("tmin")) + temperature(var("tmax"))) / 2
    elif name == "dtr":
        if has("dtr"):
            return temperature(var("dtr"), delta=True)
        if has("tmin", "tmax"):
            return temperature(var("tmax")) - temperature(var("tmin"))
    elif name == "prec" and has("prec"):
        return precipitation(var("prec"))
    elif name == "nirr" and has("nirr"):
        return radiation(var("nirr"), frequency)
    elif name == "vpr":
        if has("vpr"):
            return convert(var("vpr"), "hPa")
        if has("dewpoint"):
            e = mpcalc.saturation_vapor_pressure(var("dewpoint").metpy.quantify())
            return e.metpy.convert_units("hPa").metpy.dequantify()
        if has("huss"):
            p = (
                var("ps").metpy.quantify()
                if has("ps")
                else units.Quantity(surface_pressure_hpa, "hPa")
            )
            q = var("huss").metpy.quantify()
            e = mpcalc.vapor_pressure(p, mpcalc.mixing_ratio_from_specific_humidity(q))
            return e.metpy.convert_units("hPa").metpy.dequantify()
    elif name == "wind":
        if has("wind"):
            return convert(var("wind"), "m s-1")
        if has("u10", "v10"):
            speed = mpcalc.wind_speed(
                var("u10").metpy.quantify(), var("v10").metpy.quantify()
            )
            return speed.metpy.convert_units("m s-1").metpy.dequantify()
    elif name == "elev" and has("elev"):
        return convert(var("elev"), "m")
    return None


def to_step(da: xr.DataArray, name: str, frequency: str, step: str) -> xr.DataArray:
    """Values on the TEM time step (monthly or daily) in TEM units.

    Precipitation becomes mm per month or mm per day. Daily data cannot be built from monthly data.
    """
    if name == "elev" or "month" in da.dims:
        return da
    freq = {"monthly": "MS", "daily": "D"}[step]
    if step == "daily" and frequency == "monthly":
        raise ValueError(
            f"{name}: the core needs daily values but netcdf_input_frequency is monthly"
        )
    same = frequency == step
    if name == "prec":
        if da.attrs["kind"] == "amount":
            out = da if same else da.resample(time=freq).sum()
        else:
            out = da if same else da.resample(time=freq).mean()
            if step == "monthly":
                out = out * out.time.dt.days_in_month
    else:
        out = da if same else da.resample(time=freq).mean()
    period = {"monthly": "M", "daily": "D"}[step]
    return out.assign_coords(time=out.time.to_index().to_period(period).to_timestamp())


def to_cells(
    da: xr.DataArray, cells: pd.DataFrame, resolution: float, method: str
) -> xr.DataArray:
    """Regrid to the cell centres: dimension 'cell' replaces lat and lon."""
    lon_c = xr.DataArray(cells["lon"].values, dims="cell")
    lat_c = xr.DataArray(cells["lat"].values, dims="cell")
    if method == "box_mean" and source_res(da) < resolution * 0.99:
        half = resolution / 2
        w_lon = ((da.lon - lon_c >= -half) & (da.lon - lon_c < half)).astype(float)
        w_lat = ((da.lat - lat_c >= -half) & (da.lat - lat_c < half)).astype(
            float
        ) * np.cos(np.deg2rad(da.lat))
        valid = da.notnull()
        num = xr.dot(da.fillna(0.0), w_lat, w_lon, dim=["lat", "lon"])
        den = xr.dot(valid.astype(float), w_lat, w_lon, dim=["lat", "lon"])
        return (num / den.where(den > 0)).assign_coords(lon=lon_c, lat=lat_c)
    if method == "nearest" or abs(source_res(da) - resolution) < 1e-6:
        return da.sel(lon=lon_c, lat=lat_c, method="nearest", tolerance=resolution / 2)
    return da.interp(lon=lon_c, lat=lat_c, method="linear")


def source_res(da: xr.DataArray) -> float:
    return (
        float(np.median(np.abs(np.diff(da.lon.values)))) if da.lon.size > 1 else np.inf
    )


def cell_area_km2(lat: np.ndarray, resolution: float) -> np.ndarray:
    """Area (km2) of a resolution-degree cell centred on lat."""
    radius = 6371.0
    lat1, lat2 = np.deg2rad(lat - resolution / 2), np.deg2rad(lat + resolution / 2)
    return radius**2 * np.deg2rad(resolution) * (np.sin(lat2) - np.sin(lat1))
