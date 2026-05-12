from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    src_dir = Path(__file__).resolve().parent
    src_dir_str = str(src_dir)
    if sys.path[0] != src_dir_str:
        sys.path.insert(0, src_dir_str)

    from cli import main as cli_main

    cli_main()
