#!/usr/bin/env python3
"""Make a designated integration job fail when prerequisites cause skipped tests."""
import sys
import xml.etree.ElementTree as ET

cases = list(ET.parse(sys.argv[1]).getroot().iter("testcase"))
skipped = [case.attrib.get("name", "unknown") for case in cases if case.find("skipped") is not None]
if not cases or skipped:
    sys.exit("Required tests did not execute: " + (", ".join(skipped) or "no tests collected"))
print(f"All {len(cases)} required tests executed without skips.")
