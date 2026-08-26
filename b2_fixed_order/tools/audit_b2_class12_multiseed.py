from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import mean, stdev
import uuid
from typing import Any, Mapping, Sequence


BUSINESS = {
    "seed2026_recomputed_for_multiseed.json",
    "multiseed_summary.json",
    "input_sha256.json",
}
METRICS = (
    "class10_accuracy",
    "class11_accuracy",
    "class12_accuracy",
    "old_macro_accuracy",
    "pair_harmonic_accuracy",
    "triple_harmonic_accuracy",
    "triple_worst_accuracy",
    "overall_accuracy",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("aggregate audit mismatch: JSON root")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _verify_tree(root: Path, expected: set[str] | None = None) -> str:
    if not root.is_dir():
        raise ValueError("aggregate audit mismatch: signed tree missing")
    manifest = _read_json(root / "artifact_sha256.json")
    if expected is not None and set(manifest) != expected:
        raise ValueError("aggregate audit mismatch: business files")
    if {path.name for path in root.iterdir()} != set(manifest) | {
        "artifact_sha256.json",
        "COMPLETE.json",
    }:
        raise ValueError("aggregate audit mismatch: tree contents")
    for name, digest in manifest.items():
        if _sha256(root / name) != digest:
            raise ValueError("aggregate audit mismatch: tree SHA256")
    complete = _read_json(root / "COMPLETE.json")
    manifest_sha = _sha256(root / "artifact_sha256.json")
    if complete.get("status") != "complete" or complete.get("artifact_manifest_sha256") != manifest_sha:
        raise ValueError("aggregate audit mismatch: COMPLETE")
    return manifest_sha


def _checks(b0: Mapping[str, Any], b2: Mapping[str, Any], deltas: Sequence[float], truth: bool, equivalence: bool) -> dict[str, Any]:
    original = {
        "class12_minimum": float(b2["class12_accuracy"]) >= 0.50,
        "recent_classes_nonzero": min(float(b2["class10_accuracy"]), float(b2["class11_accuracy"]), float(b2["class12_accuracy"])) > 0.0,
        "triple_worst_vs_b0": float(b2["triple_worst_accuracy"]) >= float(b0["triple_worst_accuracy"]),
        "old_macro_budget": float(b2["old_macro_accuracy"]) >= float(b0["old_macro_accuracy"]) - 0.005,
        "batch_recursive_equivalence": equivalence,
        "independent_audit": truth,
    }
    balance = {
        "recent_triad_minimum": min(float(b2["class10_accuracy"]), float(b2["class11_accuracy"]), float(b2["class12_accuracy"])) >= 0.50,
        "pair_harmonic_strict_gain": float(b2["pair_harmonic_accuracy"]) > float(b0["pair_harmonic_accuracy"]),
        "triple_harmonic_strict_gain": float(b2["triple_harmonic_accuracy"]) > float(b0["triple_harmonic_accuracy"]),
        "overall_no_drop": float(b2["overall_accuracy"]) >= float(b0["overall_accuracy"]),
        "positive_fold_direction": sum(float(value) > 0.0 for value in deltas) >= 4,
    }
    return {
        "truth_passed": truth,
        "original_checks": original,
        "balance_checks": balance,
        "positive_fold_count": sum(float(value) > 0.0 for value in deltas),
        "passed": truth and all(original.values()) and all(balance.values()),
    }


def _risk(b0: Mapping[str, Any], b2: Mapping[str, Any]) -> dict[str, Any]:
    drops = [float(b0["per_class_accuracy"][label]) - float(b2["per_class_accuracy"][label]) for label in range(10)]
    classes = [label for label, drop in enumerate(drops) if drop > 0.02]
    return {"threshold": 0.02, "drops": drops, "classes": classes, "flagged": bool(classes), "changes_gate": False}


def _recompute(
    result_roots: Mapping[int, Path], audit_roots: Mapping[int, Path]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    if set(result_roots) != {2026, 2027, 2028} or set(audit_roots) != {2026, 2027, 2028}:
        raise ValueError("aggregate audit mismatch: seed roots")
    evidence = []
    bindings = {}
    for seed in (2026, 2027, 2028):
        result_root = Path(result_roots[seed])
        seed_audit_root = Path(audit_roots[seed])
        bindings[str(seed)] = {
            "result_manifest": _verify_tree(result_root),
            "audit_manifest": _verify_tree(seed_audit_root),
        }
        metrics = _read_json(result_root / "fold_metrics.json")
        folds = metrics.get("folds")
        aggregate = metrics.get("aggregate")
        if (
            not isinstance(folds, list)
            or len(folds) != 5
            or not isinstance(aggregate, dict)
            or not {"b0", "b2"}.issubset(aggregate)
            or (seed != 2026 and set(aggregate) != {"b0", "b2"})
            or any(
                not isinstance(row, dict)
                or not {"fold", "b0", "b2"}.issubset(row)
                or (seed != 2026 and set(row) != {"fold", "b0", "b2"})
                for row in folds
            )
        ):
            raise ValueError("aggregate audit mismatch: seed metrics")
        deltas = [float(row["b2"]["triple_harmonic_accuracy"]) - float(row["b0"]["triple_harmonic_accuracy"]) for row in folds]
        audit = _read_json(seed_audit_root / "audit_report.json")
        truth = audit.get("all_pass") is True and audit.get("access_flags_pass") is True
        equivalence = audit.get("b1_b2_equivalence_passed") is True
        checks = _checks(aggregate["b0"], aggregate["b2"], deltas, truth, equivalence)
        evidence.append(
            {
                "seed": seed,
                "passed": checks["passed"],
                "b0": aggregate["b0"],
                "b2": aggregate["b2"],
                "checks": checks,
                "fold_triple_h_deltas": deltas,
                "old_class_risk": _risk(aggregate["b0"], aggregate["b2"]),
            }
        )
    return evidence, bindings


def _summary(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    by_seed = {row["seed"]: row for row in evidence}
    descriptive = {}
    for metric in METRICS:
        values = {seed: float(by_seed[seed]["b2"][metric]) for seed in (2026, 2027, 2028)}
        ordered = list(values.values())
        worst = min(values, key=lambda seed: (values[seed], seed))
        descriptive[metric] = {
            "per_seed": {str(seed): values[seed] for seed in (2026, 2027, 2028)},
            "mean": mean(ordered),
            "sample_sd": stdev(ordered),
            "ddof": 1,
            "min": min(ordered),
            "max": max(ordered),
            "worst_seed": worst,
        }
    failed = [seed for seed in (2026, 2027, 2028) if not by_seed[seed]["passed"]]
    if not failed:
        classification = "three_seed_consistent"
    elif not by_seed[2027]["passed"] and not by_seed[2028]["passed"]:
        classification = "seed2026_local_only"
    else:
        classification = "seed_sensitive"
    return {
        "schema": "b2_class12_multiseed_summary_v1",
        "seed_order": [2026, 2027, 2028],
        "per_seed": {str(seed): dict(by_seed[seed]) for seed in (2026, 2027, 2028)},
        "descriptive": descriptive,
        "failed_seeds": failed,
        "all_seeds_passed": not failed,
        "classification": classification,
    }


def audit_b2_class12_multiseed(
    *,
    aggregate_root: Path,
    result_roots: Mapping[int, Path],
    audit_roots: Mapping[int, Path],
    seed2026_expected_result_manifest_sha256: str,
    seed2026_expected_audit_manifest_sha256: str,
    audit_root: Path,
    mode: str = "formal",
) -> dict[str, Any]:
    aggregate_root, audit_root = map(Path, (aggregate_root, audit_root))
    if audit_root.exists() or any(audit_root.parent.glob(audit_root.name + ".tmp.*")):
        raise FileExistsError("aggregate audit output conflict")
    if mode not in {"formal", "contract-test"}:
        raise ValueError("aggregate audit mismatch: mode")
    _verify_tree(aggregate_root, BUSINESS)
    evidence, bindings = _recompute(result_roots, audit_roots)
    if bindings["2026"]["result_manifest"] != seed2026_expected_result_manifest_sha256.lower() or bindings["2026"]["audit_manifest"] != seed2026_expected_audit_manifest_sha256.lower():
        raise ValueError("aggregate audit mismatch: seed2026 binding")
    expected_summary = _summary(evidence)
    if _read_json(aggregate_root / "multiseed_summary.json") != expected_summary:
        raise ValueError("aggregate audit mismatch: summary")
    seed2026 = evidence[0]
    expected_reuse = {
        "schema": "b2_class12_seed2026_recomputed_v1",
        "seed": 2026,
        "source_result_manifest_sha256": bindings["2026"]["result_manifest"],
        "source_audit_manifest_sha256": bindings["2026"]["audit_manifest"],
        "training_rerun": False,
        "capture_rerun": False,
        "diagnostic_369_rerun": False,
        "checks": seed2026["checks"],
        "old_class_risk": seed2026["old_class_risk"],
        "b2": seed2026["b2"],
    }
    if _read_json(aggregate_root / "seed2026_recomputed_for_multiseed.json") != expected_reuse:
        raise ValueError("aggregate audit mismatch: seed2026 reuse")
    expected_inputs = {"schema": "b2_class12_multiseed_input_sha256_v1", "mode": mode, "seed_bindings": bindings}
    if _read_json(aggregate_root / "input_sha256.json") != expected_inputs:
        raise ValueError("aggregate audit mismatch: input bindings")
    report = {
        "schema": "b2_class12_multiseed_audit_v1",
        "all_pass": True,
        "summary_exact": True,
        "seed2026_reuse_exact": True,
        "input_bindings_exact": True,
        "classification": expected_summary["classification"],
    }
    temporary = audit_root.with_name(audit_root.name + ".tmp." + uuid.uuid4().hex)
    audit_root.parent.mkdir(parents=True, exist_ok=True)
    temporary.mkdir()
    try:
        _write_json(temporary / "audit_report.json", report)
        _write_json(temporary / "artifact_sha256.json", {"audit_report.json": _sha256(temporary / "audit_report.json")})
        _write_json(
            temporary / "COMPLETE.json",
            {
                "schema": "b2_class12_multiseed_audit_complete_v1",
                "status": "complete",
                "artifact_manifest_sha256": _sha256(temporary / "artifact_sha256.json"),
            },
        )
        os.replace(temporary, audit_root)
    except Exception:
        if temporary.exists():
            for path in temporary.iterdir():
                path.unlink()
            temporary.rmdir()
        raise
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate-root", type=Path, required=True)
    for seed in (2026, 2027, 2028):
        parser.add_argument(f"--seed{seed}-result-root", type=Path, required=True)
        parser.add_argument(f"--seed{seed}-audit-root", type=Path, required=True)
    parser.add_argument("--seed2026-result-manifest-sha256", required=True)
    parser.add_argument("--seed2026-audit-manifest-sha256", required=True)
    parser.add_argument("--audit-root", type=Path, required=True)
    args = parser.parse_args()
    audit_b2_class12_multiseed(
        aggregate_root=args.aggregate_root,
        result_roots={seed: getattr(args, f"seed{seed}_result_root") for seed in (2026, 2027, 2028)},
        audit_roots={seed: getattr(args, f"seed{seed}_audit_root") for seed in (2026, 2027, 2028)},
        seed2026_expected_result_manifest_sha256=args.seed2026_result_manifest_sha256,
        seed2026_expected_audit_manifest_sha256=args.seed2026_audit_manifest_sha256,
        audit_root=args.audit_root,
    )
    print("B2_CLASS12_MULTISEED_AUDIT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
