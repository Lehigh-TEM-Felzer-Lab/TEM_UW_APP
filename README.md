# TEM_UW_APP

Builds a TEM_2026 case from gridded NetCDF data and runs it. It regrids the inputs to the model grid
(xarray), writes the NetCDF inputs and `tem_config.yaml` that [TEM_2026](https://github.com/Lehigh-TEM-Felzer-Lab/TEM_2026)
reads, and runs or submits `xtem`. Output is the NetCDF file written by the model. The older CSV/XML
workflow is not supported; the last version of it is the commit before this one.

## Run

```bash
conda env create -f env.yaml && conda activate tup
export TUP_ROOT=$PWD
mkdir -p ~/cases/west && cd ~/cases/west
cp $TUP_ROOT/examples/west/run_config.yaml .     # set tem_src, the climate file and the grid
$TUP_ROOT/case_submit.sh
```

TEM_2026 must be built first (`cmake -S . -B build && cmake --build build -j`, add `-DUSE_MPI=ON` for `n_cpus > 1`).
`run_mode: slurm` submits with sbatch; `run_model: false` only builds the case.

## Input files

TEM_2026 needs these NetCDF files (layouts: TEM_2026 `docs/io_structure.md`). `climate.nc` is made by the app from your climate data
(ERA5, MACA, gridMET or CMIP output, see `run_config.yaml`); the others are made by `src/make_global_inputs.py` for any box and
resolution. Sources, download links, units and caveats of each are in [docs/global_data.md](docs/global_data.md).

```bash
A="--out INPUT --cache downloads --lon-min -125 --lon-max -110 --lat-min 32 --lat-max 49 --res 0.5"
python src/make_global_inputs.py $A co2 --start 2015 --end 2024       # co2.nc (NOAA)
python src/make_global_inputs.py $A fire --fire-file <fire.nc>        # flash.nc, popdens.nc (fire.nc is in tem_biogeography/static)
python src/make_global_inputs.py $A soil                              # SoilGrids sand, silt, clay
python src/make_global_inputs.py $A elev                              # ETOPO 2022
python src/make_global_inputs.py $A wind                              # WorldClim wind
python src/make_global_inputs.py $A ozone --file <ozone.nc> --var <name>                  # CEDA login, see docs
python src/make_global_inputs.py $A ndep --file <ndep.nc> --var <name> --scale 3.1536e13  # ISIMIP, see docs
python src/make_global_inputs.py $A static                            # elev, soil, wind, ozone, ndep -> static.nc
python src/make_global_inputs.py $A lulc --luh2 states.nc --luh2-static staticData_quarterdeg.nc --year 2015   # lulc.nc
```

`lulc.nc` holds the cohorts of each cell (1 natural vegetation, 2 crops, 3 pasture) from LUH2 land-use states and the
Ramankutty and Foley potential vegetation. The model counts the cohorts of each cell from it, so no cohort-count file is needed.
Then point `netcdf_static_in_file`, `netcdf_lulc_in_file`, `netcdf_co2_in_file`, `netcdf_fire_in_file` and `netcdf_population_in_file`
of `run_config.yaml` at the files. The land-cover crosswalk is an assumption that the model developers should confirm.

## Converting old files

For runs set up with the older TEM versions (TEM_Monthly, TEM_Biogeography, GDSTEM and others):

```bash
python src/xml2yaml.py us_tem45_lulc.xml -o tem_config.yaml     # old XML control file -> YAML (keys and comments kept)
python src/xml2yaml.py tcomm45_lulc.ecd  -o tcomm50_lulc.yaml   # old parameter file (.ecd, .dat) -> YAML
python src/ascii2nc.py clm tair.csv prec.csv dtr.csv nirr.csv vpr.csv -o climate.nc   # monthly ASCII -> NetCDF
python src/ascii2nc.py clm wind.csv aot40.csv -o static.nc --grid climate.nc          # year -999 files: climatology (month)
python src/ascii2nc.py elev elev.csv -o static.nc --grid climate.nc                   # repeated calls add to the file
python src/ascii2nc.py soil soil.csv -o static.nc --grid climate.nc
python src/ascii2nc.py ndep ndep.csv -o static.nc --grid climate.nc
python src/ascii2nc.py co2 co2.csv -o co2.nc
python src/ascii2nc.py lulc lulc.csv -o lulc.nc --grid climate.nc
```

`xml2yaml.py` keeps every tag as a key and the XML comments as YAML comments, repairs the known typos of the old files (a mismatched
closing tag, an unclosed quote) and lists the ASCII input names it finds, since TEM_2026 reads NetCDF through the `netcdf_*_in_file`
keys instead; the other keys keep the names of the old control file, which `tem_config.yaml` of TEM_2026 also uses; compare the result with the template. `ascii2nc.py` reads the comma-separated records of the old preprocessors (layouts at the top of the file); variables are named as TEM_2026 expects (`CLDINESS` to `clouds`, `DTAIRRNG` to `dtr`, `VPRPRESS` to
`vpr`, `AOT40` to `ozone`) and the model counts the cohorts from `lulc.nc`, so the old cohort-count file (`MXCOHRTS`) is not needed. The old files list only
cells with data, so use `--grid` with a NetCDF file of the full grid (the climate file) to restore the empty cells. The `daily` and `ndep` kinds were not tested. Checked by writing
the example inputs of TEM_2026 as ASCII, converting them back (values equal to the original within the ASCII rounding) and running
the model on the result (maximum GPP 423.98 against 424.01). Not converted: the old ASCII fire inputs and the old output files
(`tem_utils` converts old HIST output).

## Configuration

`config/run_config.yaml` lists every key with comments; keys you do not set take its values and unknown keys
are an error. The main ones:

| Key | Meaning |
|---|---|
| `tem_src`, `tem_exe` | TEM_2026 checkout (template `tem_config.yaml`, `params/`) and the executable (default `{tem_src}/build/xtem`) |
| `netcdf_climate_in_file`, `netcdf_climate_in_frequency` | climate files (path, glob or list) and their time step (hourly, daily or monthly) |
| `netcdf_static_in_file`, `netcdf_lulc_in_file`, `netcdf_co2_in_file` | NetCDF files in the layout of TEM_2026 `docs/data.md` |
| `netcdf_fire_in_file`, `netcdf_population_in_file` | lightning flashes and population density, needed when `veg_fire: 1` |
| `varmap` | flat map `<model variable>: <variable in your files>`; the model name is used first, the map only when the file lacks it |
| `horizontal_resolution`, `lon_min`..`lat_max`, `regrid_method` | model grid and how inputs are regridded (`box_mean`, `bilinear`, `nearest`) |
| `spinflag`, `veg_fire`, `fire_mode`, `xnfertflag`, ... | the `tem_config.yaml` options, each as its own key (section 5 of `run_config.yaml`) |
| `cmntecd`, `vegecd`, ... | parameter files, by default `{tem_src}/params/biogeography/` |
| `clmoutvars`, `temoutvars` | variables written to `OUTPUT/tem.nc` |
| `run_mode`, `n_nodes`, `n_cpus`, `walltime`, `partition`, `mem`, `sbatch_options`, ... | sbatch settings as in pyUFS; the cells are shared between the `n_cpus` MPI tasks and the output is merged into one file |

Climate units are read from the `units` attribute and converted (K, degC, rates or amounts, J m-2, Pa, ...). `tmin`/`tmax` can
replace `tair`/`dtr`, and `dewpoint` or `huss` can replace `vpr`. Daily and hourly data are averaged to months.

## Case directory

```
run_config.yaml   tem_config.yaml
INPUT/    climate.nc static.nc lulc.nc co2.nc (lightning.nc population.nc)
OUTPUT/   tem.nc written by the model
logs/
```

Layouts of the files and of the output: TEM_2026 `docs/data.md` and `docs/running.md`.

## Limits

- The app writes monthly forcing, so it runs `run_dt: 1`, `run_dt_units: month` and rejects other steps. TEM_2026 itself takes other steps if built with `TEM_MAXCYCLE` large enough (`make daily`), but daily forcing is not generated here.
- Build TEM_2026 with `make` (gives `build/xtem`, the default `tem_exe`) or `make mpi` (gives `build_mpi/xtem`; set `tem_exe`).
- Tested on the Western US example only: the inputs the app writes for it are identical to the ones shipped with TEM_2026.
