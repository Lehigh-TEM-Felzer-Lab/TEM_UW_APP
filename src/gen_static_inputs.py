"""Download global datasets and write the TEM_2026 input files for a region.

Each subcommand writes one file of INPUT/ on the grid given by --bbox LON_MIN LON_MAX LAT_MIN LAT_MAX (default: the globe) and --res
(cell centres on multiples of res from the minimum). The subcommand all writes every static input including lulc.nc.
See docs/global_data.md of TEM_UW_APP for the sources, units and caveats.

    python src/gen_static_inputs.py --out INPUT --bbox -125 -110 32 49 --res 0.5 all --cohorts natural crops
    python src/gen_static_inputs.py --out INPUT --bbox -125 -110 32 49 co2 --start 2015 --end 2100
    python src/gen_static_inputs.py --out INPUT --bbox -125 -110 32 49 lulc --year 2015 --cohorts natural --min-area 10
"""

import argparse
import io
import json
import os
import subprocess
import tarfile
import urllib.request
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
HRMC = "LISOTD_HRMC_V2.3.2015.nc"
HRMC_OPEN = (
    "https://ghrc.nsstc.nasa.gov/pub/lis/climatology/LIS-OTD/HRMC/data/nc/" + HRMC
)
CMR = "https://cmr.earthdata.nasa.gov/search/granules.json?collection_concept_id=C1995863290-GHRC_DAAC&page_size=50"
WORLDPOP = "https://data.worldpop.org/GIS/Population/Global_2000_2020/2020/0_Mosaicked/ppp_2020_1km_Aggregated.tif"
ISIMIP_NDEP = "https://files.isimip.org/ISIMIP3b/InputData/socioeconomic/n-deposition/histsoc/ndep-{}_histsoc_monthly_1850_2014.nc"
CEDA_OZONE = "https://dap.ceda.ac.uk/badc/proc-earth-model/data/ozone-metrics/v2.7/CCMI_SurfaceOzoneObs_1x1_Monthly_v2.7.nc"
DAYS = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
EARTH_RADIUS_KM = 6371.0088
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
    "natural": (NATURAL, None),
    "crops": (CROPS, 50),
    "pasture": (("pastr",), 51),
}  # cohort: (LUH2 states, TEM currentveg)
LUH2 = "https://luh.umd.edu/LUH2/LUH2_v2h"
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


def fetch(url: str, cache: Path, header: str | None = None) -> Path:
    """Download into the cache once; an interrupted transfer is resumed with wget -c."""
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / url.split("?")[0].rsplit("/", 1)[1]
    if not path.exists():
        part = path.with_name(path.name + ".part")
        cmd = ["wget", "-q", "-c", "-O", str(part)] + (
            ["--header", header] if header else []
        )
        for _ in range(10):
            if subprocess.run([*cmd, url], check=False).returncode == 0:
                part.rename(path)
                return path
        raise SystemExit(f"download failed: {url}")
    return path


def hrmc_file(cache: Path) -> Path:
    """LIS/OTD HRMC: the open GHRC archive first, then the links NASA CMR lists (Earthdata Login: EARTHDATA_TOKEN or ~/.netrc)."""
    path = cache / HRMC
    if path.exists():
        return path
    cache.mkdir(parents=True, exist_ok=True)
    urls = [HRMC_OPEN]
    try:
        with urllib.request.urlopen(CMR, timeout=60) as r:
            for e in json.load(r)["feed"]["entry"]:
                urls += [
                    link["href"]
                    for link in e.get("links", [])
                    if link["href"].startswith("https")
                    and link["href"].endswith("/" + HRMC)
                ]
    except OSError:
        pass
    token = os.environ.get("EARTHDATA_TOKEN")
    cookies = str(Path.home() / ".urs_cookies")
    for url in dict.fromkeys(urls):
        cmd = ["wget", "-q", "-t", "2", "-O", str(path) + ".part"]
        if "earthdata" in url:
            cmd += (
                ["--header", f"Authorization: Bearer {token}"]
                if token
                else [
                    "--load-cookies",
                    cookies,
                    "--save-cookies",
                    cookies,
                    "--keep-session-cookies",
                ]
            )
        if subprocess.run([*cmd, url], check=False).returncode == 0:
            Path(str(path) + ".part").rename(path)
            return path
    raise SystemExit(
        "lightning: LIS/OTD HRMC download failed. NASA asks for a free Earthdata Login (EDL): "
        "get an EDL token at https://urs.earthdata.nasa.gov (profile > Generate Token) and set "
        "EARTHDATA_TOKEN, or put the login in ~/.netrc "
        "(machine urs.earthdata.nasa.gov login <user> password <password>)"
    )


def target(a: argparse.Namespace) -> tuple[np.ndarray, np.ndarray]:
    lon = np.arange(a.lon_min, a.lon_max + a.res / 2, a.res).round(4)
    lat = np.arange(a.lat_min, a.lat_max + a.res / 2, a.res).round(4)
    return lon, lat


def box_mean(
    da: xr.DataArray,
    lon: np.ndarray,
    lat: np.ndarray,
    res: float,
    how: str = "mean",
) -> xr.DataArray:
    """Mean (or sum, how="sum") of the source cells that fall in each target cell (source names lon and lat, lon in -180..180)."""
    for name, c in (("lon", lon), ("lat", lat)):
        i = np.floor((da[name].values - (c[0] - res / 2)) / res).astype(int)
        keep = (i >= 0) & (i < c.size)
        da = (
            da.isel({name: keep})
            .groupby(xr.DataArray(i[keep], dims=name, name="i" + name))
            .reduce(getattr(np, "nan" + how), dim=name)
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


def lightning(a: argparse.Namespace) -> None:
    """Lightning flashes [km-2 month-1] by month: LIS/OTD 0.5 degree monthly flash rate climatology (HRMC v2.3.2015) times the days of the month."""
    ds = xr.open_dataset(a.file or hrmc_file(Path(a.cache)), decode_times=False)
    var = a.var or next(v for v in ds.data_vars if v.upper() == "HRMC_COM_FR")
    da = ds[var].squeeze()
    sizes = {720: "lon", 360: "lat", 12: "month"}
    da = da.rename({d: sizes[da.sizes[d]] for d in da.dims}).transpose(
        "month", "lat", "lon"
    )
    if "lon" not in da.coords:
        da = da.assign_coords(
            lon=np.arange(-179.75, 180, 0.5), lat=np.arange(-89.75, 90, 0.5)
        )
    da = da.where(da >= 0, 0.0) * xr.DataArray(DAYS, dims="month")
    da = da.assign_coords(lon=((da.lon + 180) % 360) - 180).sortby("lon").sortby("lat")
    lon, lat = target(a)
    fl = box_mean(da, lon, lat, a.res).assign_attrs(units="km-2 month-1")
    write(
        fl.rename("lightning_flashes")
        .to_dataset()
        .assign_coords(month=np.arange(1, 13)),
        a,
        "flash.nc",
    )


def population(a: argparse.Namespace) -> None:
    """Population density [km-2]: WorldPop 2020 persons per 1 km pixel summed in each target cell, divided by the cell area."""
    import rioxarray as rx

    da = rx.open_rasterio(
        a.file or fetch(WORLDPOP, Path(a.cache)),
        masked=True,
        chunks={"x": 6000, "y": 6000},
    ).squeeze(drop=True)
    lon, lat = target(a)
    da = da.rename(x="lon", y="lat").sortby("lat")
    da = da.sel(
        lon=slice(lon[0] - a.res, lon[-1] + a.res),
        lat=slice(lat[0] - a.res, lat[-1] + a.res),
    )
    people = box_mean(da.fillna(0.0), lon, lat, a.res, how="sum").fillna(0.0).compute()
    south = np.deg2rad(np.clip(lat - a.res / 2, -90, 90))
    north = np.deg2rad(np.clip(lat + a.res / 2, -90, 90))
    area = EARTH_RADIUS_KM**2 * np.deg2rad(a.res) * (np.sin(north) - np.sin(south))
    dens = (people / xr.DataArray(area, dims="lat", coords={"lat": lat})).astype(
        "float32"
    )
    write(
        dens.rename("population_density").assign_attrs(units="km-2").to_dataset(),
        a,
        "popdens.nc",
    )


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
    """AOT40 climatology (month, lat, lon): the gridded ozone metrics of CEDA (needs CEDA_TOKEN) or a NetCDF given by --file."""
    file = a.file
    if not file:
        token = os.environ.get("CEDA_TOKEN")
        if not token:
            raise SystemExit(
                "ozone: set CEDA_TOKEN (docs/global_data.md) or pass --file"
            )
        file = fetch(
            CEDA_OZONE + "?download=1",
            Path(a.cache),
            f"Authorization: Bearer {token}",
        )
    var = a.var or next(
        v for v in xr.open_dataset(file).data_vars if "aot40" in v.lower()
    )
    climatology(a, str(file), var, a.scale, "ozone", "ppb h", True)


def ndep(a: argparse.Namespace) -> None:
    """Annual N deposition [mg N m-2 yr-1]: ISIMIP3b NHx plus NOy (g N m-2 month-1) averaged over --start..--end, or a NetCDF given by --file."""
    if a.file:
        climatology(a, a.file, a.var, a.scale, "ndep", "mg N m-2 yr-1", False)
        return
    parts = []
    for v in ("nhx", "noy"):
        da = xr.open_dataset(
            fetch(ISIMIP_NDEP.format(v), Path(a.cache)), decode_times=False
        )[v]
        months = (a.end - a.start + 1) * 12
        first = (a.start - 1850) * 12
        parts.append(
            da.isel(time=slice(first, first + months)).sum("time")
            / (a.end - a.start + 1)
        )
    total = (parts[0] + parts[1]) * 1000.0  # g N m-2 to mg N m-2
    da = (
        total.assign_coords(lon=((total.lon + 180) % 360) - 180)
        .sortby("lon")
        .sortby("lat")
    )
    lon, lat = target(a)
    write(
        box_mean(da, lon, lat, a.res)
        .rename("ndep")
        .assign_attrs(units="mg N m-2 yr-1")
        .to_dataset(),
        a,
        "ndep.nc",
    )


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
    st = xr.open_dataset(
        a.luh2 or fetch(f"{LUH2}/states.nc", Path(a.cache)), decode_times=False
    )
    units = st["time"].attrs["units"]
    base = int(units.split("since")[1].strip().split("-")[0])
    # LUH2 latitudes run from north to south
    st = st.isel(time=a.year - base).sortby("lat")
    stat = xr.open_dataset(
        a.luh2_static or fetch(f"{LUH2}/staticData_quarterdeg.nc", Path(a.cache))
    ).sortby("lat")
    area = stat["carea"] * (1 - stat["icwtr"])
    sel = {k: v for k, v in COHORTS.items() if k in a.cohorts}
    n = len(sel)
    shape = (n, lat.size, lon.size)
    out = {
        k: np.full(shape, INT_FILL, "int64")
        for k in ("potveg", "currentveg", "subtype", "agstate", "agprevstate", "mxc")
    }
    chrt = np.full(shape, np.nan, "float32")
    for c, (names, veg) in enumerate(sel.values()):
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
        has = (grid > a.min_area) & (pot.values > 0)
        v = pot.values if veg is None else np.full_like(pot.values, veg)
        chrt[c] = np.where(has, grid, np.nan)
        out["potveg"][c] = np.where(has, pot.values, INT_FILL)
        out["currentveg"][c] = np.where(has, v, INT_FILL)
        out["subtype"][c] = np.where(has, v, INT_FILL)
        out["agstate"][c] = np.where(has, int(veg is not None), INT_FILL)
        out["agprevstate"][c] = np.where(has, int(veg is not None), INT_FILL)
    has = ~np.isnan(chrt)
    dims = ("cohort", "lat", "lon")
    ds = xr.Dataset(
        {
            "standage": (
                dims,
                np.where(
                    has,
                    np.where(
                        (np.array(list(sel)) == "natural")[:, None, None], 3000.0, 1.0
                    ),
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
        "flag_meanings": " ".join(sel),
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


def everything(a: argparse.Namespace) -> None:
    """Every static input: elev, soil, wind, ozone, ndep, static, lulc, flash and popdens (ozone and lightning are skipped without their login)."""
    a.file, a.var, a.scale, a.start, a.end = None, None, 1.0, 2005, 2014
    for f in (elev, soil, wind, ozone, ndep, static, lulc, lightning, population):
        try:
            f(a)
        except SystemExit as e:
            print("skipped:", e)


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--out", default="INPUT")
    p.add_argument("--cache", default="downloads")
    p.add_argument("--res", type=float, default=0.5)
    p.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        default=[-180, 179, -89, 89],
        metavar=("LON_MIN", "LON_MAX", "LAT_MIN", "LAT_MAX"),
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("co2")
    c.add_argument("--start", type=int, required=True)
    c.add_argument("--end", type=int, required=True)
    c.add_argument(
        "--scenario",
        help="text file with year and ppmv per line for the years after the observations",
    )
    c.set_defaults(f=co2)
    for name, f in (
        ("soil", soil),
        ("elev", elev),
        ("wind", wind),
        ("static", static),
    ):
        sub.add_parser(name).set_defaults(f=f)
    for name, f in (("lightning", lightning), ("population", population)):
        c = sub.add_parser(name)
        c.add_argument("--file", help="a file you downloaded instead of the default")
        c.add_argument("--var")
        c.set_defaults(f=f)
    for name, f in (("ozone", ozone), ("ndep", ndep)):
        c = sub.add_parser(name)
        c.add_argument(
            "--file",
            help="NetCDF with the data; without it the default source is downloaded",
        )
        c.add_argument("--var")
        c.add_argument(
            "--scale", type=float, default=1.0, help="factor from the units of the file"
        )
        c.add_argument(
            "--start", type=int, default=2005, help="ndep: first year averaged"
        )
        c.add_argument("--end", type=int, default=2014, help="ndep: last year averaged")
        c.set_defaults(f=f)
    for name, f in (("lulc", lulc), ("all", everything)):
        c = sub.add_parser(name)
        c.add_argument("--luh2", help="LUH2 states.nc; downloaded if not given")
        c.add_argument("--luh2-static", help="LUH2 staticData_quarterdeg.nc")
        c.add_argument("--year", type=int, default=2015, help="year of the LUH2 states")
        c.add_argument(
            "--cohorts",
            nargs="+",
            choices=list(COHORTS),
            default=list(COHORTS),
            help="cohorts to keep",
        )
        c.add_argument(
            "--min-area",
            type=float,
            default=1e-3,
            help="smallest cohort area kept in a cell [km2]",
        )
        c.set_defaults(f=f)
    a = p.parse_args()
    a.lon_min, a.lon_max, a.lat_min, a.lat_max = a.bbox
    a.f(a)


if __name__ == "__main__":
    main()
