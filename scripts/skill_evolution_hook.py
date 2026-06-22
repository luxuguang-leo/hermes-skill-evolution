#!/usr/bin/env python3
"""Wrapper: run the skill precipitation hook (incremental)."""
import sys, os
sys.path.insert(0, os.path.expanduser('~/.hermes/scripts'))
from mining.hook import incremental_scan
report = incremental_scan(scan_all=False, notify=False)
print(report)
