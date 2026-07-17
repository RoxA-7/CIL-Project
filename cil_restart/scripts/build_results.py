from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cil_restart.reporting import build_figures, build_tables, build_tidy, run_consistency_checks


def main() -> None:
    raw = ROOT / "results" / "raw"
    tidy = ROOT / "results" / "tidy"
    tables = ROOT / "results" / "tables"
    figures = ROOT / "results" / "figures"
    summary_dir = ROOT / "results" / "summary"
    task, classes, summary = build_tidy(raw, tidy)
    audit_path = tidy / "legacy_code_audit.csv"
    build_tables(task, summary, tables, audit_path)
    build_figures(task, raw, figures, summary_dir)
    checks = run_consistency_checks(task, summary, summary_dir)
    print(f"runs={len(summary)}, task_rows={len(task)}, class_rows={len(classes)}")
    print(f"numeric_checks={checks['all_numeric_checks_passed']}")


if __name__ == "__main__":
    main()

