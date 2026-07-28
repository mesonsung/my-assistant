#!/usr/bin/env python3
"""Cron entrypoint for no_agent mode. Invoked by hermes cron scheduler."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

_TARGET = Path(__file__).resolve().parent / "generate_english_learning_pack.py"
sys.argv = [str(_TARGET), "--cron"]
runpy.run_path(str(_TARGET), run_name="__main__")
