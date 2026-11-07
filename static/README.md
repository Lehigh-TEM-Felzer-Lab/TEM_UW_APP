# Static input

Put the per-cell static files of the domain here, or set `static_dir`. Every file holds
rows for exactly the grid cells of the run (same lon, lat as `INPUT/grids.csv`), so the
files must match `resolution`. TUP subsets them to the run cells in grid order.

| File | Content | Row format |
|---|---|---|
| `texture.csv` | soil texture | `lon,lat, TEXTURE ,area,v1,v2,v3,flag, IGBP ,region` (v1-v3: the three texture percentages) |
| `ozone.csv` | long-term monthly AOT40 | `lon,lat, AOT40 ,area,year,total,max,avg,min,jan..dec, region` |
| `ndep.csv` | nitrogen deposition | `lon,lat,year,value` |
| `mxcohort.csv` | maximum cohorts per cell | `lon,lat, MXCOHRTS ,area,-111,n,n, region` |
| `cohort.csv` | land cover cohorts, one row per cohort | `lon,lat, LULCCHRT ,-111,cohort,...` |
| `co2.data` | annual CO2 (ppm) | `year<TAB>ppm` |

Formats are taken from the example files in `examples/west/static`; copy those to see the
exact layout.
