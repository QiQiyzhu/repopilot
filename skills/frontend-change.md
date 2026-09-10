---
name: frontend-change
description: Make a scoped UI change and verify its repository contracts.
trigger: [frontend, ui, react, layout]
workflow: [locate, patch, typecheck, unit-test, diff-review]
allowed_tools: [read_file, list_files, search_code, read_symbol, apply_patch, git_diff, git_status, run_tests, run_command_safe]
verification: [syntax, unit, diff]
---
A passing syntax/typecheck and a passing unit check are required. Visual inspection is a separate human check, never fabricated by this skill.
