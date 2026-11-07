# Climate NetCDF

Optional place for the climate NetCDF files (`netcdf_input_file` can point anywhere, and
accepts one path, a glob or a list). Required variables: air temperature (or tmin and
tmax), diurnal range (or tmin and tmax), precipitation, downward shortwave radiation,
vapour pressure (or dewpoint or specific humidity with surface pressure), wind, and
elevation. Set `netcdf_varmap` and `netcdf_input_frequency` in `run_config.yaml`.
