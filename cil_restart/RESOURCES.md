# Resources

## Knowledge

- `../00_Learning_without_Forgetting.pdf`
  - Use for LwF motivation, teacher-student output distillation, and the difference between the original setting and this project's single-head CIL setting.
- `../01_Class_Incremental_Learning_with_Multi-Teacher_Distillation.pdf`
  - Use for true MTD: teacher construction, multi-teacher aggregation, diversity assumptions, and reported protocol.
- `../02_Continual_Learning_With_Knowledge_Distillation_A_Survey.pdf`
  - Use as a method map for continual learning with distillation. Do not use survey rankings as direct evidence for this project.
- PyTorch official docs: `CrossEntropyLoss`, `Softmax`, and autograd notes.
  - Use for CE definition, logits convention, and gradient/backpropagation behavior.
- Torchvision official CIFAR-100 docs.
  - Use for raw CIFAR-100 dataset assumptions and avoiding unnecessary JPEG conversion or 224x224 resizing.
- Official CLearning repository fixed locally at commit `ce0789a40bda9e566a1e0432d3ac320937ca48f0`.
  - Use for B50-5S reproduction configs and official MTD/SS-IL baselines.

## Project Evidence

- `../增量学习交接文档.docx`
  - Use for old project timeline, reported phenomena, code paths, and suspected implementation problems.
- `../增量学习代码/VGG16_CIL/train_CIL12.py`
  - Use only as a fault-case source for classifier expansion, CE/KD loss, and new-class-only training behavior.
- `../增量学习代码/VGG16_CIL/train_CIL12_10p11.py`
  - Use only as a fault-case source for double-teacher logic and gradient-path checks.
- `results/raw/`
  - Source of truth for generated numbers. Final tables and figures must trace back here.
- `results/tidy/`
  - Clean statistical input generated from raw logs.
- `results/tables/` and `results/figures/`
  - Presentation artifacts generated from tidy data; numbers must not be manually edited.
- `output/pdf/CIL类增量学习完整课程讲义.pdf`
  - Current self-study course artifact for zero-background onboarding.

## Lessons And Reference

- `lessons/0001_loss_and_bias.html`
  - Short lesson on CE, KD, and common logit shifts.
- `lessons/0002_cil_protocol_metrics.html`
  - Short lesson on CIL protocol and metrics.
- `lessons/0003_mtd.html`
  - Short lesson on true MTD versus historical checkpoints.
- `lessons/0004_tables_and_figures.html`
  - Short lesson on three-line tables and chart reading.
- `reference/glossary.html`
  - Quick terminology reference.
- `QUIZ.md`
  - Self-check questions.

## Wisdom

- Group meeting feedback is treated as a constraint: old VGG results are not reliable formal results, but they are useful as a diagnosed failure case.
- A result is not presentation-ready unless it has protocol, seed, raw log, tidy row, generated table/figure, and a stated evidence boundary.
- Formal B50-5S results are not complete while the official dependency stack remains blocked; do not fill missing numbers.

## Gaps

- Resolve `continuum==1.2.4` / Python 3.12 compatibility or run official CLearning in a compatible environment.
- Complete PODNet, MTD-PODNet, SS-IL, and MTD-SSIL for seeds 1993, 1994, 1995.
- Verify PODNet and MTD-PODNet AIA against the paper within the planned 2 percentage point tolerance before extending research claims.
- Add learning records only after the learner demonstrates a durable concept, such as explaining CE/KD replacement without looking.
