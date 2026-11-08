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
