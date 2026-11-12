#!/usr/bin/env python3
"""A land cover on the model grid is still filtered by land_fraction_min (src/driver.py regrid_file, src/tem_regrid.py).

Before, a land cover on the same grid as the model skipped lulc_to_grid, so cells with 1% land (ice caps, Arctic islands) kept their
cohorts and the model stopped at them: SoilGrids, ETOPO and WorldClim have no data there. Mixed potential types are written twice (primary and
primary_second_component, each with the full area), and the second component must not count again towards the land area of the cell.
Run: python3 tests/test_lulc_ongrid.py
"""
import os
import sys
import tempfile

import numpy as np
import xarray as xr

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import tem_regrid

lon, lat = np.array([0.0, 1.0, 2.0, 3.0]), np.array([60.0])
cell = tem_regrid.cell_area_km2(lon, lat, 1.0)[0]
# cohorts: primary, primary_second_component
area = np.full((2, 1, 4), np.nan)
area[0, 0] = [1.0, 0.01, 0.30, 0.30]  # share of the cell: land, 1% land, mixed type with 30% land, a plain type with 30% land
area[1, 0, 2] = 0.30                  # the second component of the mixed cell carries the same area again
area = area * cell
ds = xr.Dataset(
    {"chrtarea": (("cohort", "lat", "lon"), area), "potveg": (("cohort", "lat", "lon"), np.where(np.isnan(area), np.nan, 8.0))},
    coords={"cohort": [1, 2], "lat": lat, "lon": lon},
)
ds["cohort"].attrs["flag_meanings"] = "primary primary_second_component"

out = tem_regrid.lulc_to_grid(ds, lon, lat, 1.0, land_fraction_min=0.5)
a = out["chrtarea"].values
assert np.isclose(a[0, 0, 0], cell[0]) and np.isnan(a[1, 0, 0]), "a land cell on the model grid is kept"
assert np.isnan(a[:, 0, 1]).all(), "a cell with 1% land is not land, also when the grid is the model grid"
assert np.isnan(a[:, 0, 2]).all(), "the two components of a mixed type count once: 30% land, not 60%"
assert np.isnan(a[:, 0, 3]).all(), "a plain cell with 30% land is not land"

# the same land cover with one source cell: no failure
one = tem_regrid.lulc_to_grid(ds.isel(lon=[0], lat=[0]), lon[:1], lat, 1.0, land_fraction_min=0.5)
assert np.isclose(one["chrtarea"].values[0, 0, 0], cell[0])

# through the driver, which needs the packages of env.yaml
try:
    import driver
except ImportError as e:
    print("skipped the driver check:", e)
else:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "lulc.nc")
        ds.to_netcdf(path)
        cfg = {"horizontal_resolution": 1.0, "land_fraction_min": 0.5, "regrid_method": "box_mean", "varmap": {}}
        got = driver.regrid_file(path, cfg, lon, lat, landcover=True)["chrtarea"].values
        assert np.isclose(got[0, 0, 0], cell[0]) and np.isnan(got[:, 0, 1:]).all(), got
print("ok: land_fraction_min applies on the model grid, mixed types count once")
