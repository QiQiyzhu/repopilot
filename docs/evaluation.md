# Evaluation methodology

The benchmark target is ARC//SHIFT commit `b17f4c24cf95a02d3197ec493026b6f23c8f2c3e`. Each task includes ID, natural-language description, immutable ref, category, difficulty, required files and independent executable acceptance. The 36 tasks are human-designed contract exercises derived from actual source and test behavior. They are not represented as historical production bugs.

| Category | Count | Discriminating check |
|---|---:|---|
| Bug Fix | 16 | Planted incorrect implementation fails; reference repair passes |
| Add Test | 6 | Missing test fails; reference test passes; altered implementation is rejected |
| Small Feature | 6 | Missing export fails; specified endpoints/edge cases pass |
| Refactor | 4 | Exported constant and implementation linkage preserve behavior |
| Performance | 2 | Equivalent boundary behavior and elimination of a selected square root |
| Documentation + Code Consistency | 2 | Machine-readable documentation equals runtime catalog exports |

Every task passed its positive and negative control in the checked-in [contract report](../evaluation/results/arc-contract-validation.json). Performance tasks do not establish a measured speedup. The pure TypeScript loader transpiles candidate modules and executes Node assertions from outside the workspace. It is an independent evaluator, not an OS sandbox; hostile candidates could attack a host process and must not be evaluated in host mode.

The [pinned baseline report](../evaluation/results/arc-pinned-baseline.json) records npm dependency installation, 92 regression tests, typecheck and production build in a fresh archived checkout. It does not run in the user's active ARC source tree.

## Ablations

`PROFILES` defines single-shot, tools, verifier, structured context, and full memory/skills configurations. The deterministic fixture experiment ran all five through the same external pytest acceptance. It records success, steps, latency, token usage, errors, repairs and selected memory chunks. All five pass because each was given a known script. The no-verifier harness status is UNVERIFIED even when the external evaluator later accepts its patch.

The real-provider runner is `scripts/run_model_benchmark.py`. It materializes task setup without exposing reference repairs to the provider, installs candidate dependencies as an explicit operator step, runs the chosen harness profile, then executes sealed acceptance, mutation adequacy when relevant, regression, typecheck and build. Incremental results survive interruption. It requires configured model/key and `--confirm-paid-api`; CI never calls it.

All real-model ablation cells are **not_run / null**, not zero-percent failures and not copied fixture scores. No provider cost or task-solving improvement is fabricated. The real runner's first memory task is cold; because scope is exact commit, some later tasks will also have no applicable prior lesson. This limitation must be reported in a real experiment.

## Interpretation and next experiment

The sample emphasizes small pure-function contracts and is easier than arbitrary repository maintenance. It does not measure broad SWE-bench performance. Reference implementations and tasks should be reviewed by another engineer before a hiring interview. A useful next experiment is one pinned model, fixed per-task budgets, all profiles on all tasks, recorded repetitions/seeds, held-out acceptance and confidence intervals. Report regressions and non-improvements rather than changing tasks after seeing results.
