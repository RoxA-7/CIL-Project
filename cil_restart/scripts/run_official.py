from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cil_restart.official import METHODS, run_official


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", choices=sorted(METHODS), required=True)
    parser.add_argument("--seed", type=int, choices=[1993, 1994, 1995], required=True)
    parser.add_argument("--epochs", type=int, help="smoke only; omit for protocol value 160")
    parser.add_argument("--tasks", type=int, help="smoke only; omit for protocol value 6")
    args = parser.parse_args()
    print(run_official(ROOT, args.method, args.seed, args.epochs, args.tasks))


if __name__ == "__main__":
    main()

