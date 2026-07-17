from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cil_restart.official import dependency_report


def main() -> None:
    report = dependency_report()
    official = ROOT / "third_party" / "CLearning"
    expected_commit = "ce0789a40bda9e566a1e0432d3ac320937ca48f0"
    if (official / ".git").exists():
        report["official_present"] = True
        report["official_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=official, text=True).strip()
        report["official_clean"] = not bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=official, text=True).strip())
    else:
        report["official_present"] = False
        report["official_commit"] = None
        report["official_clean"] = None
        report["official_expected_commit"] = expected_commit
        report["official_error"] = f"missing official checkout at {official}"
    deps_ready = all(report["modules"][m]["ok"] for m in ["torch", "torchvision", "continuum", "yaml", "tensorboard", "scipy", "sklearn"])
    report["ready"] = report["cuda_available"] and deps_ready and report["official_present"]
    out = ROOT / "results" / "summary" / "official_environment.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
