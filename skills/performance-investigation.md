---
name: performance-investigation
description: Inspect an identified hot path and collect repeatable evidence.
trigger: [performance, latency, slow, allocation]
workflow: [measure-baseline, locate, patch, measure-after, regression-test, diff-review]
allowed_tools: [read_file, list_files, search_code, read_symbol, apply_patch, git_diff, git_status, run_tests, run_command_safe]
verification: [repository, unit, diff]
---
Requires a repository check and unit regression evidence. Timing claims must be supplied by a repeatable external benchmark; passing this skill alone does not prove speedup.
