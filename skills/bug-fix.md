---
name: bug-fix
description: Reproduce a defect and repair it with a bounded regression loop.
trigger: [bug, fix, regression, broken]
workflow: [reproduce, locate, patch, unit-test, regression-test, diff-review]
allowed_tools: [read_file, list_files, search_code, read_symbol, apply_patch, git_diff, git_status, run_tests, run_command_safe]
verification: [unit, diff]
require_reproduction: true
---
Read the failing evidence before editing. The runtime rejects patches until a test has been attempted, and prevents finish without a passing check and reviewed diff. Only an actual failed check qualifies as reproduction evidence in the trace.
