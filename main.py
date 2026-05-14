#!/usr/bin/env python3
"""
Thin CLI entrypoint for `python main.py …` from the repo root.

The orchestrator lives in `logic_platform.digitization.orchestrator`. This module
adds `src/` to sys.path when needed so you can run without fiddling PYTHONPATH.
"""

from __future__ import annotations

import sys
from pathlib import Path

_repo = Path(__file__).resolve().parent
_src = _repo / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from logic_platform.digitization.orchestrator import main

if __name__ == "__main__":
    main()
