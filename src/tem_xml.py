# tem_xml.py
"""Fill the XML template of a TEM core: ElementTree keeps the tag order and the comments."""

import xml.etree.ElementTree as ET
from pathlib import Path


def read(template: Path) -> ET.Element:
    """Parse the template, keeping the comments."""
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    return ET.parse(template, parser).getroot()


def tag(root: ET.Element, name: str) -> ET.Element:
    found = root.findall(name)
    if len(found) != 1:
        raise KeyError(f"XML tag <{name}> found {len(found)} times; expected once")
    return found[0]


def render(template: Path, values: dict[str, object]) -> str:
    """The template XML with the text of every tag in values replaced (comments are kept)."""
    root = read(template)
    for name, value in values.items():
        tag(root, name).text = str(value)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode") + "\n"


def text(template: Path, name: str) -> str:
    """The text of one tag of the template."""
    return (tag(read(template), name).text or "").strip()
