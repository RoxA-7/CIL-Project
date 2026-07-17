from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cil_restart.legacy_diagnostic import load_config, run_variant


def main() -> None:
    parser = argparse.ArgumentParser(description="Run legacy VGG head-level causal diagnostics")
    parser.add_argument("--config", default=str(ROOT / "configs" / "diagnostic.yaml"))
    parser.add_argument("--variants", nargs="+", default=["D0", "D1", "D2", "D3", "D4"])
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--force-cache", action="store_true")
    args = parser.parse_args()
    cfg = load_config(args.config)
    if args.epochs is not None:
        cfg["epochs"] = args.epochs
    for i, variant in enumerate(args.variants):
        if variant not in cfg["variants"]:
            raise SystemExit(f"unknown variant {variant}")
        path = run_variant(cfg, ROOT, variant, force_cache=args.force_cache and i == 0)
        print(path)


if __name__ == "__main__":
    main()

