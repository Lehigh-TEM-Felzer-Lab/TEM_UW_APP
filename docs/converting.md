# Converting old files

For runs set up with the older TEM versions (TEM_Monthly, TEM_Biogeography, GDSTEM and others).

## Control and parameter files

```bash
python src/xml2yaml.py us_tem45_lulc.xml -o tem_config.yaml
python src/xml2yaml.py tcomm45_lulc.ecd -o tcomm50_lulc.yaml
```

`xml2yaml.py` turns an XML control file or an `.ecd`/`.dat` parameter file into YAML. Every tag becomes a key and the XML comments become YAML comments.
It repairs the known typos of the old files (a mismatched closing tag, an unclosed quote) and lists the ASCII input names it finds, since TEM_2026
reads NetCDF through the `netcdf_*_in_file` keys. The other keys keep their old names; compare the result with `templates/tem_config.yaml` of TEM_2026.

## ASCII inputs

```bash
python src/ascii2nc.py clm tair.csv prec.csv dtr.csv nirr.csv vpr.csv -o climate.nc
python src/ascii2nc.py clm wind.csv aot40.csv -o static.nc --grid climate.nc
python src/ascii2nc.py elev elev.csv -o static.nc --grid climate.nc
python src/ascii2nc.py soil soil.csv -o static.nc --grid climate.nc
python src/ascii2nc.py ndep ndep.csv -o static.nc --grid climate.nc
python src/ascii2nc.py co2 co2.csv -o co2.nc
python src/ascii2nc.py lulc lulc.csv -o lulc.nc --grid climate.nc
```

Repeated calls with the same `-o` add to the file. The kinds and the record layouts are listed at the top of `src/ascii2nc.py`:

| Kind | Record |
|---|---|
| `clm` | lon, lat, VAR, area, year, total, max, ave, min, jan to dec, region (year -999: climatology by month) |
| `daily` | lon, lat, VAR, area, year, month, day, value, region |
| `elev` | lon, lat, ELEV, area, elev, region |
| `soil` | lon, lat, SOIL, area, sand, silt, clay, wsoil, source, region |
| `ndep` | lon, lat, year, value |
| `co2` | year, ppmv |
| `lulc` | lon, lat, VAR, year, cohort, srccohort, standage, chrtarea, potveg, currentveg, subtype, agstate, agprevstate, tillflag, fertflag, irrgflag, disturbflag, disturbmonth, FRI, slashpar, vconvert, prod10par, prod100par, vrespar, sconvert, region |

Variables are renamed as TEM_2026 expects (`CLDINESS` to `clouds`, `DTAIRRNG` to `dtr`, `VPRPRESS` to `vpr`, `AOT40` to `ozone`). The model counts the cohorts
from `lulc.nc`, so the old cohort-count file (`MXCOHRTS`) is not needed. The old files list only cells with data: `--grid` takes a NetCDF file of the full grid,
usually the climate file, and restores the empty cells.

Checked by writing the example inputs of TEM_2026 as ASCII, converting them back (equal to the originals within the ASCII rounding) and running the model on the result
(maximum GPP 423.98 against 424.01). The `daily` and `ndep` kinds were not tested. The old ASCII fire inputs and the old output files are not converted;
`tem_utils` converts old HIST output.
