# Global input data

`src/make_global_inputs.py` writes the input files of TEM_2026 for any box and resolution (run it from the root of TEM_UW_APP).
The commands below are for a 0.5 degree box over the western United States.
Needs `pip install xarray netcdf4 pandas scipy rioxarray` and `wget`.

```bash
A="--out INPUT --cache downloads --lon-min -125 --lon-max -110 --lat-min 32 --lat-max 49 --res 0.5"
python src/make_global_inputs.py $A co2 --start 2015 --end 2024
python src/make_global_inputs.py $A soil
python src/make_global_inputs.py $A elev
python src/make_global_inputs.py $A wind
python src/make_global_inputs.py $A lightning
python src/make_global_inputs.py $A population
python src/make_global_inputs.py $A ndep --start 2005 --end 2014
CEDA_TOKEN=<token> python src/make_global_inputs.py $A ozone
python src/make_global_inputs.py $A static
python src/make_global_inputs.py $A lulc --luh2 states.nc --luh2-static staticData_quarterdeg.nc --year 2015
```

Every step downloads its source into `--cache` once. `tools/run_test.py` runs all of them for the globe at 1 degree.
`static` merges the elevation, soil, wind, ozone and N deposition files into `static.nc`. `climate.nc` is made by the app from ERA5, MACA, gridMET or CMIP output.
The regridding is the mean of the source cells in a target cell, so the target should be coarser than the source.

## Sources

| File | Variable (unit) | Source |
|---|---|---|
| `co2.nc` | `co2` (ppmv) | NOAA GML Mauna Loa annual mean; SSP scenarios for later years (Meinshausen et al. 2020) |
| `flash.nc` | `lightning_flashes` (km-2 month-1) | LIS/OTD 0.5 degree monthly climatology HRMC v2.3.2015 (Cecil et al. 2014), flash rate per day times the days of the month |
| `popdens.nc` | `population_density` (km-2) | WorldPop 2020 persons per 1 km pixel (WorldPop 2018), summed in each cell and divided by the cell area |
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
wget https://ghrc.nsstc.nasa.gov/pub/lis/climatology/LIS-OTD/HRMC/data/nc/LISOTD_HRMC_V2.3.2015.nc
wget https://data.worldpop.org/GIS/Population/Global_2000_2020/2020/0_Mosaicked/ppp_2020_1km_Aggregated.tif
I=https://files.isimip.org/ISIMIP3b/InputData/socioeconomic/n-deposition/histsoc
wget $I/ndep-nhx_histsoc_monthly_1850_2014.nc    # also ndep-noy
wget https://luh.umd.edu/LUH2/LUH2_v2h/states.nc                    # 5.8 GB
wget https://luh.umd.edu/LUH2/LUH2_v2h/staticData_quarterdeg.nc
```

The `ndep` step (downloaded file, units and the 1 degree result), the `lightning` step on a synthetic file and the `population` step on a synthetic raster were tested, as were the CO2, soil, elevation and wind steps. The LIS/OTD file could not be reached from the test machine, so its variable name (`HRMC_COM_FR`), its dimensions and its unit (flashes km-2 day-1) are assumed from the dataset description; if the step fails, download the file and pass it with `--file` (and `--var`). The WorldPop step was not run on the full 830 MB raster. The LUH2 step was tested on a synthetic file, not on the downloaded `states.nc`.
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

The script writes up to three cohorts per cell from the LUH2 fractions of one year and the cell area:

| Cohort | LUH2 states | `currentveg` | `agstate` | `standage` |
|---|---|---|---|---|
| 1 natural | `primf`, `primn`, `secdf`, `secdn`, `range` | potential vegetation of the cell | 0 | 3000 |
| 2 crops | `c3ann`, `c4ann`, `c3per`, `c4per`, `c3nfx` | 50 (Crops) | 1 | 1 |
| 3 pasture | `pastr` | 51 (Pasture) | 1 | 1 |

`chrtarea` is the area in km2, `potveg` the TEM type of the potential vegetation, `subtype` equals `currentveg` and `FRI` is 2000.
A cohort exists where its area exceeds 0.001 km2. The model counts the cohorts of each cell from the cells where `standage` has data.
`cohort`, `potveg`, `currentveg` and `agstate` carry `flag_values` and `flag_meanings` that list the TEM vegetation types by name. Urban land is not simulated.

The 15 classes of Ramankutty and Foley map to TEM types (`params/biogeography/tcomm50_lulc.yaml` of TEM_2026) as 1 to 16, 2 to 18, 3 to 33, 4 to 9, 5 to 10,
6 and 7 to 4, 8 to 8, 9 to 14, 10 to 13, 11 and 12 to 15, 13 to 3, 14 to 21 and 15 to 2. This crosswalk, the `subtype` rule, `standage` of the managed cohorts and
`agstate` of pasture are assumptions of the script; the model developers should confirm them before a production run.
Management layers (`tillflag`, `fertflag`, `irrgflag`) and land-cover change in time are not written, so a run uses `tlulcflag: 0`.

`lulc.nc` has `cohort` as dimension and as int64 coordinate; `lat` and `lon` are float32, categorical fields int64 with `_FillValue -9999`, other fields float32.
The layouts of all files are in `docs/io_structure.md` of TEM_2026.

## References

- Cecil, D. J., Buechler, D. E. and Blakeslee, R. J. (2014) Atmos. Res. 135-136, 404-414. https://doi.org/10.1016/j.atmosres.2012.06.028
- Evans, M. J. and Sofen, E. D. (2016) Gridded Global Surface Ozone Metrics data (1971-2015), version 2.7. CEDA. https://doi.org/10.5285/897a3958-5bfc-4311-9bb0-01134bf6aefa
- Fick, S. E. and Hijmans, R. J. (2017) Int. J. Climatol. 37, 4302-4315. https://doi.org/10.1002/joc.5086
- Hurtt, G. C. et al. (2020) Geosci. Model Dev. 13, 5425-5464. https://doi.org/10.5194/gmd-13-5425-2020
- Lamarque, J.-F. et al. (2013) Atmos. Chem. Phys. 13, 7997-8018. https://doi.org/10.5194/acp-13-7997-2013
- Meinshausen, M. et al. (2020) Geosci. Model Dev. 13, 3571-3605. https://doi.org/10.5194/gmd-13-3571-2020
- NOAA NCEI (2022) ETOPO 2022 15 Arc-Second Global Relief Model. https://doi.org/10.25921/fd45-gt74
- Poggio, L. et al. (2021) SOIL 7, 217-240. https://doi.org/10.5194/soil-7-217-2021
- Ramankutty, N. and Foley, J. A. (1999) Global Biogeochem. Cycles 13, 997-1027. https://doi.org/10.1029/1999GB900046
- Sofen, E. D. et al. (2016) Earth Syst. Sci. Data 8, 41-59. https://doi.org/10.5194/essd-8-41-2016
- WorldPop (www.worldpop.org) and CIESIN, Columbia University (2018) Global High Resolution Population Denominators Project. University of Southampton. https://doi.org/10.5258/SOTON/WP00647
- Yang, J., Tian, H. and Büchner, M. (2026) ISIMIP3b Simulated Historical Nitrogen Deposition Input Data, v1.1. ISIMIP Repository. https://doi.org/10.48364/ISIMIP.600567.1
