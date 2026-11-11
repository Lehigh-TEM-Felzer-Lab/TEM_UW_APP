"""Global 1 degree test of XTEM and TEM_UW_APP: clone, build, get the data, run the cases, archive.

    python run_test.py                  # monthly and daily case
    python run_test.py --all            # plus every case behind a flag
    python run_test.py --only monthly,fire
    python run_test.py --mock-era5 --all   # synthetic forcing, no CDS account needed

The cells run under srun inside the batch job (the app only stages the case: run_model is false); --srun-args adds options
(write it as --srun-args=--mpi=pmix). Everything happens in WORK (default: the current directory): repos/, downloads/, data/, cases/<name>/,
summary.yaml and archive_<time>.tar.gz. Downloads and inputs that exist are reused and the build is incremental; the cases always run again.
--force removes the case directories first. Needs git, make, mpicxx, libyaml, libnetcdf, wget and the python packages of
TEM_UW_APP env.yaml plus cdsapi (a ~/.cdsapirc for the Climate Data Store; not needed with --mock-era5). TEM_MODULES="gcc openmpi" loads modules around
every command.

Climate is ERA5 daily statistics of one year, downloaded by src/gen_climate_inputs.py (CDS dataset derived-era5-single-levels-daily-statistics). The monthly
case aggregates it to months, the daily case runs the 365 days of that year (set run_length: 7 with run_length_units: days to stop after a week).
With --mock-era5, xarray writes deterministic synthetic forcing to downloads/era5_mock/climate_era5.nc, with the variables and the
daily coverage of the downloaded input; it tests the workflow and the fluxes are not realistic.
Every other input is made by src/gen_static_inputs.py from its source: CO2 (NOAA), soil (SoilGrids), elevation (ETOPO),
wind (WorldClim), land cover (LUH2), lightning (LIS/OTD), population (WorldPop) and N deposition (ISIMIP3b). Ozone comes from
CEDA when CEDA_TOKEN is set or from --ozone FILE:VAR[:SCALE]; otherwise a constant placeholder is used (AOT40 0), as is for a step
that fails (N deposition 1000 mg N m-2 yr-1). Lightning needs EARTHDATA_TOKEN or ~/.netrc (NASA Earthdata Login); without it the
fire case is skipped. GDP per person comes from --gdp FILE:VAR[:SCALE] (technical_desc.md of the app, Fire inputs) or is a constant
placeholder (10 thousand US dollars per person). The log says so, and fluxes are then not realistic.

The fire case runs with the parameter files of params/gdstem_fire (the fire model needs igef, fsr and fd), so it has its own land
cover file, numbered with the tcomm45_lulc.yaml of that set; every other case uses params/gdstem.

20241109 Changed: one build_mpi of XTEM runs the monthly and the daily case (build_mpi_daily removed).
20241110 Changed: the model runs under srun (the case is staged with run_model: false); --mock-era5 and --srun-args added.
20241111 Changed: repository XTEM; the land cover is numbered with the tcomm45_lulc.yaml of the parameter set; fire is the GDSTEM-FIRE
         model (gdp_file, params/gdstem_fire; fire_seed and fire_mode, competition and wood_pools are gone); --gdp added.
"""

import argparse
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import time
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import xarray as xr
import yaml

GITHUB = "https://github.com/Lehigh-TEM-Felzer-Lab"
REPOS = {
    "XTEM": "XTEM",
    "TEM_UW_APP": "TEM_UW_APP",
}
YEAR = 2019  # a year without 29 February
BOX = {"lon_min": -180.0, "lon_max": 179.0, "lat_min": -89.0, "lat_max": 89.0}
OZONE = 0.0  # placeholder AOT40 [ppb h]
NDEP = 1000.0  # placeholder N deposition [mg N m-2 yr-1]
GDP = 10.0  # placeholder GDP per person [thousand US dollars]
VARMAP = {
    k: k for k in ("tair", "tmin", "tmax", "prec", "nirr", "dewpoint")
}  # names written by gen_climate_inputs.py
OUTVARS = ["gpp", "npp", "nep", "vegc", "soilorgc"]
EQUIL = {"equil_tau_years": 100.0, "equil_min_years": 100, "equil_max_years": 300}  # daily cases and --fast
# name -> (flag, overrides of run_config.yaml); "needs" is a case that runs first, "fire" adds the fire inputs and params/gdstem_fire
CASES = {
    "monthly": ("", {"ostateflag": 1}),
    "daily": ("", {"run_dt_units": "day", **EQUIL}),
    "fire": ("fire", {"veg_fire": 1, "fire": True}),
    "spin_numspin": ("spin", {"spinflag": 1, "numspin": 2, "spintime": 20}),
    "spin_dynamic": ("spin", {"spinflag": 2, "de_nyears": 1}),
    "ode_rkf": ("solver", {"ode_solver": 2}),
    "rsoil_q10": ("solver", {"rsoil_method": 1}),
    "rhmoist_dndc": ("solver", {"rhmoist_method": 2}),
    "rhmoist_sech": ("solver", {"rhmoist_method": 3}),
    "no_nfeed": ("process", {"nfeed": 0}),
    "no_avln": ("process", {"avlnflag": 0}),
    "baseline": ("process", {"baseline": 1}),
    "no_moistlim": ("process", {"moistlim": 0}),
    "no_o3": ("process", {"o3flag": 0}),
    "agriculture": ("agri", {"agtillflag": 1, "agirrgflag": 1, "agfertflag": 1}),
    "restart": ("restart", {"istateflag": 1, "needs": "monthly"}),
}
FLAGS = sorted({v[0] for v in CASES.values() if v[0]})
SETS = ("gdstem", "gdstem_fire")  # parameter sets used by the cases
PARAM_KEYS = ("cmntecd", "rootzecd", "vegecd", "conductecd", "mcrbecd", "agecd")
t0 = time.time()


def say(msg: str) -> None:
    print(f"[{time.time() - t0:8.0f}s] {msg}", flush=True)


def sh(
    cmd: list[str],
    cwd: Path | None = None,
    log: Path | None = None,
    env: dict | None = None,
) -> int:
    """Run a command, with the modules of TEM_MODULES loaded; output goes to log or the terminal."""
    mods = os.environ.get("TEM_MODULES", "")
    if mods:
        line = " ".join(shlex.quote(c) for c in cmd)
        cmd = ["bash", "-lc", f"module load {mods} && exec {line}"]
    with open(log, "w") if log else nullcontext() as out:
        return subprocess.run(
            cmd,
            cwd=cwd,
            env={**os.environ, **(env or {})},
            stdout=out,
            stderr=subprocess.STDOUT if out else None,
            check=False,
        ).returncode


def need(cmd: list[str], **kw) -> None:
    if sh(cmd, **kw):
        log = kw.get("log")
        if log and Path(log).exists():
            tail = "\n".join(Path(log).read_text().splitlines()[-40:])
            print(f"--- last lines of {log}\n{tail}\n---", flush=True)
        sys.exit(f"failed: {' '.join(cmd)}")


def clone(work: Path) -> None:
    """Clone or update the repositories."""
    (work / "repos").mkdir(parents=True, exist_ok=True)
    for name, repo in REPOS.items():
        dest = work / "repos" / name
        if dest.exists():
            need(["git", "-C", str(dest), "pull", "--ff-only", "-q"])
        else:
            need(["git", "clone", "-q", f"{GITHUB}/{repo}", str(dest)])
    for name in REPOS:
        rev = subprocess.run(
            ["git", "-C", str(work / "repos" / name), "log", "--oneline", "-1"],
            capture_output=True,
            text=True,
            check=False,
        )
        say(f"{name} {rev.stdout.strip()}")


def build(work: Path, jobs: int) -> None:
    """build_mpi/xtem of XTEM, which runs the monthly and the daily cases (fire is compiled in: FIRE=1 is the default)."""
    src = work / "repos" / "XTEM"
    if shutil.which("mpicxx") is None and not os.environ.get("TEM_MODULES"):
        sys.exit(
            "mpicxx not found: load an MPI module (export TEM_MODULES='gcc openmpi netcdf' or module load in the job script)"
        )
    need(
        ["make", f"-j{jobs}", "MPI=1", "BUILD=build_mpi", "all"],
        cwd=src,
        log=work / "build.log",
    )
    say("built XTEM")


def era5(work: Path) -> Path:
    """downloads/era5/climate_era5.nc from src/gen_climate_inputs.py: tair, tmin, tmax, prec, nirr, dewpoint, daily, of the year."""
    out = work / "downloads" / "era5" / "climate_era5.nc"
    if not out.exists():
        if not (Path.home() / ".cdsapirc").exists() and "CDSAPI_KEY" not in os.environ:
            sys.exit("no ~/.cdsapirc: see https://cds.climate.copernicus.eu/how-to-api")
        (work / "logs").mkdir(exist_ok=True)
        say("ERA5 download")
        if sh(
            [
                sys.executable,
                str(work / "repos" / "TEM_UW_APP" / "src" / "gen_climate_inputs.py"),
                "--out",
                str(out.parent),
                "--start",
                str(YEAR),
                "--end",
                str(YEAR),
                "--bbox",
                *map(str, BOX.values()),
                "era5",
                "--grid",
                "1.0/1.0",
            ],
            log=work / "logs" / "era5.log",
        ):
            sys.exit("ERA5 download failed (logs/era5.log)")
    return out


def mock_era5(work: Path) -> Path:
    """downloads/era5_mock/climate_era5.nc: daily synthetic forcing of YEAR on the 1 degree grid of BOX."""
    out = work / "downloads" / "era5_mock" / "climate_era5.nc"
    if out.exists():
        return out
    lon = np.arange(BOX["lon_min"], BOX["lon_max"] + 0.5).round(4).astype("float32")
    lat = np.arange(BOX["lat_min"], BOX["lat_max"] + 0.5).round(4).astype("float32")
    time_axis = np.arange(
        np.datetime64(f"{YEAR}-01-01"),
        np.datetime64(f"{YEAR + 1}-01-01"),
        np.timedelta64(1, "D"),
    )
    # latitude and season vary the fields; the values are the same on every run
    hemisphere = np.sin(np.deg2rad(lat))[None, :]
    latitude = np.abs(hemisphere)
    phase = 2 * np.pi * (np.arange(time_axis.size)[:, None] - 172) / time_axis.size
    season = hemisphere * np.cos(phase)
    tair = 300.15 - 37 * latitude + 10 * season
    fields = {
        "tair": (tair, "K"),
        "tmin": (tair - 4, "K"),
        "tmax": (tair + 5, "K"),
        "prec": ((0.0005 + 0.0025 * (1 - latitude)) * (1 + 0.4 * season), "m"),
        "nirr": (np.maximum(10, 250 - 160 * latitude + 110 * season) * 86400, "J m-2"),
        "dewpoint": (tair - 7, "K"),
    }
    shape = (time_axis.size, lat.size, lon.size)
    ds = xr.Dataset(
        {
            name: (
                ("time", "lat", "lon"),
                np.broadcast_to(values.astype("float32")[:, :, None], shape),
                {"units": unit},
            )
            for name, (values, unit) in fields.items()
        },
        coords={
            "time": time_axis,
            "lat": ("lat", lat, {"units": "degrees_north"}),
            "lon": ("lon", lon, {"units": "degrees_east"}),
        },
        attrs={"source": "synthetic ERA5-style forcing for TEM workflow tests"},
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    encoding = {name: {"zlib": True, "complevel": 1} for name in fields}
    with TemporaryDirectory(dir=out.parent) as directory:
        staged = Path(directory) / out.name
        ds.to_netcdf(staged, engine="netcdf4", encoding=encoding)
        staged.replace(out)
    say(f"wrote mock ERA5 forcing {out}")
    return out


def static_data(work: Path, args: argparse.Namespace, sets: set[str]) -> Path:
    """data/: co2, elev, soil, wind, ozone, ndep, gdp, static, flash and popdens at the model grid; data/lulc_<set>/lulc.nc for each parameter set."""
    data, app = work / "data", work / "repos" / "TEM_UW_APP"
    data.mkdir(exist_ok=True)
    (work / "logs").mkdir(exist_ok=True)
    grid = ["--cache", str(work / "downloads"), "--res", "1.0"]
    grid += ["--bbox", *map(str, BOX.values())]

    def make(*sub: str, out: Path = data, tag: str = "") -> int:
        say(f"data: {sub[0]}{tag}")
        return sh(
            [
                sys.executable,
                str(app / "src" / "gen_static_inputs.py"),
                "--out",
                str(out),
                *grid,
                *sub,
            ],
            log=work / "logs" / f"data_{sub[0]}{tag}.log",
        )

    for f, sub in {
        "co2.nc": ("co2", "--start", str(YEAR), "--end", str(YEAR)),
        "soil.nc": ("soil",),
        "elev.nc": ("elev",),
        "wind.nc": ("wind",),
    }.items():
        if not (data / f).exists() and make(*sub):
            sys.exit(f"data step failed: {sub[0]} (logs/data_{sub[0]}.log)")
    # inputs of the fire case; a failed step leaves the file out and the case is skipped
    if "gdstem_fire" in sets:
        for f, sub in {
            "flash.nc": ("lightning",),
            "popdens.nc": ("population",),
        }.items():
            if not (data / f).exists() and make(*sub):
                say(
                    f"WARNING {sub[0]} failed, the fire case is skipped (logs/data_{sub[0]}.log)"
                )
    # inputs with a placeholder when the source is not available
    placeholders = [("ozone", args.ozone, OZONE), ("ndep", args.ndep, NDEP)]
    if "gdstem_fire" in sets:
        placeholders.append(("gdp", args.gdp, GDP))
    for name, spec, const in placeholders:
        if (data / f"{name}.nc").exists():
            continue
        if spec:
            file, var, *scale = spec.split(":")
            ok = (
                make(name, "--file", file, "--var", var, "--scale", *(scale or ["1"]))
                == 0
            )
        elif name == "ndep" or (name == "ozone" and os.environ.get("CEDA_TOKEN")):
            ok = make(name) == 0
        else:
            ok = False
        if not ok:
            say(f"data: {name} placeholder {const}")
            lon = np.arange(BOX["lon_min"], BOX["lon_max"] + 0.5).astype("float32")
            lat = np.arange(BOX["lat_min"], BOX["lat_max"] + 0.5).astype("float32")
            shape = (
                (12, lat.size, lon.size) if name == "ozone" else (lat.size, lon.size)
            )
            dims = ("month", "lat", "lon") if name == "ozone" else ("lat", "lon")
            unit = {
                "ozone": "ppb h",
                "ndep": "mg N m-2 yr-1",
                "gdp": "thousand US dollars per person",
            }[name]
            xr.Dataset(
                {
                    name: (
                        dims,
                        np.full(shape, const, "float32"),
                        {"units": unit, "comment": "constant placeholder"},
                    )
                },
                coords={"lat": lat, "lon": lon},
            ).to_netcdf(data / f"{name}.nc")
    if not (data / "static.nc").exists() and make("static"):
        sys.exit("data step failed: static (logs/data_static.log)")
    # the type numbers of the land cover depend on the parameter set (tcomm45_lulc.yaml of the set)
    for s in sorted(sets):
        out = data / f"lulc_{s}"
        out.mkdir(exist_ok=True)
        tcomm = work / "repos" / "XTEM" / "params" / s / "tcomm45_lulc.yaml"
        if not (out / "lulc.nc").exists() and make(
            "lulc", "--tcomm", str(tcomm), out=out, tag=f"_{s}"
        ):
            sys.exit(f"data step failed: lulc {s} (logs/data_lulc_{s}.log)")
    return data


def param_overrides(work: Path, pset: str) -> dict:
    """Parameter file keys of the app's run_config.yaml, with params/gdstem replaced by params/<pset>; every file must exist."""
    src = work / "repos" / "XTEM"
    default = yaml.safe_load(
        (work / "repos" / "TEM_UW_APP" / "config" / "run_config.yaml").read_text()
    )
    out = {}
    for key, value in default.items():
        is_param = key in PARAM_KEYS or (key.endswith("_dat") and len(key) > 4)
        if is_param and isinstance(value, str):
            new = value.replace("/params/gdstem/", f"/params/{pset}/")
            path = Path(new.replace("{tem_src}", str(src)))
            if not path.exists():
                sys.exit(f"{key}: {path} does not exist in the parameter set {pset}")
            out[key] = new
    return out


def run_case(
    name: str,
    work: Path,
    climate: Path,
    data: Path,
    args: argparse.Namespace,
    ncpu: int,
) -> dict:
    """Write run_config.yaml of the case, build its INPUT with the driver of the app and run the model."""
    over = dict(CASES[name][1])
    case = work / "cases" / name
    if args.force and case.exists():
        shutil.rmtree(case)
    case.mkdir(parents=True, exist_ok=True)
    exe = "build_mpi/xtem"
    needs = over.pop("needs", None)
    fire = over.pop("fire", False)
    pset = "gdstem_fire" if fire else "gdstem"
    cfg = {
        "tem_src": str(work / "repos" / "XTEM"),
        "tem_exe": f"{work / 'repos' / 'XTEM' / exe}",
        "run_mode": "local",
        "run_model": False,  # the app stages the case, srun runs the model
        "n_cpus": ncpu,
        "region": "GLOBAL_1DEG",
        "horizontal_resolution": 1.0,
        **BOX,
        "start_year": YEAR,
        "run_length": 1,
        "run_length_units": "years",
        "climate_file": str(climate),
        "netcdf_climate_in_frequency": "daily",
        "static_file": str(data / "static.nc"),
        "lulc_file": str(data / f"lulc_{pset}" / "lulc.nc"),
        "co2_file": str(data / "co2.nc"),
        "varmap": VARMAP,
        "clmoutvars": ["tair"],
        "temoutvars": OUTVARS,
    }
    if fire:
        missing = [
            f for f in ("flash.nc", "popdens.nc", "gdp.nc") if not (data / f).exists()
        ]
        if missing:
            return {
                "case": name,
                "rc": -1,
                "minutes": 0.0,
                "note": f"skipped: no {' '.join(missing)}",
            }
        cfg |= {
            "lightning_file": str(data / "flash.nc"),
            "population_file": str(data / "popdens.nc"),
            "gdp_file": str(data / "gdp.nc"),
        }
        cfg |= param_overrides(work, pset)
    if args.fast and over.get("run_dt_units") != "day":
        cfg |= EQUIL
    cfg |= over
    if needs:
        cfg |= {"istatefile": str(work / "cases" / needs / "OUTPUT" / "temstate.nc")}
    (case / "run_config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    (case / "logs").mkdir(exist_ok=True)
    app = work / "repos" / "TEM_UW_APP"
    start = time.time()
    rc = sh(
        [sys.executable, str(app / "src" / "driver.py")],
        cwd=case,
        log=case / "driver.out",
        env={"TEM_UW_APP_ROOT": str(app), "PYTHONPATH": str(app / "src")},
    )
    if rc == 0:
        (case / "OUTPUT").mkdir(exist_ok=True)
        for stale in (case / "OUTPUT").glob("tem.nc*"):
            stale.unlink()
        rc = sh(
            ["srun", "-n", str(ncpu), *shlex.split(args.srun_args), cfg["tem_exe"]],
            cwd=case,
            log=case / "logs" / "tem.out",
        )
    res = {"case": name, "rc": rc, "minutes": (time.time() - start) / 60, "note": ""}
    out = case / "OUTPUT" / "tem.nc"
    if rc == 0 and out.exists():
        with xr.open_dataset(out) as ds:
            v = ds[OUTVARS[0]]
            res["cells"] = int((ds["mask"] > 0).sum())
            good = v.where(v > -1e5)
            res["valid_cell_cohorts"] = int(good.notnull().any("time").sum())
            res["gpp_max"] = float(good.max())
    elif rc == 0:
        res["note"] = "no OUTPUT/tem.nc"
    else:
        tails = [
            p for p in (case / "logs" / "tem.out", case / "driver.out") if p.exists()
        ]
        res["note"] = " | ".join(
            p.read_text().strip().splitlines()[-1]
            for p in tails
            if p.read_text().strip()
        )[:300]
    return res


def archive(work: Path, keep_inputs: bool) -> Path:
    path = work / f"archive_{datetime.now(tz=UTC):%Y%m%d_%H%M%S}.tar.gz"
    with tarfile.open(path, "w:gz") as t:
        for f in ("summary.yaml", "build.log"):
            if (work / f).exists():
                t.add(work / f, arcname=f)
        for sub in ("logs",):
            if (work / sub).exists():
                t.add(work / sub, arcname=sub)
        for case in sorted((work / "cases").glob("*")):
            t.add(
                case,
                arcname=f"cases/{case.name}",
                filter=lambda i: None if "/INPUT" in i.name and not keep_inputs else i,
            )
    say(f"archive {path}")
    return path


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--work", default=os.getcwd(), help="work directory (default: current directory)")
    p.add_argument(
        "--ncpu", type=int, default=int(os.environ.get("SLURM_NTASKS", "32"))
    )
    p.add_argument("--only", help="comma separated case names (see below)")
    p.add_argument("--all", action="store_true", help="every case behind a flag")
    for f in FLAGS:
        p.add_argument(
            f"--{f}",
            action="store_true",
            help="cases: " + ", ".join(n for n, v in CASES.items() if v[0] == f),
        )
    p.add_argument(
        "--ozone",
        help="FILE:VAR[:SCALE] of a gridded AOT40 file instead of CEDA or the placeholder",
    )
    p.add_argument(
        "--ndep",
        help="FILE:VAR:SCALE of a N deposition file instead of the placeholder",
    )
    p.add_argument(
        "--gdp",
        help="FILE:VAR[:SCALE] of a GDP per person file (thousand US dollars) instead of the placeholder of the fire case",
    )
    p.add_argument(
        "--fast",
        action="store_true",
        help="cap the equilibration of the monthly cases (100 to 300 years)",
    )
    p.add_argument(
        "--force", action="store_true", help="remove the case directories first"
    )
    p.add_argument(
        "--box",
        help="--box=lon_min,lon_max,lat_min,lat_max instead of the globe (quick tests)",
    )
    p.add_argument(
        "--mock-era5",
        action="store_true",
        help="synthetic daily forcing instead of the ERA5 download (workflow test only)",
    )
    p.add_argument(
        "--srun-args",
        default="",
        help='extra options of srun, written --srun-args="--mpi=pmix"',
    )
    p.add_argument("--skip-build", action="store_true")
    p.add_argument(
        "--keep-inputs",
        action="store_true",
        help="put the INPUT directories of the cases in the archive",
    )
    a = p.parse_args()
    if a.box:
        BOX.update(dict(zip(BOX, map(float, a.box.split(",")), strict=True)))
    work = Path(a.work)
    (work / "cases").mkdir(parents=True, exist_ok=True)
    flags = set(FLAGS) if a.all else {f for f in FLAGS if getattr(a, f)}
    names = (
        a.only.split(",")
        if a.only
        else [n for n, v in CASES.items() if not v[0] or v[0] in flags]
    )
    names = [n for n in names if n in CASES]
    for n in list(names):  # a case that needs another one runs after it
        dep = CASES[n][1].get("needs")
        if dep and dep not in names:
            names.insert(0, dep)
    sets = {"gdstem_fire" if CASES[n][1].get("fire") else "gdstem" for n in names}
    signal.signal(signal.SIGTERM, lambda *_: sys.exit("SIGTERM: archiving what exists"))
    rows: list[dict] = []
    try:
        clone(work)
        if not a.skip_build:
            build(work, min(a.ncpu, 16))
        climate = mock_era5(work) if a.mock_era5 else era5(work)
        data = static_data(work, a, sets)
        for n in names:
            say(f"case {n}")
            rows.append(run_case(n, work, climate, data, a, a.ncpu))
            say(str(rows[-1]))
            (work / "summary.yaml").write_text(yaml.safe_dump(rows, sort_keys=False))
    finally:
        archive(work, a.keep_inputs)
    return int(any(r["rc"] and not r["note"].startswith("skipped") for r in rows))


if __name__ == "__main__":
    sys.exit(main())
