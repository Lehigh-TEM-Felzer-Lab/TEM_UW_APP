# TEM_UW_APP

Prepares and runs a case of [TEM_2026](https://github.com/Lehigh-TEM-Felzer-Lab/TEM_2026). The app regrids gridded NetCDF data to the model grid,
writes the NetCDF inputs and `tem_config.yaml` of the model, and runs or submits `xtem`. It also builds the global input files and converts
the files of the older TEM versions. The earlier CSV/XML workflow is not supported; its last version is the commit before this one.

# What files are what

| Path | Content |
|---|---|
| `case_submit.sh` | entry point, run from the case directory |
| `config/run_config.yaml` | all keys with defaults and comments |
| `src/driver.py`, `tem_climate.py`, `tem_config.py` | case builder: regridding, units, `tem_config.yaml` |
| `src/make_global_inputs.py` | builds `co2.nc`, `static.nc`, `lulc.nc` and the fire files for any region |
| `src/xml2yaml.py`, `src/ascii2nc.py` | convert old XML, parameter and ASCII files |
| `launchers/` | local and SLURM launchers |
| `examples/west/` | western United States example |
| `docs/` | `global_data.md` (sources of the input data), `converting.md` |
| `tools/make_docs.py` | builds the two PDFs |

# Setup

```bash
conda env create -f env.yaml && conda activate tem_uw_app
git clone https://github.com/Lehigh-TEM-Felzer-Lab/TEM_2026
make -C TEM_2026 -j4                  # serial: build/xtem
make -C TEM_2026 mpi -j4              # MPI, for n_cpus > 1: build_mpi/xtem
export TUP_ROOT=$PWD
```

# Running a case

1. Copy `examples/west/run_config.yaml` to an empty directory.
2. Set `tem_src` (the TEM_2026 checkout), the climate files, the box and the years. For `n_cpus > 1` set `tem_exe: "{tem_src}/build_mpi/xtem"`.
3. Run `$TUP_ROOT/case_submit.sh` from that directory. With `run_mode: slurm` it submits with sbatch; with `run_model: false` it only builds the case.

```
run_config.yaml   tem_config.yaml
INPUT/            climate.nc static.nc lulc.nc co2.nc (lightning.nc population.nc)
OUTPUT/           tem.nc, written by the model
logs/
```

# Configuration

`config/run_config.yaml` lists every key; keys you do not set take its values and unknown keys are an error.

| Key | Description |
|---|---|
| `tem_src`, `tem_exe` | TEM_2026 checkout and executable (default `{tem_src}/build/xtem`) |
| `netcdf_climate_in_file`, `netcdf_climate_in_frequency` | climate files (path, glob or list) and their time step (hourly, daily, monthly) |
| `netcdf_static_in_file`, `netcdf_lulc_in_file`, `netcdf_co2_in_file` | static, land-cover and CO2 files in the layout of TEM_2026 `docs/io_structure.md` |
| `netcdf_fire_in_file`, `netcdf_population_in_file` | lightning flashes and population density, needed when `veg_fire: 1` |
| `varmap` | `<model variable>: <variable in your files>`; the model name is used first, the map only when the file lacks it |
| `horizontal_resolution`, `lon_min` to `lat_max`, `regrid_method` | model grid and regridding (`box_mean`, `bilinear`, `nearest`) |
| `spinflag`, `veg_fire`, `xnfertflag`, ... | the options of `tem_config.yaml`, one key each |
| `cmntecd`, `vegecd`, ... | parameter files, by default `{tem_src}/params/biogeography/` |
| `clmoutvars`, `temoutvars` | variables written to `OUTPUT/tem.nc` |
| `run_mode`, `n_nodes`, `n_cpus`, `walltime`, `partition`, `mem`, `sbatch_options` | sbatch settings as in pyUFS; the cells are shared between the `n_cpus` MPI tasks |

Climate units are read from the `units` attribute and converted. `tmin` and `tmax` can replace `tair` and `dtr`, and `dewpoint` or `huss` can replace `vpr`.
Daily and hourly data are averaged to months.

# Input data

`climate.nc` is made by the app from your climate files. The other inputs come from `src/make_global_inputs.py`:

```bash
A="--out INPUT --cache downloads --lon-min -125 --lon-max -110 --lat-min 32 --lat-max 49 --res 0.5"
python src/make_global_inputs.py $A co2 --start 2015 --end 2024
python src/make_global_inputs.py $A soil
python src/make_global_inputs.py $A elev
python src/make_global_inputs.py $A wind
python src/make_global_inputs.py $A static
python src/make_global_inputs.py $A lulc --luh2 states.nc --luh2-static staticData_quarterdeg.nc --year 2015
```

Ozone, N deposition and the fire files come from files you supply (`ozone`, `ndep` and `fire` subcommands). Sources, download links,
units and the land-cover assumptions are in [docs/global_data.md](docs/global_data.md). Files of older TEM versions are converted as in
[docs/converting.md](docs/converting.md). Then set the `netcdf_*_in_file` keys of `run_config.yaml` to the files.

# Documentation

| File | Content |
|---|---|
| [run_config_Nov2026.pdf](run_config_Nov2026.pdf) | every key of `run_config.yaml` with default and meaning |
| [TEM_UW_APP-Technical-Description.pdf](TEM_UW_APP-Technical-Description.pdf) | this README and the documents in `docs/` |

`python tools/make_docs.py` rebuilds both (needs pandoc and xelatex).

# Limits

- The app writes monthly forcing, so it runs `run_dt: 1`, `run_dt_units: month` and rejects other steps. Daily forcing is not generated.
- Tested on the western United States example only; the inputs the app writes for it are identical to those shipped with TEM_2026.
- The global land-cover builder is not validated against the lab's earlier inputs.
