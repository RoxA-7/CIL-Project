# Reproducibility Notes

## Environment Observed

From `cil_restart/results/summary/official_environment.json`:

- OS: Windows 11
- Python: 3.12.2
- GPU: NVIDIA GeForce RTX 4060 Laptop GPU
- torch: 2.5.1+cu121
- torchvision: 0.20.1+cu121
- yaml: 6.0.2
- tensorboard: 2.16.2
- scipy: 1.12.0
- sklearn: 1.4.1.post1
- continuum: missing

The official reproduction workflow is therefore not ready until `continuum` compatibility is resolved.

## Commands

Run from `cil_restart/`.

```powershell
python -m pytest
```

```powershell
python scripts/build_results.py
```

```powershell
python scripts/check_official.py
```

```powershell
python scripts/run_official.py --method podnet --seed 1993
```

## Data And Result Rules

- `results/raw/` is the source of truth.
- `results/tidy/` is generated from raw logs.
- `results/tables/` and `results/figures/` are generated artifacts.
- Final table values must not be manually edited.
- Test accuracy must not be used to select checkpoints.

## Formal Result Gate

Do not fill the standard method table until:

1. Official environment check is ready.
2. A short smoke run passes.
3. PODNet and MTD-PODNet single-seed results are close to the paper within the planned tolerance.
4. Main methods have all required seeds.

