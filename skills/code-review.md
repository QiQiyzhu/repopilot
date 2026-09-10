---
name: code-review
description: Read-only review with traceable file references.
trigger: [review, audit, explain]
workflow: [read-contract, inspect-diff, search-callers, evidence-review]
allowed_tools: [read_file, list_files, search_code, read_symbol, git_diff, git_status]
verification: [no-write, diff]
---
The router denies edits and commands. Findings are decision summaries with source references, not hidden reasoning.
