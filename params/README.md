# Parameter files

Put the parameter files of the core you run in `params/<core>/` (the folder named like the
profile), or set `params_dir` in `run_config.yaml`. TUP links the folder to `INPUT/params`
and points the XML at the files by name. The files come from the model group; they are not
in the TEM repositories for the daily core. TUP stops and lists the missing names.

Community and vegetation parameters (.ecd), identical names for the monthly cores:

- `tcomm45_lulc.ecd`
- `trotz45_lulc.ecd`
- `tveg45_lulc.ecd` (TEM_Daily: `tveg45_lulc1_wlr.ecd`)
- `tconduct45_lulc.ecd`
- `tmcrv45_lulc.ecd`
- `ag45_lulc.ecd`

Site calibration files (.dat), listed in the `datfilenames` tag of the XML:

| Core | Files |
|---|---|
| `tem_monthly`, `tem_competition_monthly` | `hvc45_openn_303.dat`, `hvd45_openn_303.dat` |
| `tem_daily` | `pas_daily_ag0_lowsolc_1mrtz_0210.dat` |

The BKS daily example of TEM_Daily uses `tveg45_lulc1.ecd` (vegetation) and `pwn45_openn_0225.dat`
(calibration) instead of the WLR pair; put them in `params/tem_daily/` and set
`tem: {vegecd: ./INPUT/params/tveg45_lulc1.ecd, datfilenames: ./INPUT/params/pwn45_openn_0225.dat}`.
`tconduct45_lulc.ecd` of the daily calibration may differ from the monthly one of the same name.

To use other calibration files set the names in the XML tags through `tem:` in
`run_config.yaml`, and keep the files in the same folder. A file named in the template that
is absent from the folder is an error.

Monthly parameters have not been verified for the daily core: the daily model needs its
own calibration (time base of the rates, daily-scale files). Do not use monthly files for
real daily simulations; they only allow a test run.
