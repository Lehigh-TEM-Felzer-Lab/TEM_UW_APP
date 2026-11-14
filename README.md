# TEM_UW_APP

Prepares and runs cases of [XTEM](https://github.com/Lehigh-TEM-Felzer-Lab/XTEM). From a `run_config.yaml` it regrids gridded NetCDF data to the model grid, writes the NetCDF inputs and `tem_config.yaml`, and runs or submits `xtem`. It also builds model inputs from public climate and land datasets.

## Repository layout

| Path | Content |
|---|---|
| `case_submit.sh` | entry point, run from the case directory |
| `config/run_config.yaml` | all keys, defaults and comments |
| `src/driver.py`, `tem_climate.py`, `tem_config.py`, `tem_regrid.py`, `time_units.py` | case builder: regridding, units, `tem_config.yaml` |
| `src/gen_climate_inputs.py` | downloads ERA5, gridMET, MACA or CMIP6 forcing |
| `src/gen_static_inputs.py` | builds `co2.nc`, `static.nc`, `lulc.nc`, `flash.nc`, `popdens.nc` and other static inputs |
| `launchers/` | local and SLURM launchers |
| `tools/run_test.py` | global 1 degree test of the whole workflow |
| `examples/west/` | western United States example |
| `technical_desc.md` | sources of the input data and how they are built |
| `config_desc.md` | `run_config.yaml` key reference |
| `flowchart.md` | call hierarchy of the app |

## Related repositories

| Repository | Role |
|---|---|
| [XTEM](https://github.com/Lehigh-TEM-Felzer-Lab/XTEM) | the model. Sources are in `src/physics` (science), `src/io` (files, MPI, log) and `src/driver` (main program) |
| [GDSTEM](https://github.com/Lehigh-TEM-Felzer-Lab/GDSTEM) | the reference of the model science; XTEM carries its changes over (XML and text input and output) |
| [TEM_Biogeography](https://github.com/Lehigh-TEM-Felzer-Lab/TEM_Biogeography) | potential vegetation workflow; holds a copy of the XTEM sources and the case builder of this repository |

This repository has no model code. The files it names in XTEM are checked weekly by `.github/workflows/xtem-paths.yml`.

## Setup

```bash
conda env create -f env.yaml && conda activate tem_uw_app
git clone https://github.com/Lehigh-TEM-Felzer-Lab/XTEM
make -C XTEM -j4          # serial: build/xtem
make -C XTEM mpi -j4      # MPI, used when n_cpus > 1: build_mpi/xtem
export TEM_UW_APP_ROOT=$PWD
```

XTEM requires g++ 9 or later, make, libyaml and libnetcdf (C). The MPI build also requires an MPI-enabled netCDF (`netcdf-mpi`) and `hpcx-mpi` or `openmpi`; module names vary by site. Compile options (`OPEN_N`, `FIRE`, `STORM`, `CXXFLAGS`) are described in the XTEM README.

## Run a case

1. Copy `examples/west/run_config.yaml` to an empty directory.
2. Set `tem_src` (the XTEM checkout), the climate files, the box and the years.
3. Run `$TEM_UW_APP_ROOT/case_submit.sh` from that directory.

`run_mode: slurm` submits with sbatch. `run_model: false` only stages the case. The case directory then contains:

```
run_config.yaml   tem_config.yaml
INPUT/            climate.nc static.nc lulc.nc co2.nc (flash.nc popdens.nc gdp.nc)
OUTPUT/           tem.nc, written by the model
tem_<id>.out      progress of the run (written by the model)
tem_<id>.log      all other messages of the model and the launcher
```

The driver writes to the terminal only; the two `tem_<id>` files come from the model (`<id>` is the start date and time).

Without `tem_exe` the app uses `build/xtem`, or `build_mpi/xtem` when `n_cpus` is above 1.

## Configuration

`config/run_config.yaml` lists every key. Unset keys take its values, and unknown keys are an error. The main groups:

| Key | Description |
|---|---|
| `tem_src`, `tem_exe` | XTEM checkout and executable |
| `climate_file`, `netcdf_climate_in_frequency` | climate files (path, glob or list) and their time step: `hourly`, `daily` or `monthly` |
| `static_file`, `lulc_file`, `co2_file` | static, land-cover and CO2 files, in the layout of XTEM `technical_desc.md` |
| `lightning_file`, `population_file`, `gdp_file` | needed when `veg_fire: 1`; the vegetation parameter file must define `igef`, `fsr` and `fd` (use `params/gdstem_fire`) |
| `storm_file`, `nfert_file` | needed for `storm_disturbance: true` and `agfertflag: 1` |
| `varmap` | `<model variable>: <variable name in your dataset>`; the model name is tried first |
| `horizontal_resolution`, `lon_min` to `lat_max`, `regrid_method`, `land_fraction_min` | model grid and regridding (`box_mean`, `bilinear`, `nearest`) |
| `start_year`, `run_length`, `run_length_units` | first year and duration, in any unit from seconds to years |
| `run_dt`, `run_dt_units` | model step: one month or whole days |
| `cmntecd`, `vegecd`, ... | parameter files, by default `{tem_src}/params/gdstem/` |
| `clmoutvars`, `temoutvars`, `output_file` | output variables (YAML lists) and path (default `./OUTPUT/tem.nc`) |
| `run_mode`, `n_nodes`, `n_cpus`, `walltime`, `partition`, `mem`, `sbatch_options` | sbatch settings; cells are shared between the `n_cpus` MPI tasks |
| other keys | options of `tem_config.yaml`, one key each |

Climate units come from the `units` attribute and are converted. `tmin` and `tmax` can replace `tair` and `dtr`, and `dewpoint` or `huss` can replace `vpr`. For monthly steps, daily and hourly data are averaged to months. A daily step needs `netcdf_climate_in_frequency: daily`.

Site calibration files are top-level `*_dat` keys. The key name is a label, and the community ID is read from the file. Setting any `*_dat` key in a case replaces the whole default set, so list all the files you need:

```yaml
hvc_dat: "{tem_src}/params/gdstem/hvc45_trendy.yaml"
hvd_dat: "{tem_src}/params/gdstem/hvd45_trendy.yaml"
```

## Build input data

`gen_climate_inputs.py` writes daily forcing and `gen_static_inputs.py` writes the other inputs. Run both from the repository root:

```bash
A="--out INPUT --cache downloads --bbox -125 -110 32 49 --res 0.5"
python src/gen_climate_inputs.py --out INPUT --bbox -125 -110 32 49 --start 2000 --end 2019 gridmet
python src/gen_static_inputs.py $A co2 --start 2000 --end 2019
python src/gen_static_inputs.py $A all --tcomm XTEM/params/gdstem/tcomm45_lulc.yaml --year 2015 --cohorts primary secondary crops pasture urban
```

`gen_climate_inputs.py` writes `climate_<source>.nc` and `varmap_<source>.yaml`. Copy the varmap into `run_config.yaml` and set `netcdf_climate_in_frequency: daily`. Ozone needs a CEDA token (`CEDA_TOKEN`) and lightning an Earthdata Login token (`EARTHDATA_TOKEN`). Everything else downloads without credentials. Sources, units and land-cover assumptions are in [technical_desc.md](technical_desc.md).

## Test

`tools/run_test.py` clones XTEM and TEM_UW_APP, builds the model, creates a global 1 degree case for one year and runs it monthly and daily under `srun`. It needs `~/.cdsapirc` for ERA5, or `--mock-era5` for synthetic forcing that tests the workflow only. `--all` adds the cases behind flags, and `-h` lists the options. The work directory is the current directory unless `--work` is given. Run it from a batch script that activates the conda environment, sets `TEM_MODULES` (for example `"gcc openmpi netcdf"`) and calls `python run_test.py --mock-era5 --all --srun-args=--mpi=pmix`.

## Limits

- Daily results have not been compared with observations.
- Only the western United States example has been tested; the inputs the app writes for it match those shipped with XTEM.
- The global land-cover builder has not been validated against the lab's earlier inputs.
