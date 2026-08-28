#!/usr/bin/env python3
"""Offline structural validation for generated source files."""

import json
from pathlib import Path

from update_sources import validate_sources

root = Path(__file__).resolve().parents[1]
with (root / "apps.json").open(encoding="utf-8") as handle:
    lbox = json.load(handle)
with (root / "source.json").open(encoding="utf-8") as handle:
    altstore = json.load(handle)
validate_sources(lbox, altstore)
print("Source validation passed")
