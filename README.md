# TUP: TEM Unified Preprocessor

A configuration-driven preprocessor for the Terrestrial Ecosystem Model (TEM). It reads
NetCDF climate (one file, a glob or a list) and a YAML file, and builds the case directory
that a TEM executable runs in: input CSV files, the XML control file and `tem_in.txt`.
The layout follows pyUFS. TUP does not run the model.

The target core is a YAML profile in `profiles/`, so the same NetCDF and run config work
for TEM_Biogeography, TEM_Monthly, TEM_Competition-Monthly and TEM_Daily, and a new core
is a new profile. Any grid resolution is accepted, and the NetCDF can be hourly, daily or
monthly.

## Quick start

```bash
git clone https://github.com/Lehigh-TEM-Felzer-Lab/tup.git
cd tup && conda env create -f env.yaml && conda activate tup
export TUP_ROOT=$PWD
mkdir -p ~/cases/west && cd ~/cases/west
cp $TUP_ROOT/examples/west/run_config.yaml .      # edit core, params_dir, domain
$TUP_ROOT/case_submit.sh
```

`run_mode: local` (default) runs in the foreground. `run_mode: slurm` submits with
`sbatch`, using `walltime`, `partition`, `account`, `mem`, `modules`, `sbatch_options`.
Keys you do not set come from `config/run_config.yaml`; unknown keys are rejected.

Then run the core from the case directory (the core reads `tem_in.txt` from the working
directory, it is not an option):

```bash
cd ~/cases/west && /path/to/xtem45_disturb
```

## Case directory after a successful run

```
west/
  run_config.yaml        your configuration
  tem_in.txt             one word: the name of the XML control file (tem_config.xml)
  tem_config.xml         core template with years, input paths, params and outputs filled in
  INPUT/
    grids.csv            cells of the run (lon, lat, area km2, region)
    climate/             tair, dtr, prec, nirr, vpr, wind, elev .csv
    static/              texture, ozone, ndep, cohort, mxcohort, co2.data
    params/              link to params_dir (.ecd and .dat files)
  HIST/                  model output while the core runs (empty after preprocessing)
  OUTPUT/                final products (written by the post-processing of the core repository)
  logs/tup.log
```

TEM_Daily also gets `INPUT/climate/co2.csv` and `ozone.csv` (see below) and has no
`INPUT/static/co2.data`.

`tem_in.txt` exists because every TEM core opens a file of this name in the working
directory and takes the XML file name from its first word. All other paths in the XML are
relative to the case directory (`./INPUT/...`, `./HIST/...`), so run the core from there.

## Inputs you provide

| Key | Meaning |
|---|---|
| `core` | profile name in `profiles/` or path to a profile YAML |
| `params_dir` | directory with the `.ecd` and `.dat` files named by the core XML; TUP lists the missing ones |
| `netcdf_input_file` | path, glob, or list of paths; merged by coordinates |
| `netcdf_input_frequency` | `hourly`, `daily` or `monthly` |
| `netcdf_varmap` | NetCDF variable for each of tair, dtr, prec, nirr, vpr, wind, elev |
| `resolution`, `lon_min`... `lat_max`, `region` | model grid and domain |
| `start_year`, `end_year` | transient years |
| `static_dir` | folder with `texture.csv`, `ozone.csv`, `ndep.csv`, `cohort.csv`, `mxcohort.csv`, `co2.data` (or give each as `*_file`) |
| `fire_file` | optional, only for cores with a fire module |
| `tem` | any XML tag to override, for example `xto3flag: 0` |
| `tem_outputs` | list of output variables; null keeps the template list |

Units are read from the NetCDF `units` attribute and converted. Variables may be given as
tmin/tmax instead of tair/dtr, and precipitation may be a rate or an amount per step.
Cells are the grid points inside the box that have valid elevation. The NetCDF may be
finer or coarser than `resolution`; `regrid_method` is `box_mean`, `bilinear` or `nearest`.
Daily input was tested for monthly cores (hourly is implemented but untested); monthly input cannot feed a daily core.

## Profiles

| Profile | Rows written | Status in testing |
|---|---|---|
| `tem_biogeography` | monthly | inputs byte-identical to TEM_Biogeography preprocessing |
| `tem_monthly` | monthly | executable built from TEM_Monthly ran to completion on a TUP case |
| `tem_competition_monthly` | monthly | executable built from the repository ran; cells finished through 2099 (run stopped by time limit) |
| `tem_daily` | daily, 365 or 366 rows per year | executable reads every file and starts simulating; the run then fails numerically because the daily calibration files are not in the repository (monthly ones were used as stand-ins). Not validated end to end |

land_legacy and GDSTEM have no profile yet (they read additional nitrogen-fertilizer
tags). `tools/scan_core.py <core_repo> <template.xml>` lists XML tags the source reads
that a template lacks; it reports tags that are read conditionally too, so check the output.

## Things that fail if you miss them

- Mode flags in the XML must match the static data. The TEM_Monthly template expects
  transient ozone, nitrogen deposition and land use files. With the single-year static
  files from TEM_Biogeography set `tem: {xto3flag: 0, xtndepflag: 0, tlulcflag: 0}`,
  otherwise the core stops with "Ran out of Ozone data" or "not coregistered".
- `params_dir` must contain the files named by the template (basenames only are used).
- The TEM_Daily XML in its repository has a stray closing tag; the template here is repaired.
- TEM_Daily reads CO2 and ozone as daily rows per cell. TUP writes CO2 as constant per
  year from `co2.data`, and ozone by repeating the monthly AOT40 value on each day of
  one non-leap year. This reading of AOT40 is an assumption and has not been checked
  against the model authors.
- Daily NetCDF years must be complete. TEM_Daily expects 366 days when `year % 4 == 0`
  and 365 otherwise; use a 365/366 calendar. Non-standard calendars are converted
  (missing days filled forward).
- All model output, including the climate echo files, is directed to `HIST/`.

## Adding a core

Copy the core's XML to `templates/`, copy the closest profile in `profiles/`, and change:
`xml_template`, `time_step` (monthly or daily), the tag names for each climate and static
file, `param_tags`, `output_tags`, `fixed_tags` (tags TUP forces, such as `intervalflag`).
Then run a small case and the core; the first error message usually names the tag or file.
Profile keys are documented by comments in the existing profiles.

## Layout

```
case_submit.sh  launchers/   submission (local or sbatch)
config/run_config.yaml       default configuration
profiles/ templates/         core definitions and XML templates
src/                         driver, climate, io, preprocess, case
examples/west/               small monthly NetCDF and static files
tools/scan_core.py
```
