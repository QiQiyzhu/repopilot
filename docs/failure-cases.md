# Ten reproduced failure cases

These are controlled fault injections and development failures, not invented production incidents. Each boundary below is executable in the backend tests.

| Failure | Observed behavior / repair | Reproduce |
|---|---|---|
| 1. Traversal `../outside.txt` | Router returns boundary error; no outside read | `test_path_boundary` |
| 2. `python -c` / destructive Git command | Allowlist denies arbitrary execution | `test_command_allowlist` |
| 3. Untrusted pytest request | Explicit trust requirement prevents execution | `test_tests_require_trust` |
| 4. Command never exits | Timeout terminates process tree | `test_timeout_kills_process` |
| 5. Noisy child emits 200 KB | Output drained; retained bytes capped and truncation marked | `test_output_limit_drains_noisy_child` |
| 6. Model finishes without fixing code | Verifier rejects; repair bounded; no trusted memory written | `test_repair_is_bounded_after_verifier_rejects` |
| 7. Context / token budget too small | Task fails explicitly before an unbounded request | `test_context_overflow` |
| 8. Real provider has no key | Explicit provider failure, zero model steps, no fake fallback | `test_missing_real_key_fails_explicitly` |
| 9. Deletion requested without approval | File remains until explicit decision; rejection preserves it | `test_approval_gate_waits_for_explicit_decision` |
| 10. MCP server's child inherited protocol stdin | Initial real MCP demo timed out in pytest; setting child stdin to DEVNULL fixed it | `test_mcp_end_to_end_uses_real_stdio_transport` |

Additional coverage checks retries after transient provider errors, malformed action JSON, token accounting, native/MCP parity, replay exhaustion, atomic patch matching, memory invalidation, scope isolation and cancellation.

One Windows symlink-creation test is skipped when the host lacks that privilege; Linux CI executes that test. No test skip is silently presented as a pass. Browser tests also exercise approve, reject and cancel paths against the actual backend and show missing-provider failure explicitly.
