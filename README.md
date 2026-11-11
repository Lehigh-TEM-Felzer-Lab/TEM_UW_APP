# TEM_UW_APP

Prepares and runs a case of [TEM_2026](https://github.com/Lehigh-TEM-Felzer-Lab/TEM_2026). The app regrids gridded NetCDF data to the model grid,
writes the NetCDF inputs and `tem_config.yaml` of the model, and runs or submits `xtem`. It also builds NetCDF inputs from public climate and land datasets.

# What files are what

| Path | Content |
|---|---|
| `case_submit.sh` | entry point, run from the case directory |
| `config/run_config.yaml` | all keys with defaults and comments |
| `src/driver.py`, `tem_climate.py`, `tem_config.py` | case builder: regridding, units, `tem_config.yaml` |
| `src/gen_climate_inputs.py` | downloads ERA5, gridMET, MACA or CMIP6 forcing for a box and years and writes the climate file |
| `src/gen_static_inputs.py` | downloads the global datasets and builds `co2.nc`, `static.nc`, `lulc.nc`, `flash.nc` and `popdens.nc` for a box |
| `launchers/` | local and SLURM launchers |
| `examples/west/` | western United States example |
| `docs/` | `global_data.md` (sources of the input data) |

# Setup

```bash
conda env create -f env.yaml && conda activate tem_uw_app
git clone https://github.com/Lehigh-TEM-Felzer-Lab/TEM_2026
make -C TEM_2026 -j4                  # serial: build/xtem
make -C TEM_2026 mpi -j4              # MPI, for n_cpus > 1: build_mpi/xtem
export TEM_UW_APP_ROOT=$PWD
```

TEM_2026 needs g++ 9 or later, make, libyaml and libnetcdf (C). The serial build needs only `netcdf`; the MPI build needs the MPI-enabled `netcdf-mpi` with `hpcx-mpi` or `openmpi` (module names vary by site).

# Running a case

The call hierarchy of the model is in the [flowchart of TEM_2026](https://github.com/Lehigh-TEM-Felzer-Lab/TEM_2026/blob/main/flowchart.md).

1. Copy `examples/west/run_config.yaml` to an empty directory.
2. Set `tem_src` (the TEM_2026 checkout), the climate files, the box and the years. For `n_cpus` above 1 build `make mpi`; set `competition: 1` for cohorts that take each step together.
3. Run `$TEM_UW_APP_ROOT/case_submit.sh` from that directory. With `run_mode: slurm` it submits with sbatch; with `run_model: false` it only builds the case.

```
run_config.yaml   tem_config.yaml
INPUT/            climate.nc static.nc lulc.nc co2.nc (flash.nc popdens.nc)
OUTPUT/           tem.nc, written by the model
logs/
```

# Configuration

`config/run_config.yaml` lists every key; keys you do not set take its values and unknown keys are an error.

| Key | Description |
|---|---|
| `tem_src`, `tem_exe` | TEM_2026 checkout and executable (default chosen from `n_cpus` and `run_dt_units`, see Compile-time options) |
| `climate_file`, `netcdf_climate_in_frequency` | climate files (path, glob or list) and their time step (hourly, daily, monthly) |
| `static_file`, `lulc_file`, `co2_file` | static, land-cover and CO2 files in the layout of TEM_2026 `docs/io_structure.md` |
| `lightning_file`, `population_file` | lightning flashes and population density, needed when `veg_fire: 1` |
| `gdp_file`, `cropfire_file` | optional: with `gdp_file` (`gdp`) the fire model adds the GDSTEM-FIRE terms (the vegetation file needs `fsr`, `fd`, `rswf_min`, `rswf_max`); `cropfire_file` (`cropfire_month`) is optional; staged as `gdp.nc` and `crop.nc` |
| `storm_file`, `nfert_file` | storm return intervals (`storm_disturbance: true`) and N fertilizer (`xnfertflag`), layout in TEM_2026 `docs/io_structure.md` |
| `varmap` | `<model variable>: <variable in your files>`; the model name is used first, the map only when the file lacks it |
| `horizontal_resolution`, `lon_min` to `lat_max`, `regrid_method` | model grid and regridding (`box_mean`, `bilinear`, `nearest`) |
| `start_year`, `run_length`, `run_length_units` | first year and duration in any unit (seconds to years, converted to seconds) from 1 January; the app stages climate with exactly that many steps |
| `spinflag`, `veg_fire`, `xnfertflag`, ... | the options of `tem_config.yaml`, one key each |
| `cmntecd`, `vegecd`, ... | parameter files, by default `{tem_src}/params/biogeography/` |
| `output_file` | native NetCDF output path, default `./OUTPUT/tem.nc` |
| `clmoutvars`, `temoutvars` | YAML sequences of output variable names |
| `run_mode`, `n_nodes`, `n_cpus`, `walltime`, `partition`, `mem`, `sbatch_options` | sbatch settings as in pyUFS; the cells are shared between the `n_cpus` MPI tasks |

Climate units are read from the `units` attribute and converted. `tmin` and `tmax` can replace `tair` and `dtr`, and `dewpoint` or `huss` can replace `vpr`.
Daily and hourly data are averaged to months.

Use top-level `*_dat` keys for site calibration files in `run_config.yaml`.
The key is a label. TEM uses the community ID declared inside the file.
Case-level calibration keys replace the default set.

```yaml
hvc_dat: "{tem_src}/params/biogeography/hvc50_openn_dndc.yaml"
hvd_dat: "{tem_src}/params/biogeography/hvd50_openn_dndc.yaml"
```

# Compile-time options

These are options of the TEM_2026 build, not of this app. Pass them to `make` in the TEM_2026 checkout, for example `make mpi -j16 OPEN_N=0 STORM=0`. Changing an option rebuilds the objects of that build directory.

| Option | Default | Effect |
|---|---|---|
| `OPEN_N` | 1 | 1 open nitrogen cycle, 0 closed |
| `STORM` | 1 | 1 includes stochastic tropical storm and hurricane damage, enabled by `storm_disturbance: true` and `storm_file`; 0 omits it and rejects `storm_disturbance: true`. Prescribed land-cover disturbances are always available |
| `CXXFLAGS` | `-O2` | an unoptimised build gives different numbers |
| `CXX` | `g++` | compiler; `make mpi` uses `mpicxx` |

Every build makes one executable, `xtem`, which runs monthly and daily steps (`run_dt`, `run_dt_units`, converted to seconds) and cohorts in turn or together (`competition`). Without `tem_exe` the app picks `build/xtem`, or `build_mpi/xtem` when `n_cpus` is above 1.

# Input data

The app builds `climate.nc` from your climate files, which `src/gen_climate_inputs.py` can download; `src/gen_static_inputs.py` makes the other inputs:

```bash
A="--out INPUT --cache downloads --bbox -125 -110 32 49 --res 0.5"
python src/gen_climate_inputs.py --out INPUT --bbox -125 -110 32 49 --start 2000 --end 2019 gridmet
python src/gen_static_inputs.py $A co2 --start 2000 --end 2019
python src/gen_static_inputs.py $A all --year 2015 --cohorts primary secondary crops pasture urban
```

`gen_climate_inputs.py` writes `climate_<source>.nc` and `varmap_<source>.yaml` (copy it into `run_config.yaml`; set `netcdf_climate_in_frequency: daily`). `all` builds `static.nc`, `lulc.nc`, `flash.nc` and `popdens.nc` (and the files they are made from); `--cohorts` and `--min-area` select the cohorts of `lulc.nc`.
Ozone needs a CEDA token (`CEDA_TOKEN`) and lightning an Earthdata Login token (`EARTHDATA_TOKEN`); all other files are downloaded by the script. Sources, download links,
units and the land-cover assumptions are in [docs/global_data.md](docs/global_data.md). Set the `netcdf_*_in_file` keys of
`run_config.yaml` to your datasets. NetCDF inputs may use any filename extension.

# Test

`python tools/run_test.py` is one file that clones TEM_2026 and TEM_UW_APP, builds the model, downloads ERA5 (needs `~/.cdsapirc` and `cdsapi`) and the other input data, makes a global 1 degree case for one year and runs it monthly and daily. Flags such as `--competition`, `--fire`, `--all` add cases; `python tools/run_test.py -h` lists them and the docstring describes the work directory, the archive and the placeholders for ozone and N deposition.

# Documentation

| File | Content |
| --- | --- |
| [TEM_UW_APP-Technical-Description.pdf](TEM_UW_APP-Technical-Description.pdf) | build options, workflow and input sources |
| [run_config.pdf](run_config.pdf) | `run_config.yaml` key reference |

The [run configuration](config/run_config.yaml) lists keys, defaults, and meanings.

# Limits

- The app writes monthly or daily forcing (`run_dt` is one month or one day, written in any unit; daily needs daily forcing, `netcdf_climate_in_frequency` set to `daily`). Daily results were not compared with observations.
- Tested on the western United States example only; the inputs the app writes for it are identical to those shipped with TEM_2026.
- The global land-cover builder is not validated against the lab's earlier inputs.
