---
name: add-unit-test
description: Add a behavioral regression test without rewriting the implementation.
trigger: [test, coverage, assertion]
workflow: [locate, read-contract, add-test, unit-test, diff-review]
allowed_tools: [read_file, list_files, search_code, read_symbol, apply_patch, git_diff, git_status, run_tests]
verification: [unit, test-file, diff]
---
The verifier requires a changed test file and a passing test command. The permission set excludes general command execution.
