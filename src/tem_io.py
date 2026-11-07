# tem_io.py
"""Write the TEM climate, elevation and static CSV files."""

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

MONTHS = [
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
]
VARNAMES = {
    "tair": "TAIR",
    "dtr": "DTAIRRNG",
    "prec": "PREC",
    "nirr": "NIRR",
    "vpr": "VPRPRESS",
    "wind": "WIND",
    "co2": "CO2",
    "ozone": "AOT40",
}


def write_monthly_csv(
    path: Path, name: str, da: xr.DataArray, cells: pd.DataFrame
) -> None:
    """TEM monthly rows (cell-major, then year): lon,lat, VAR ,area,year,total,max,avg,min,jan..dec, region.

    da has dimensions (time, cell), or (month, cell) for a long-term mean (written as year -999).
    """
    if "month" in da.dims:
        values = da.transpose("cell", "month").values[:, None, :]
        years = np.array([-999])
    else:
        years = np.unique(da.time.dt.year.values)
        values = da.transpose("cell", "time").values.reshape(len(cells), len(years), 12)
    n_cell, n_year, _ = values.shape
    frame = pd.DataFrame(values.reshape(-1, 12), columns=MONTHS)
    frame.insert(0, "min", frame.min(axis=1))
    frame.insert(0, "avg", frame[MONTHS].sum(axis=1) / 12)
    frame.insert(0, "max", frame[MONTHS].max(axis=1))
    frame.insert(0, "total", frame[MONTHS].sum(axis=1))
    rows = np.repeat(np.arange(n_cell), n_year)
    with path.open("w") as out:
        for i, rec in enumerate(frame.itertuples(index=False)):
            cell = cells.iloc[rows[i]]
            head = f"{cell.lon:.4f},{cell.lat:.4f}, {VARNAMES[name]} ,{int(cell.area)},{years[i % n_year]}"
            stats = f"{rec.total:.1f},{rec.max:.1f},{rec.avg:.2f},{rec.min:.1f}"
            months = ",".join(f"{getattr(rec, m):.1f}" for m in MONTHS)
            out.write(f"{head},{stats},{months}, {cell.region}\n")


def write_daily_csv(
    path: Path, name: str, da: xr.DataArray, cells: pd.DataFrame
) -> None:
    """TEM daily rows (cell-major, then day): lon,lat, VAR ,area,year,month,day,value, region.

    The daily cores read 365 rows per year, 366 when year % 4 == 0, for every cell in the
    order of the grid, so every year must hold exactly that many days.
    """
    time = da.time.to_index()
    per_year = time.year.value_counts().sort_index()
    expected = {y: 366 if y % 4 == 0 else 365 for y in per_year.index}
    bad = {y: n for y, n in per_year.items() if n != expected[y]}
    if bad:
        raise ValueError(
            f"{name}: days per year {bad}; the daily core needs 365, or 366 when year % 4 == 0"
        )
    values = da.transpose("cell", "time").values
    stamp = pd.DataFrame({"y": time.year, "m": time.month, "d": time.day})
    with path.open("w") as out:
        for i, cell in enumerate(cells.itertuples()):
            head = f"{cell.lon:.4f},{cell.lat:.4f}, {VARNAMES[name]} ,{int(cell.area)}"
            tail = f", {cell.region}\n"
            out.writelines(
                f"{head},{y},{m},{d},{v:.4f}{tail}"
                for y, m, d, v in zip(stamp.y, stamp.m, stamp.d, values[i], strict=True)
            )


def write_elev_csv(path: Path, da: xr.DataArray, cells: pd.DataFrame) -> None:
    with path.open("w") as out:
        for cell, value in zip(cells.itertuples(), da.values, strict=True):
            out.write(
                f"{cell.lon:.4f},{cell.lat:.4f}, ELEV ,{int(cell.area)},{value:.1f}, {cell.region}\n"
            )


def subset_csv(source: Path, target: Path, cells: pd.DataFrame) -> None:
    """Write the rows of a per-cell TEM CSV (lon,lat first) for the grid cells, in cell order."""
    rows: dict[tuple[float, float], list[str]] = {}
    for line in source.read_text().splitlines():
        lon, lat = line.split(",", 2)[:2]
        rows.setdefault((round(float(lon), 4), round(float(lat), 4)), []).append(line)
    missing = [(c.lon, c.lat) for c in cells.itertuples() if (c.lon, c.lat) not in rows]
    if missing:
        raise ValueError(
            f"{source.name} has no rows for {len(missing)} cells, e.g. {missing[:3]}"
        )
    with target.open("w") as out:
        for cell in cells.itertuples():
            out.write("\n".join(rows[(cell.lon, cell.lat)]) + "\n")


def link(source: Path, target: Path) -> None:
    """Symlink target to source, replacing an earlier file or link."""
    target.unlink(missing_ok=True)
    target.symlink_to(source.resolve())
