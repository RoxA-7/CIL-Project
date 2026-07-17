from __future__ import annotations

import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cil_restart.audit import audit_legacy


def main() -> None:
    rows = audit_legacy(ROOT.parent / "增量学习代码" / "VGG16_CIL")
    out = ROOT / "results" / "tidy" / "legacy_code_audit.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(out)


if __name__ == "__main__":
    main()

