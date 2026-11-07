# tem_case.py
"""Create the case directory: INPUT/params, HIST/, OUTPUT/, logs/, the XML and tem_in.txt."""

import logging
from pathlib import Path

import tem_xml

log = logging.getLogger("CASE")
XML_NAME = "tem_config.xml"
YEAR_TAGS = ("clmstartyr", "de_startyear", "startyr")


def file_values(template: Path, name: str) -> list[str]:
    return [v.strip() for v in tem_xml.text(template, name).split(",") if v.strip()]


def param_tags(cfg: dict) -> dict[str, str]:
    """Parameter file tags of the template rewritten to INPUT/params/<name>; the files must exist."""
    profile, params = cfg["profile"], cfg["params_dir"]
    tags, missing = {}, []
    for name in profile.get("param_tags", []):
        files = [Path(f).name for f in file_values(profile["xml_template"], name)]
        missing += [f for f in files if not (params / f).is_file()]
        tags[name] = ",".join(f"./INPUT/params/{f}" for f in files)
    if missing:
        raise FileNotFoundError(
            f"{len(missing)} parameter files named by the {profile['name']} template are not in "
            f"params_dir {params}: {sorted(set(missing))}"
        )
    return tags


def output_tags(cfg: dict) -> dict[str, str]:
    """XML tags of the model output: every file goes to HIST/; tem_outputs replaces the variable list."""
    profile = cfg["profile"]
    template = profile["xml_template"]
    out = profile.get("output_tags", {})
    if not out:
        return {}
    tags = {}
    clm = out.get("climate_files")
    if clm and "missing" not in file_values(template, clm):
        tags[clm] = ",".join(
            f"./HIST/{Path(f).name}" for f in file_values(template, clm)
        )
    variables = cfg["tem_outputs"]
    if variables:
        pattern = profile.get("output_pattern", "{var}.TEMOUT")
        files = [pattern.format(var=v) for v in variables]
        tags |= {out["variables"]: ",".join(variables), out["count"]: len(variables)}
    else:
        files = file_values(template, out["files"])
    tags[out["files"]] = ",".join(f"./HIST/{Path(f).name}" for f in files)
    return tags


def tags(cfg: dict, input_tags: dict[str, str]) -> dict[str, object]:
    """Years, then input paths, parameter paths, output paths, fixed profile tags and user overrides."""
    start, end = cfg["start_year"], cfg["end_year"]
    derived = {t: start for t in YEAR_TAGS} | {
        "endyr": end,
        "transtime": end - start + 1,
        "lulclastyr": end,
    }
    return {
        **derived,
        **input_tags,
        **param_tags(cfg),
        **output_tags(cfg),
        **cfg["profile"].get("fixed_tags", {}),
        **cfg["tem"],
    }


def stage(cfg: dict, input_tags: dict[str, str]) -> None:
    """Create the case subdirectories, link the parameter files into INPUT/, write the XML and tem_in.txt."""
    case = cfg["case_dir"]
    for sub in ("INPUT", "HIST", "OUTPUT", "logs"):
        (case / sub).mkdir(parents=True, exist_ok=True)
    link = case / "INPUT" / "params"
    link.unlink(missing_ok=True)
    link.symlink_to(cfg["params_dir"].resolve())
    xml = tem_xml.render(cfg["profile"]["xml_template"], tags(cfg, input_tags))
    (case / XML_NAME).write_text(xml)
    (case / "tem_in.txt").write_text(f"{XML_NAME}\n")
    log.info("Created %s for the %s core", case, cfg["profile"]["name"])
