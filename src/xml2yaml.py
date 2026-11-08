"""Convert a TEM XML control file or parameter file (.xml, .ecd, .dat) to YAML.

The YAML keeps every tag name as a key and the explanatory XML comments as YAML comments,
so the converted run configuration documents itself. Child elements that carry attributes
or children (<community>, <temveg>) become list entries; their attributes (type, description,
...) become keys. The keys are those of TEM_2026 tem_config.yaml, but the input file names (icldsfname, ...) are not used any more.


    xml2yaml.py hvd_openn_xtem.xml                 # writes hvd_openn_xtem.yaml
    xml2yaml.py tveg45_lulc.ecd -o tveg45_lulc.yaml
"""

import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

NUMBER = re.compile(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")


def scalar(text: str) -> str:
    text = text.strip()
    if NUMBER.fullmatch(text):
        return text
    if text == "":
        return '""'
    return yaml.safe_dump(text, width=10**9, allow_unicode=True).split("\n")[0]


def comment_lines(text: str, indent: str) -> list[str]:
    return [f"{indent}# {line.strip()}" for line in text.strip().splitlines()]


def emit(elem: ET.Element, indent: str, first_prefix: str | None = None) -> list[str]:
    """Lines for the contents of elem: its attributes, then its children.

    first_prefix replaces the indent on the first line (used for the "- " of list entries).
    """
    lines: list[str] = []
    pending: list[str] = []

    def put(line: str) -> None:
        lines.extend(pending)
        pending.clear()
        lines.append(indent + line)

    for key, value in elem.attrib.items():
        put(f"{key}: {scalar(value)}")

    children = list(elem)
    done: set[str] = set()
    for child in children:
        if child.tag is ET.Comment:
            pending.extend(comment_lines(child.text or "", indent))
        elif len(child) or child.attrib:
            if child.tag in done:
                continue
            done.add(child.tag)
            put(f"{child.tag}:")
            for item in (c for c in children if c.tag == child.tag):
                lines.extend(emit(item, indent + "    ", indent + "  - "))
        else:
            put(f"{child.tag}: {scalar(child.text or '')}")
    lines.extend(pending)

    if first_prefix is not None and lines:
        # The first non-comment line carries the list marker.
        for i, line in enumerate(lines):
            if not line.lstrip().startswith("#"):
                lines[i] = first_prefix + line[len(indent) :]
                break
    return lines


MISMATCHED = re.compile(r"<(\w+)>([^<\n]*)</(\w+)>")


def repair(text: str, name: str) -> str:
    """Fix <a>v</b> on one line and an unclosed attribute quote. The TEM XML reader looks only for the closing tag, so the
    closing name is the one the model sees (gdstem/tcomm45_lulc.ecd has <submuntype4>)."""

    def fix(m: re.Match) -> str:
        if m.group(1) == m.group(3):
            return m.group(0)
        print(f"{name}: <{m.group(1)}> closed by </{m.group(3)}>, using {m.group(3)}")
        return f"<{m.group(3)}>{m.group(2)}</{m.group(3)}>"

    text = re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+);)", "&amp;", text)
    text = MISMATCHED.sub(fix, text)
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.count('"') % 2 and "=" in line and not line.rstrip().endswith(">"):
            print(f"{name}: line {i + 1} has an unclosed quote, closing it")
            lines[i] = line.rstrip() + '"'
    return "\n".join(lines)


def convert(path: Path) -> str:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    parser.feed(repair(path.read_text(), path.name))
    root = parser.close()
    header = [
        f"# Converted from {path.name} by src/xml2yaml.py (root element: {root.tag})"
    ]
    return "\n".join(header + emit(root, "")) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", type=Path)
    ap.add_argument("-o", "--output", type=Path, help="default: source with .yaml")
    args = ap.parse_args()
    out = args.output or args.source.with_suffix(".yaml")
    text = convert(args.source)
    out.write_text(text)
    print(out)
    names = re.findall(r"^(i\w+fname): (\S+)", text, re.MULTILINE)
    if names:
        print(
            "ASCII inputs named in the file: convert them with src/ascii2nc.py and set netcdf_*_in_file"
        )
        for key, value in names:
            if value != "missing":
                print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
