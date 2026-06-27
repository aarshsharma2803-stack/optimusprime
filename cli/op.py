#!/usr/bin/env python3
"""Development runner: python cli/op.py <command>

For installed usage: op <command>  (see pyproject.toml entry point)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from optimusprime.cli.op import main

if __name__ == "__main__":
    main()
