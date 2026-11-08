# Global input data

The files of TEM_2026 `examples/test/INPUT` for any region: where each comes from, the download command and the step that writes the TEM_2026 layout.
`src/make_global_inputs.py` (run from the root of TEM_UW_APP) does the download and the regridding for a box and a resolution; the commands below were run for
a 0.5 degree box over the western United States (co2, fire, soil, elev, wind, lulc with a synthetic LUH2 file). Requirements:
`pip install xarray netcdf4 pandas scipy rioxarray` and `wget`.

```bash
A="--out INPUT --cache downloads --lon-min -125 --lon-max -110 --lat-min 32 --lat-max 49 --res 0.5"
python src/make_global_inputs.py $A co2 --start 2015 --end 2024
python src/make_global_inputs.py $A fire --fire-file tem_biogeography/static/fire.nc
python src/make_global_inputs.py $A soil
python src/make_global_inputs.py $A elev
python src/make_global_inputs.py $A wind
python src/make_global_inputs.py $A lulc --luh2 states.nc --luh2-static staticData_quarterdeg.nc --year 2015
python src/make_global_inputs.py $A ozone --file <ozone.nc> --var <name>
python src/make_global_inputs.py $A ndep --file <ndep.nc> --var <name> --scale <factor>
python src/make_global_inputs.py $A static          # merges elev, soil, wind, ozone and ndep into static.nc
```

`climate.nc` is built by TEM_UW_APP from ERA5, MACA, gridMET or CMIP output (see `data.md`). The regridding is the mean of the source
cells that fall in a target cell, so the target resolution should be coarser than the source.

## Sources

| File and variable | Unit | Source | Download | Status |
|---|---|---|---|---|
| `co2.nc` `co2` | ppmv | NOAA GML Mauna Loa annual mean (observed years); for later years a scenario file with `year ppmv` per line, for example the SSP series of Meinshausen et al. (2020) | `wget https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_annmean_mlo.txt`; scenarios on https://esgf-node.llnl.gov/projects/input4mips/ | NOAA file tested. The scenario series is not downloaded by the script |
| `flash.nc` `lightning_flashes` | km-2 month-1 | LIS/OTD high-resolution monthly climatology (Cecil et al. 2014), as prepared in `tem_biogeography/static/fire.nc` (0.5 degree, global) | `git clone https://github.com/Lehigh-TEM-Felzer-Lab/tem_biogeography`; original data https://ghrc.nsstc.nasa.gov/pub/lis/climatology/LIS-OTD/HRMC/data/nc/ | tested on `fire.nc` |
| `popdens.nc` `population_density` | km-2 | GPW v4 (CIESIN), in the same `fire.nc` | https://sedac.ciesin.columbia.edu/data/set/gpw-v4-population-density-rev11 (login) | tested on `fire.nc` |
| `static.nc` `elev` | m | ETOPO 2022 60 arc-second ice surface (NOAA NCEI) | `wget https://www.ngdc.noaa.gov/thredds/fileServer/global/ETOPO2022/60s/60s_surface_elev_netcdf/ETOPO_2022_v1_60s_N90W180_surface.nc` (478 MB) | tested |
| `sand`, `silt`, `clay` | percent | SoilGrids 2.0 at 5 km (Poggio et al. 2021), layers 0-5, 5-15 and 15-30 cm weighted by thickness; g kg-1 divided by 10 | `wget https://files.isric.org/soilgrids/latest/data_aggregated/5000m/sand/sand_0-5cm_mean_5000.tif` and the same for `silt`, `clay` and the other two layers (9 MB each) | tested; the sum is 100 percent |
| `wind` (month) | m s-1 | WorldClim 2.1 monthly mean wind 1970-2000 (Fick and Hijmans 2017), 10 arc-minutes | `wget https://geodata.ucdavis.edu/climate/worldclim/2_1/base/wc2.1_10m_wind.zip` | tested. The height is 2 m, not 10 m |
| `ozone` (month) | AOT40, ppb h | Gridded Global Surface Ozone Metrics v2.7, 1971-2015 (Evans and Sofen 2016; Sofen et al. 2016), monthly files at several resolutions, from station data; or a model field | See "Ozone and nitrogen deposition" below | Not downloaded by the script (free CEDA login); pass the file |
| `ndep` | mg N m-2 yr-1 | ISIMIP3b simulated historical nitrogen deposition (NHx + NOy), 0.5 degree (Yang et al. 2026) | See "Ozone and nitrogen deposition" below | Not downloaded by the script; ISIMIP is in kg m-2 s-1, so `--scale 3.1536e13` gives mg N m-2 yr-1 |
| `lulc.nc` | see below | LUH2 v2h (Hurtt et al. 2020) states for the year; Ramankutty and Foley (1999) potential vegetation | `wget http://luh.umd.edu/LUH2/LUH2_v2h/states.nc` (5.8 GB), `staticData_quarterdeg.nc` next to it; `wget https://sage-public-files.s3.amazonaws.com/global-potential-vegetation/potveg_nc.tar.gz` (done by the script) | `states.nc` link answers with a redirect but was not downloaded; confirm the links on https://luh.umd.edu/data.shtml. The code was tested with a synthetic LUH2 file |

## Ozone and nitrogen deposition

These two are not downloaded by the script, because the sources need a login or block scripted requests. Get the file once, then pass it with `--file`, `--var` and `--scale`.

**Ozone (AOT40).**

1. Register for a free account at https://accounts.ceda.ac.uk/registration/ and sign in.
2. Open the dataset record https://catalogue.ceda.ac.uk/uuid/c0455ab814224a05ac74642d3d44b73e/ (DOI 10.5285/897a3958-5bfc-4311-9bb0-01134bf6aefa) and its archive directory http://data.ceda.ac.uk/badc/proc-earth-model/data/ozone-metrics/v2.7 .
3. Download a monthly file whose resolution is closest to your grid, for example `CCMI_SurfaceOzoneObs_1x1_Monthly_v2.7.nc`. Direct link (works once signed in, or with a CEDA access token in the request header, see http://help.ceda.ac.uk/article/4431-ceda-archive-web-download-and-services):
   `wget --header "Authorization: Bearer $CEDA_TOKEN" -O ozone_1x1_monthly.nc "https://dap.ceda.ac.uk/badc/proc-earth-model/data/ozone-metrics/v2.7/CCMI_SurfaceOzoneObs_1x1_Monthly_v2.7.nc?download=1"`
4. Find the AOT40 variable with `ncdump -h ozone_1x1_monthly.nc | grep -i aot40` and pass its name: `python src/make_global_inputs.py $A ozone --file ozone_1x1_monthly.nc --var <name>`.

The variable names, the unit of AOT40 in that file and the time axis (monthly series 1971-2015 versus a climatology) were not checked, because the file needs a login. The script averages a time axis into a 12-month climatology (nitrogen deposition: into a single mean); check the result. The data derive from monitoring stations, so cells without stations are missing, and TEM skips cells with missing data. Fill them from a model field or a neighbouring value before running if the region has few stations.

**Nitrogen deposition.**

1. Open https://doi.org/10.48364/ISIMIP.600567.1 (ISIMIP3b simulated historical nitrogen deposition input data, v1.1). Its file list gives the total, wet and dry NHx and NOy files with their download links. Blocking of scripted requests applies to the website, so download in a browser or with `pip install isimip-client` (documentation: https://github.com/ISI-MIP/isimip-client), then `wget` the file URLs the client returns.
2. Total deposition is NHx plus NOy. If the files are separate, add them first (`cdo add nhx.nc noy.nc ndep.nc`).
3. Run `python src/make_global_inputs.py $A ndep --file ndep.nc --var <name> --scale 3.1536e13`. The factor converts kg m-2 s-1 to mg N m-2 yr-1 (1 kg = 1e6 mg, 365 d x 86400 s = 3.1536e7 s). Confirm whether the ISIMIP units are per kg N or per kg of the compound, and change the factor if they are not kg N.
4. Other source: Lamarque et al. (2013) ACCMIP deposition, https://doi.org/10.5194/acp-13-7997-2013 (data via https://esgf-node.llnl.gov/projects/input4mips/).

## Land cover (`lulc.nc`)

The script writes up to three cohorts per cell from the LUH2 fractions of one year and the area of the cell (`carea` times the land fraction):

| Cohort | LUH2 states | `currentveg` | `agstate` | `standage` |
|---|---|---|---|---|
| 1 natural | `primf`, `primn`, `secdf`, `secdn`, `range` | the potential vegetation of the cell | 0 | 3000 |
| 2 crops | `c3ann`, `c4ann`, `c3per`, `c4per`, `c3nfx` | 50 (Crops) | 1 | 1 |
| 3 pasture | `pastr` | 51 (Pasture) | 1 | 1 |

`chrtarea` is the area in km2, `potveg` is the TEM type of the potential vegetation, `subtype` equals `currentveg` and `FRI` is 2000. A cohort exists
where its area exceeds 0.001 km2; The model counts the cohorts of each cell and year from the cells where `standage` has data. `cohort` (1 natural vegetation, 2 crops, 3 pasture), `potveg`, `currentveg` and `agstate` carry `flag_values` and `flag_meanings` listing the TEM vegetation types by name. Urban land is not simulated.

The 15 classes of Ramankutty and Foley map to TEM types (`params/biogeography/tcomm50_lulc.yaml`) as 1 to 16, 2 to 18, 3 to 33, 4 to 9, 5 to 10,
6 and 7 to 4, 8 to 8, 9 to 14, 10 to 13, 11 and 12 to 15, 13 to 3, 14 to 21 and 15 to 2. This crosswalk, the `subtype` rule, `standage` of the
managed cohorts and `agstate` of pasture are assumptions of the script, not values taken from the western example; check them with the model developers
before a production run. Management layers (`tillflag`, `fertflag`, `irrgflag`) and land-cover change in time are not written: a run with
`tlulcflag: 0` uses the single year.

## Layout of the output

`lulc.nc` has `cohort` as dimension and as an int64 coordinate variable (1 to the number of cohorts); `lat` and `lon` are float32; categorical fields are
int64 with `_FillValue -9999`; the other fields are float32. `static.nc` and the others follow `io_structure.md`.

## References

- Cecil, D. J., Buechler, D. E. and Blakeslee, R. J. (2014) Atmos. Res. 135-136, 404-414.
- Fick, S. E. and Hijmans, R. J. (2017) Int. J. Climatol. 37, 4302-4315.
- Hurtt, G. C. et al. (2020) Geosci. Model Dev. 13, 5425-5464.
- Lamarque, J.-F. et al. (2013) Atmos. Chem. Phys. 13, 7997-8018.
- Meinshausen, M. et al. (2020) Geosci. Model Dev. 13, 3571-3605.
- Poggio, L. et al. (2021) SOIL 7, 217-240.
- Ramankutty, N. and Foley, J. A. (1999) Global Biogeochem. Cycles 13, 997-1027.
- Sofen, E. D. et al. (2016) Earth Syst. Sci. Data 8, 41-59.
- NOAA NCEI (2022) ETOPO 2022 15 Arc-Second Global Relief Model, https://doi.org/10.25921/fd45-gt74
