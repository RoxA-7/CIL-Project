# Backup Manifest

日期：2026-07-18

## Local Backup

Before preparing this GitHub package, a full local backup of the current `cil_restart` directory was created:

```text
D:\Pro_Experiment\backups\cil_restart_before_github_push_20260718_001936.zip
```

This backup contains the full local working copy, including files that are intentionally not included in the GitHub package, such as temporary render outputs and caches.

## GitHub Package

The GitHub package is a curated, lightweight version intended for sharing and continued work.

Included:

- Source code under `cil_restart/src`.
- Scripts under `cil_restart/scripts`.
- Tests under `cil_restart/tests`.
- Configs under `cil_restart/configs`.
- Raw/tidy/table/figure/summary results.
- Teaching materials and generated PDF.
- Top-level deliverables for quick access.

Excluded:

- Paper PDFs.
- Official CLearning source checkout.
- Old VGG source checkout.
- Large feature cache.
- Temporary PDF render pages and QA images.
- Python and node dependency caches.

## Why This Split

The local backup preserves everything for recovery. The GitHub package preserves the project evidence and deliverables without committing avoidable large files, third-party sources, or copyrighted papers.

