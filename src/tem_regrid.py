"""Land-aware regridding of the land-cover file to the model grid, with xarray and numpy.

The model does not interpolate and cannot place plants over water, so the land cover is aggregated by the area of land:

- chrtarea (km2 of land of a cohort) is summed over the source cells inside a target cell, by the share of each source cell
  that lies in it. Water is not in chrtarea, so it adds nothing.
- Categories (potveg, currentveg, subtype, agstate, agprevstate, fertflag, irrgflag) take the value with the largest land area of
  that cohort in the target cell (majority), never an average and never the value of the nearest centre.
- standage is the mean weighted by chrtarea.
- A target cell is land when its land area is at least land_fraction_min of the cell area. A cell that is not land, and a cohort
  that has no area in a land cell, get no data, so the model does not run it.

The source must be finer than the target or equal to it. Longitudes and latitudes are regular and increasing; weights are the
overlaps of the cell edges, in longitude and in the sine of latitude (areas on the sphere).
"""

import numpy as np
import xarray as xr

AREA = "chrtarea"
MEAN = ("standage",)
CATEGORICAL = (
    "potveg",
    "currentveg",
    "subtype",
    "agstate",
    "agprevstate",
    "fertflag",
    "irrgflag",
)
EARTH_KM = 6371.0


def _edges(centres: np.ndarray, res: float) -> np.ndarray:
    if centres.size == 1:  # a single source cell has the width of the model cells
        return np.array([centres[0] - res / 2, centres[0] + res / 2])
    mid = (centres[1:] + centres[:-1]) / 2
    return np.concatenate([[centres[0] - (mid[0] - centres[0])], mid, [centres[-1] + (centres[-1] - mid[-1])]])


def share(src: np.ndarray, dst: np.ndarray, res: float, sine: bool = False) -> np.ndarray:
    """(target, source) matrix: the fraction of each source cell that lies in each target cell."""
    se = _edges(np.asarray(src, float), res)
    de = np.append(np.asarray(dst, float) - res / 2, dst[-1] + res / 2)
    if sine:
        se, de = (np.sin(np.deg2rad(np.clip(e, -90, 90))) for e in (se, de))
    lo = np.maximum(de[:-1, None], se[None, :-1])
    hi = np.minimum(de[1:, None], se[None, 1:])
    return np.clip(hi - lo, 0, None) / (se[1:] - se[:-1])[None, :]


def cell_area_km2(lon: np.ndarray, lat: np.ndarray, res: float) -> np.ndarray:
    s = np.sin(np.deg2rad(np.clip(np.stack([lat - res / 2, lat + res / 2]), -90, 90)))
    ring = EARTH_KM**2 * np.deg2rad(res) * (s[1] - s[0])
    return np.repeat(ring[:, None], lon.size, axis=1)


def lulc_to_grid(ds: xr.Dataset, lon: np.ndarray, lat: np.ndarray, res: float, land_fraction_min: float = 0.5) -> xr.Dataset:
    """The cohorts of ds (cohort, lat, lon; lat and lon increasing) on the model grid. See the module text."""
    if AREA not in ds:
        raise ValueError(f"the land cover needs {AREA} (km2 of each cohort) to be regridded")
    src_res = float(np.median(np.abs(np.diff(ds.lon.values)))) if ds.lon.size > 1 else res
    if src_res > res * 1.01:
        raise ValueError(
            f"the land cover has {src_res:g} degree cells, coarser than the model grid of {res:g}: make the land cover at the model resolution"
        )
    a = ds[AREA].transpose("cohort", "lat", "lon").fillna(0.0).values.astype(float)
    wlat, wlon = share(ds.lat.values, lat, res, sine=True), share(ds.lon.values, lon, res)

    def box_sum(x: np.ndarray) -> np.ndarray:
        return np.einsum("ij,cjk,lk->cil", wlat, x, wlon, optimize=True)

    area = box_sum(a)
    # A mixed potential type is written twice, once per component, each with the full area (lulc.nc: "..._second_component"), so the
    # second components must not be counted again in the land area of the cell.
    names = str(ds.cohort.attrs.get("flag_meanings", "")).split()
    second = np.array([n.endswith("_second_component") for n in names] if len(names) == area.shape[0] else [False] * area.shape[0])
    land = area[~second].sum(0) >= land_fraction_min * cell_area_km2(lon, lat, res)
    ok = (area > 0) & land[None]
    dims, coords = ("cohort", "lat", "lon"), {"cohort": ds.cohort, "lat": lat, "lon": lon}
    out = {AREA: xr.DataArray(np.where(ok, area, np.nan), dims=dims, coords=coords, attrs=ds[AREA].attrs)}
    for name in MEAN:
        if name in ds:
            x = np.nan_to_num(ds[name].transpose(*dims).values.astype(float))
            mean = box_sum(x * a) / np.where(area > 0, area, 1.0)
            out[name] = xr.DataArray(np.where(ok, mean, np.nan), dims=dims, coords=coords, attrs=ds[name].attrs)
    for name in CATEGORICAL:
        if name not in ds:
            continue
        v = ds[name].transpose(*dims).values.astype(float)
        best, best_area = np.full(area.shape, np.nan), np.zeros(area.shape)
        for c in np.unique(v[np.isfinite(v)]):
            w = box_sum(np.where(v == c, a, 0.0))
            better = w > best_area
            best, best_area = np.where(better, c, best), np.where(better, w, best_area)
        out[name] = xr.DataArray(np.where(ok, best, np.nan), dims=dims, coords=coords, attrs=ds[name].attrs)
    return xr.Dataset(out)
