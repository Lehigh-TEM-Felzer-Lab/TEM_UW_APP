"""List the XML tags a TEM core reads and compare them with a TUP XML template.

usage: python tools/scan_core.py <core_repo_dir> <template.xml>
Use it when adding a profile: tags read by the source but absent from the template must be added.
"""

import re
import sys
from pathlib import Path
from xml.etree import ElementTree

READ = re.compile(r'"gofile"\s*,\s*"(\w+)"')

source = {
    m
    for f in Path(sys.argv[1]).glob("*.cpp")
    for m in READ.findall(f.read_text(errors="ignore"))
}
template = {e.tag for e in ElementTree.parse(sys.argv[2]).getroot()}
print(f"read by source, missing in template: {sorted(source - template)}")
print(f"in template, not read by source: {sorted(template - source)}")
