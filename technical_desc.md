# TEM_UW_APP technical description

Build options, the workflow and the keys of `run_config.yaml` are in [README.md](README.md) and [config_desc.md](config_desc.md). This file describes how the input files are built and where the data come from.

# Global input data

`src/gen_static_inputs.py` writes the input files of XTEM for any bounding box and resolution (run it from the root of TEM_UW_APP).
The commands below are for a 0.5 degree box over the western United States; `--bbox` takes `LON_MIN LON_MAX LAT_MIN LAT_MAX` and defaults to the globe.
Needs `pip install xarray netcdf4 pandas scipy rioxarray` and `wget`.

```bash
A="--out INPUT --cache downloads --bbox -125 -110 32 49 --res 0.5"
python src/gen_static_inputs.py $A co2 --start 2015 --end 2024
python src/gen_static_inputs.py $A all --tcomm XTEM/params/gdstem/tcomm45_lulc.yaml --year 2015 --cohorts primary secondary crops pasture urban --min-area 1
```

`all` writes `elev.nc`, `soil.nc`, `wind.nc`, `ozone.nc`, `ndep.nc`, `static.nc`, `lulc.nc`, `flash.nc` and `popdens.nc`; the ozone and lightning steps are skipped with a message if their login is missing
(`CEDA_TOKEN`, `EARTHDATA_TOKEN`, see below), and the optional `gdp` and `cropfire` steps if no `--file` is given (see Fire inputs). Each step can also be run alone (`soil`, `elev`, `wind`, `ndep --start 2005 --end 2014`, `ozone`, `lightning`, `population`, `gdp`, `cropfire`, `static`, `lulc`).
`--cohorts` keeps only the listed cohorts (`primary`, `secondary`, `crops`, `pasture`, `urban`; the cohort dimension of `lulc.nc` follows the order given here) and `--min-area` drops cohorts smaller than that area in a cell (km2).
LUH2 (6 GB) is downloaded unless `--luh2` and `--luh2-static` point to local copies.

Every step downloads its source into `--cache` once. `tools/run_test.py` runs all of them for the globe at 1 degree.
`static` merges the elevation, soil, wind, ozone and N deposition files into `static.nc`. The app makes `climate.nc` from climate files such as those of `src/gen_climate_inputs.py` (see Climate forcing).
The regridding is the mean of the source cells in a target cell, so the target should be coarser than the source.

## Climate forcing

```bash
python src/gen_climate_inputs.py --out INPUT --bbox -125 -110 32 49 --start 2000 --end 2019 era5      # needs ~/.cdsapirc
python src/gen_climate_inputs.py --out INPUT --bbox -125 -110 32 49 --start 2000 --end 2019 gridmet
python src/gen_climate_inputs.py --out INPUT --bbox -125 -110 32 49 --start 2000 --end 2099 maca --model BNU-ESM --scenario rcp85
python src/gen_climate_inputs.py --out INPUT --bbox -125 -110 32 49 --start 2000 --end 2099 cmip6 --model MPI-ESM1-2-HR --scenario ssp245
```

Each source writes `climate_<source>.nc` (daily, `tmin`, `tmax`, `prec`, `nirr`, and `dewpoint` or `huss`; `tair` for ERA5 and CMIP6) with the units of the source, and `varmap_<source>.yaml`.
Set `climate_file` and `netcdf_climate_in_frequency: daily` and paste the varmap into `run_config.yaml`; the app converts the units and averages to months.

| Source | Data | Access |
|---|---|---|
| `era5` | ERA5 daily statistics, 0.25 degree, global (Hersbach et al. 2020) | Copernicus CDS dataset `derived-era5-single-levels-daily-statistics`; `--grid 1.0/1.0` requests a coarser grid |
| `gridmet` | gridMET, 4 km, conterminous United States, from 1979 (Abatzoglou 2013) | OPeNDAP at reacchpna.org, variables `tmmx`, `tmmn`, `pr`, `srad`, `sph` |
| `maca` | MACAv2-METDATA, 4 km, conterminous United States, 1950-2099 (Abatzoglou and Brown 2012) | OPeNDAP at reacchpna.org; `--model`, `--scenario rcp45` or `rcp85`, `--member` (default `r1i1p1`) |
| `cmip6` | CMIP6 daily output, model grid (Eyring et al. 2016) | Pangeo Google Cloud archive (`pip install gcsfs zarr`); `--model`, `--scenario` (for example `ssp245`) for years after 2014, `--member` |

The gridMET, MACA and CMIP6 downloads were tested on a 2 x 2 degree box for 2013 and 2014 and the app converted their units. The ERA5 request needs a CDS account and was not run here.
The files for nitrogen fertilizer and for yearly land-cover change are not generated.

## What the model needs from the files

All files of a run must be on the same grid (the same `lon` and `lat` values, so the same resolution) and every file with a time axis must start in `clmstartyr`, be regular at the model step, a month or a year, and cover the run; `time` carries CF units (`days since ...`, `noleap`, `365_day` or `standard` calendar). XTEM checks this at load and stops with the file and the values that differ (`tem_core/tem_input_check.cpp`), so use one `--bbox` and one `--res` for every step. A cell runs where `lulc.nc` has a cohort and, if a `mask` is mapped in `varmap`, where the mask is above 0; every other input must have data there. The fire files below are needed only with `veg_fire: 1`, and `gdp.nc` and `crop.nc` only for the GDSTEM-FIRE terms.

## Fire inputs

`lightning` and `population` write `flash.nc` and `popdens.nc` (sources in the table below). The two optional files switch on the GDSTEM-FIRE terms (fuel load from the carbon pools, GDP and population suppression, crop fire) and are made from files you download, because the sources need a manual download:

```bash
# GDP per person, Kummu et al. (2018), https://doi.org/10.5061/dryad.dk1j0 (2011 international dollars; --scale 0.001 gives thousand dollars)
python src/gen_static_inputs.py $A gdp --file downloads/GDP_per_capita_PPP_1990_2015_v2.nc --var GDP_per_capita_PPP --scale 0.001
# month of crop burning, abm_lf of a CLM5 surface dataset (CESM inputdata server), 1 to 12, 0 for none
python src/gen_static_inputs.py $A cropfire --file downloads/surfdata_clm5.nc --var abm_lf
```

`gdp.nc` has `gdp` (thousand US dollars per person, `lat`, `lon`) and `crop.nc` has `cropfire_month`; set `gdp_file` and `cropfire_file` in `run_config.yaml`. The file and variable names above are those I expect for these datasets and were not checked against the downloads: list the variables of your file (`ncdump -h`) and pass the right `--var`. The commands were tested only on synthetic files with the same layout. The model also needs per-community fire parameters in the vegetation YAML (`fsr`, `fd`, `rswf_min`, `rswf_max`), which `params/` of XTEM has. The fire return interval `FRI` of `lulc.nc` is 2000 years.

## Sources

| File | Variable (unit) | Source |
|---|---|---|
| `co2.nc` | `co2` (ppmv) | NOAA GML Mauna Loa annual mean; SSP scenarios for later years (Meinshausen et al. 2020) |
| `flash.nc` | `lightning_flashes` (km-2 month-1) | LIS/OTD 0.5 degree monthly climatology HRMC v2.3.2015 (Cecil et al. 2014), flash rate per day times the days of the month; needs an Earthdata Login |
| `popdens.nc` | `population_density` (km-2) | WorldPop 2020 persons per 1 km pixel (WorldPop 2018), summed in each cell and divided by the cell area |
| `gdp.nc` | `gdp` (thousand US$ per person) | optional; Kummu et al. (2018), or `gdp_lf` of the CLM5 surface dataset (Lawrence et al. 2019); from a file you download |
| `crop.nc` | `cropfire_month` (1 to 12) | optional; `abm_lf` of the CLM5 surface dataset (Lawrence et al. 2019); from a file you download |
| `static.nc` | `elev` (m) | ETOPO 2022, 60 arc-second ice surface (NOAA NCEI 2022) |
| | `sand`, `silt`, `clay` (percent) | SoilGrids 2.0 at 5 km (Poggio et al. 2021), layers 0-5, 5-15 and 15-30 cm weighted by thickness, g kg-1 divided by 10 |
| | `wind` (m s-1, by month) | WorldClim 2.1 mean wind 1970-2000 (Fick and Hijmans 2017); the height is 2 m, not 10 m |
| | `ozone` (AOT40, by month) | Gridded surface ozone metrics v2.7 from CEDA (Evans and Sofen 2016; Sofen et al. 2016), needs a token |
| | `ndep` (mg N m-2 yr-1) | ISIMIP3b NHx plus NOy deposition, mean of 2005 to 2014 (Yang et al. 2026), g N m-2 month-1 times 1000 |
| `lulc.nc` | cohorts of each cell | LUH2 v2h (Hurtt et al. 2020); potential vegetation of Ramankutty and Foley (1999) |

Sources, which the script downloads itself except LUH2 (`tools/run_test.py` fetches that with wget):

```bash
wget https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_annmean_mlo.txt
S=https://files.isric.org/soilgrids/latest/data_aggregated/5000m
wget $S/sand/sand_0-5cm_mean_5000.tif      # also silt, clay; 5-15 and 15-30 cm
N=https://www.ngdc.noaa.gov/thredds/fileServer/global/ETOPO2022/60s/60s_surface_elev_netcdf
wget $N/ETOPO_2022_v1_60s_N90W180_surface.nc
wget https://geodata.ucdavis.edu/climate/worldclim/2_1/base/wc2.1_10m_wind.zip
wget https://sage-public-files.s3.amazonaws.com/global-potential-vegetation/potveg_nc.tar.gz
wget https://data.worldpop.org/GIS/Population/Global_2000_2020/2020/0_Mosaicked/ppp_2020_1km_Aggregated.tif
I=https://files.isimip.org/ISIMIP3b/InputData/socioeconomic/n-deposition/histsoc
wget $I/ndep-nhx_histsoc_monthly_1850_2014.nc    # also ndep-noy
wget https://luh.umd.edu/LUH2/LUH2_v2h/states.nc                    # 5.8 GB
wget https://luh.umd.edu/LUH2/LUH2_v2h/staticData_quarterdeg.nc
```

Tested on real data: the `ndep`, CO2, soil, elevation and wind steps, the `lightning` step on the downloaded LIS/OTD file (variable `HRMC_COM_FR`, flashes km-2 day-1, dimensions found by size, annual totals of 30, 10 and 56 flashes km-2 yr-1 in Florida, Pennsylvania and the Congo)
and the `population` step on the full 830 MB WorldPop raster at 1 degree for the globe (header EPSG:4326, 0.0083 degree, float32, nodata -3.4e38).
The `lulc` step was tested on synthetic LUH2 files with the documented layout (descending latitude, `secma`), not on the downloaded `states.nc`; its headers were not inspected.
Scenario CO2 after the observed years is not downloaded; pass a file with one `year ppmv` pair per line to `co2 --scenario`
(see https://esgf-node.llnl.gov/projects/input4mips/).

## Ozone

The ozone file needs a CEDA account (https://help.ceda.ac.uk/article/39-ceda-account) and an access token (https://services.ceda.ac.uk/account/token/; valid for 3 days).
With the token in `CEDA_TOKEN`, `ozone` downloads the monthly 1 degree file of the dataset record https://catalogue.ceda.ac.uk/uuid/c0455ab814224a05ac74642d3d44b73e/
(archive directory http://data.ceda.ac.uk/badc/proc-earth-model/data/ozone-metrics/v2.7) and uses the variable whose name contains `aot40`.
Pass `--file` and `--var` for a file you downloaded. The file name, variable and unit of AOT40 were not checked, because the download needs a login. The script averages a time axis into a
12-month climatology; check the result. The data come from monitoring stations, so cells without stations are missing and TEM skips cells with missing data.

## Nitrogen deposition

`ndep` adds the NHx and NOy files of ISIMIP3b (https://doi.org/10.48364/ISIMIP.600567.1, unit g N m-2 month-1, 1850 to 2014), sums the months of `--start` to `--end`
(default 2005 to 2014), averages the years and multiplies by 1000 to get mg N m-2 yr-1. The file carries the unit per N, so no further conversion is needed.
For other data pass `--file`, `--var` and `--scale`. Another source is the ACCMIP multi-model deposition of Lamarque et al. (2013) (https://doi.org/10.5194/acp-13-7997-2013).

## Land cover

The script writes up to seven cohorts per cell from the LUH2 fractions of one year and the cell area, in the encoding of the Hurtt cohort file of TEM_Biogeography (`cruHurtt3.2.1lulccohrts`, 2014):

| Cohort | LUH2 states | `potveg`, `currentveg`, `subtype` | `agstate` | `fertflag`, `irrgflag` | `standage` |
|---|---|---|---|---|---|
| `primary` | `primf`, `primn` | potential vegetation | 0 | 0 | 3000 |
| `secondary` | `secdf`, `secdn` | potential vegetation | 0 | 0 | `secma`, 425 if absent |
| `crops` | `c3ann`, `c4ann`, `c3per`, `c4per`, `c3nfx` | 50 | 1 | 1 | 0 |
| `pasture` | `pastr`, `range` | 51 | 2 | 0 | 0 |
| `urban` | `urban` | 48 | 3 | 1 | 0 |

For the mixed potential types 8, 14, 27 and 31 the primary and the secondary cohort are written twice, once per component, with `subtype` 9 and 10, 12 and 16, 12 and 16, and 10 and 12 and the full area in both, as in the Hurtt file.
`chrtarea` is the area in km2 and `FRI` is 2000. A cohort exists where its area exceeds `--min-area` (0.001 km2). The model counts the cohorts of each cell from the cells where `standage` has data.
`cohort` lists the cohort names; `potveg`, `currentveg` and `subtype` carry `flag_values` and `flag_meanings` that list the TEM vegetation types by name.

The type numbers differ between parameter sets, so the script is written with the numbers of the old `biogeography` set and renumbers every type by its description in the `tcomm45_lulc.yaml` that `--tcomm` names (`XTEM/params/gdstem/tcomm45_lulc.yaml`); a type that the set lacks stops the script. The managed cohorts are mapped to crops (C3 annual crops), pasture and turf lawn by name; their `agstate` values (crops 1, pasture 2, urban 3) and the use of the `nfert` input for fertilizer in place of the old fertilizer flags have not been checked against the seven managed states of GDSTEM and need the model developers. In the numbers of the old set, the 15 classes of Ramankutty and Foley map to TEM types as 1 to 16, 2 to 18, 3 to 33, 4 to 9, 5 to 10,
6 and 7 to 4, 8 to 8, 9 to 14 (31 poleward of 23.5 degrees), 10 to 13, 11 and 12 to 15, 13 to 3, 14 to 21 and 15 to 2.
The Hurtt file used TEM's own finer potential vegetation: in 3381 cells of the lower 48 states it agrees with this crosswalk in 44 percent of the cells, so results differ from the old runs where the types differ.
The savanna rule, the crosswalk and the age of secondary stands are assumptions of the script; the model developers should confirm them before a production run.
Tillage, disturbance and land-cover change in time are not written, so a run uses `tlulcflag: 0`.

`lulc.nc` has `cohort` as dimension and as int64 coordinate; `lat` and `lon` are float32, categorical fields int64 with `_FillValue -9999`, other fields float32.
The layouts of all files are in `docs/io_structure.md` of XTEM.

## References

- Abatzoglou, J. T. (2013) Int. J. Climatol. 33, 121-131. https://doi.org/10.1002/joc.3413
- Abatzoglou, J. T. and Brown, T. J. (2012) Int. J. Climatol. 32, 772-780. https://doi.org/10.1002/joc.2312
- Cecil, D. J., Buechler, D. E. and Blakeslee, R. J. (2014) Atmos. Res. 135-136, 404-414. https://doi.org/10.1016/j.atmosres.2012.06.028
- Evans, M. J. and Sofen, E. D. (2016) Gridded Global Surface Ozone Metrics data (1971-2015), version 2.7. CEDA. https://doi.org/10.5285/897a3958-5bfc-4311-9bb0-01134bf6aefa
- Eyring, V. et al. (2016) Geosci. Model Dev. 9, 1937-1958. https://doi.org/10.5194/gmd-9-1937-2016
- Fick, S. E. and Hijmans, R. J. (2017) Int. J. Climatol. 37, 4302-4315. https://doi.org/10.1002/joc.5086
- Hersbach, H. et al. (2020) Q. J. R. Meteorol. Soc. 146, 1999-2049. https://doi.org/10.1002/qj.3803
- Hurtt, G. C. et al. (2020) Geosci. Model Dev. 13, 5425-5464. https://doi.org/10.5194/gmd-13-5425-2020
- Lamarque, J.-F. et al. (2013) Atmos. Chem. Phys. 13, 7997-8018. https://doi.org/10.5194/acp-13-7997-2013
- Kummu, M., Taka, M. and Guillaume, J. H. A. (2018) Sci. Data 5, 180004. https://doi.org/10.1038/sdata.2018.4
- Lawrence, D. M. et al. (2019) J. Adv. Model. Earth Syst. 11, 4245-4287. https://doi.org/10.1029/2018MS001583
- Meinshausen, M. et al. (2020) Geosci. Model Dev. 13, 3571-3605. https://doi.org/10.5194/gmd-13-3571-2020
- NOAA NCEI (2022) ETOPO 2022 15 Arc-Second Global Relief Model. https://doi.org/10.25921/fd45-gt74
- Poggio, L. et al. (2021) SOIL 7, 217-240. https://doi.org/10.5194/soil-7-217-2021
- Ramankutty, N. and Foley, J. A. (1999) Global Biogeochem. Cycles 13, 997-1027. https://doi.org/10.1029/1999GB900046
- Sofen, E. D. et al. (2016) Earth Syst. Sci. Data 8, 41-59. https://doi.org/10.5194/essd-8-41-2016
- WorldPop (www.worldpop.org) and CIESIN, Columbia University (2018) Global High Resolution Population Denominators Project. University of Southampton. https://doi.org/10.5258/SOTON/WP00647
- Yang, J., Tian, H. and Büchner, M. (2026) ISIMIP3b Simulated Historical Nitrogen Deposition Input Data, v1.1. ISIMIP Repository. https://doi.org/10.48364/ISIMIP.600567.1
