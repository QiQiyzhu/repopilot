---
name: capsule-repair
description: Repair one frozen development capsule with container-only test execution.
trigger: [capsule]
workflow: [reproduce, locate, patch, test, finish]
allowed_tools: [read_file, list_files, search_code, read_symbol, apply_patch, git_diff, git_status, run_tests]
verification: [unit, diff]
require_reproduction: true
---
Use run_tests with exactly ["python", "-m", "unittest", "-q", "test_visible"]. Only solution.py can be edited. Tests run in a restricted container. Independent runtime-withheld checks run after the actor terminates and cannot provide repair feedback. No shell or network tool is available. This skill is deliberately absent from the general trusted-host UI registry.
