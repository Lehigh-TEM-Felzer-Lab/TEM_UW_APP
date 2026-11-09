"""Build run_config_Nov2026.pdf (key reference) and TEM_UW_APP-Technical-Description.pdf.

    python tools/make_docs.py        # needs pandoc and xelatex

The key reference is generated from config/run_config.yaml: one table per section, with the default and the comment of each key.
The technical description is README.md and docs/global_data.md in one document.
"""

import re
import subprocess
import tempfile
import textwrap
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADER = r"""\usepackage{xurl}
\urlstyle{tt}
\usepackage{fvextra}
\fvset{breaklines=true,breakanywhere=true}
\DefineVerbatimEnvironment{Highlighting}{Verbatim}{breaklines,breakanywhere,commandchars=\\\{\}}
\RecustomVerbatimEnvironment{verbatim}{Verbatim}{breaklines,breakanywhere}
\fvset{fontsize=\footnotesize}
\usepackage{longtable,booktabs,array}
\usepackage{etoolbox}
\AtBeginEnvironment{longtable}{\small}
\usepackage[nobottomtitles]{titlesec}
\renewcommand{\bottomtitlespace}{.25\textheight}
\setlength{\parindent}{0pt}
\setlength{\parskip}{4pt}
"""
KEY = re.compile(r"^([A-Za-z_]\w*):\s*(.*?)(?:\s+#\s+(.*))?$")
SECTION = re.compile(r"^# (\d+)\. (.+)$")


def width(c: int, rows: list[list[str]]) -> int:
    """Relative width of column c: the longest cell (at most 70), but not less than the longest unbreakable word."""
    cells = [r[c].strip() for r in rows]
    words = [w for t in cells for w in re.findall(r"`[^`]*`|\S+", t)]
    need = max(int(len(w) * 1.8) + 4 if w[0] == "`" else len(w) + 3 for w in words)
    return max(need, min(70, max(len(t) + t.count("`") * 8 for t in cells)) + 3)


def fit_tables(md: str) -> str:
    """Pipe tables get column widths from the dashes of the separator row: set them from the longest cell of each column."""
    lines, out, i = md.split("\n"), [], 0
    while i < len(lines):
        if (
            i + 1 < len(lines)
            and re.fullmatch(r"\|[-:| ]+\|", lines[i + 1])
            and lines[i].startswith("|")
        ):
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            rows = [
                re.split(r"(?<!\\)\|", r.strip()[1:-1])
                for r in lines[i : i + 1] + lines[i + 2 : j]
            ]
            w = [width(c, rows) for c in range(len(rows[0]))]
            out += [
                lines[i],
                "|" + "|".join("-" * n for n in w) + "|",
                *lines[i + 2 : j],
            ]
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def wrap_yaml(lines: list[str]) -> str:
    """Wrap long comments to 96 columns; a trailing comment moves above its key."""
    prose = lambda t: t.startswith("# ") and not t.startswith("#  ")
    joined: list[str] = []
    for ln in lines:
        if joined and prose(ln) and prose(joined[-1]) and len(joined[-1]) >= 70:
            joined[-1] += " " + ln[2:]
        else:
            joined.append(ln)
    out = []
    for ln in joined:
        m = re.match(r"^(\s*)([^#\s][^#]*?)\s+#\s+(.*)$", ln)
        if len(ln) > 96 and m:
            out += textwrap.wrap(
                m.group(3), 94, initial_indent="# ", subsequent_indent="# "
            )
            ln = m.group(1) + m.group(2)
        elif len(ln) > 96 and ln.startswith("#"):
            out += textwrap.wrap(
                ln[1:].strip(), 94, initial_indent="# ", subsequent_indent="# "
            )
            continue
        out.append(ln)
    return "```yaml\n" + "\n".join(out) + "\n```"


def breakable(md: str) -> str:
    """Long inline code does not wrap in LaTeX: set it with \\path, which breaks after / and _ (fenced blocks are left alone)."""
    out, fenced = [], False
    for line in md.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced:
            line = re.sub(
                r"`([^`\n]+)`",
                lambda m: (
                    f"`\\path|{m.group(1)}|`{{=latex}}"
                    if len(m.group(1)) >= 16
                    and "|" not in m.group(1)
                    and " " not in m.group(1)
                    else m.group(0)
                ),
                line,
            )
        out.append(line)
    return "\n".join(out)


def pandoc(md: str, out: Path, title: str, subtitle: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src, hdr = Path(tmp) / "in.md", Path(tmp) / "h.tex"
        src.write_text(breakable(fit_tables(md)))
        hdr.write_text(HEADER)
        meta = {
            "title": title,
            "subtitle": subtitle,
            "author": "Lehigh TEM Felzer Lab",
            "date": f"{datetime.now(tz=UTC):%B %Y}",
        }
        cmd = [
            "pandoc",
            "-f",
            "markdown-smart+autolink_bare_uris",
            str(src),
            "-o",
            str(out),
            "--pdf-engine=xelatex",
            "-H",
            str(hdr),
        ]
        for k, v in {
            "geometry:margin": "2.2cm",
            "fontsize": "10pt",
            "colorlinks": "true",
            "linkcolor": "blue",
        }.items():
            cmd += ["-V", f"{k}={v}"]
        for k, v in meta.items():
            cmd += ["-M", f"{k}={v}"]
        cmd += ["--toc", "--toc-depth=2", "--number-sections"]
        subprocess.run(cmd, check=True, cwd=ROOT / "docs")


def patch_notes() -> str:
    heading = "# I/O and storm patch"
    readme = (ROOT / "README.md").read_text()
    body = readme.split(heading + "\n", 1)[1].split("\n# ", 1)[0]
    return f"{heading}\n{body.strip()}\n"


def key_reference() -> str:
    out = [
        "# Overview\n",
        "`config/run_config.yaml` is the run configuration of TEM_UW_APP. A case-local `run_config.yaml` sets only the keys it changes; unknown keys are an error. The sections below are the file itself. Keys of the section Model options are written to `tem_config.yaml` of TEM_2026, whose template describes them in more detail.\n",
    ]
    out.append(patch_notes())
    block: list[str] = []
    started = False
    for line in (ROOT / "config" / "run_config.yaml").read_text().splitlines():
        if m := SECTION.match(line):
            if block:
                out.append(wrap_yaml(block) + "\n")
            title = m.group(2).split(" (")[0].capitalize().replace("Netcdf", "NetCDF")
            out.append(f"# {m.group(1)}. {title} {{-}}\n")
            block, started = [], True
        elif started and not line.startswith("# ---"):
            block.append(line)
        if block and not any(block):
            block = []
    out.append(wrap_yaml(block))
    return "\n".join(out)


def technical() -> str:
    readme = (ROOT / "README.md").read_text().split("\n", 1)[1]
    docs = (ROOT / "docs" / "global_data.md").read_text()
    return f"# Overview\n{readme}\n\n{docs}"


if __name__ == "__main__":
    pandoc(
        key_reference(),
        ROOT / "run_config_Nov2026.pdf",
        "run_config.yaml",
        "TEM_UW_APP run configuration, key reference",
    )
    pandoc(
        technical(),
        ROOT / "TEM_UW_APP-Technical-Description.pdf",
        "TEM_UW_APP",
        "Technical description",
    )
    print("wrote run_config_Nov2026.pdf and TEM_UW_APP-Technical-Description.pdf")
