#!/usr/bin/env python3
"""The land cover is aggregated by land area and never placed over water (src/tem_regrid.py).

A 0.5 degree land cover on 4 x 1 target cells of 1 degree: a cell inside the land, a cell with 3 of 4 source cells land, a cell with
1 of 4 land (mostly water), and a cell whose categories differ between the count and the area of the source cells.
Run: python3 tests/test_lulc_regrid.py
"""
import os, sys
import numpy as np
import xarray as xr

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import tem_regrid

lon, lat = np.array([0.0, 1.0, 2.0, 3.0]), np.array([0.0])
src_lon, src_lat = -0.25 + 0.5 * np.arange(8), np.array([-0.25, 0.25])  # 8 x 2 source cells; target cell k covers src columns 2k, 2k+1
U = tem_regrid.cell_area_km2(lon, lat, 1.0)[0, 0] / 4  # land area of a fully land source cell
U = 3000.0  # km2 of land in a full 0.5 degree source cell near the equator; a 1 degree target cell is about 12360 km2 and needs half of that
area = np.zeros((1, 2, 8)); pot = np.full((1, 2, 8), np.nan); age = np.zeros((1, 2, 8))
area[0, :, 0:2] = U; pot[0, :, 0:2] = 4; age[0, :, 0:2] = 50                      # cell 0: all land
area[0, :, 2:4] = U; area[0, 1, 3] = 0.0; pot[0, :, 2:4] = 4; age[0, :, 2:4] = 80  # cell 1: 3 of 4 source cells land
area[0, 0, 4] = U; pot[0, 0, 4] = 4                                                # cell 2: 1 of 4 land, mostly water
area[0, :, 6:8] = 1000.0; pot[0, :, 6:8] = 4; age[0, :, 6:8] = 10                  # cell 3: three cells of type 4 with 1000 km2 each ...
area[0, 0, 6] = 4000.0; pot[0, 0, 6] = 9; age[0, 0, 6] = 200                       # ... and one cell of type 9 with 4000 km2
ds = xr.Dataset(
    {"chrtarea": (("cohort", "lat", "lon"), area), "potveg": (("cohort", "lat", "lon"), pot), "standage": (("cohort", "lat", "lon"), age)},
    coords={"cohort": [1], "lat": src_lat, "lon": src_lon},
)
out = tem_regrid.lulc_to_grid(ds, lon, lat, 1.0, land_fraction_min=0.5)
a, p, s = (out[k].values[0, 0] for k in ("chrtarea", "potveg", "standage"))
assert np.allclose(a[[0, 1]], [4 * U, 3 * U]), a            # areas are summed, water adds nothing
assert np.isnan(a[2]) and np.isnan(p[2]) and np.isnan(s[2]), "a cell that is mostly water must have no cohort"
assert p[3] == 9, "the category is the one with the largest land area, not the most frequent or the nearest"
assert np.isclose(s[0], 50.0) and np.isclose(s[1], 80.0) and np.isclose(s[3], (4000 * 200 + 3 * 1000 * 10) / 7000), s
assert np.isclose(np.nansum(a), 4 * U + 3 * U + 7000), "land area is conserved except in the cell dropped for being water"
print("ok: land cover regrid by area, water cells have no cohort")
