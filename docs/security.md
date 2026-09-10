# Threat model and safety boundary

## Intended use

A single developer runs this lab locally against repositories they trust. The model, repository text and tool arguments may be mistaken. Hostile repository code and hostile remote tenants are outside the host runner's security boundary. The API must not be exposed publicly.

| Threat | Implemented control | Residual limit |
|---|---|---|
| Path traversal / alternate streams | Relative path normalization, resolved-root checks, symlink rejection, protected components | No kernel-level filesystem isolation; filesystem races are not eliminated |
| Secret inclusion | .env exclusion, dependency/secret directory filtering, leaf redaction, child environment allowlist | Regex redaction is not comprehensive secret detection |
| Shell injection | Argument arrays, no shell, strict executable/argument allowlist | Allowed pytest/npm scripts execute trusted repository code |
| Child consuming MCP protocol stdin | Every execution child gets DEVNULL stdin | MCP process itself owns its protocol stream |
| Runaway command | Timeout, bounded incremental stdout draining, process-tree termination | Detached/hostile processes require stronger OS controls |
| Destructive file deletion | Task pauses for explicit approval; rejection/cancellation leaves file intact | Approval scope covers one workspace-relative deletion |
| Source corruption | Committed git archive materialized into a fresh workspace | Uncommitted source changes are excluded by design |
| Unreviewed output | Actual tracked and new-file diff; executable verifier | Human review still needed before merging candidate code |
| Prompt injection | Untrusted-content instruction plus runtime tool/skill permissions | Model decisions are not intrinsically trustworthy |
| Cross-origin requests | Local UI origin allowlist, optional bearer token | Not a complete production authentication/authorization system |
| Stale memory | Exact repository + commit scope, provenance, invalidation | Conservative scope may reduce useful recall |

`run_command_safe` is a policy boundary, **not a sandbox**. Checking `python -m pytest` does not stop that test from opening arbitrary files or making network requests. The UI therefore asks whether the repository test code is trusted. CLI uses `--trust-code`; API uses `allow_repository_code`.

Compose runs the backend as UID 10001, read-only root filesystem, dropped capabilities, no-new-privileges, PID/memory limits and a dedicated writable workspace volume. It is still a shared local service rather than per-task hostile-code isolation. A future remote system should use a fresh network-restricted container/VM per job, read-only acceptance mounts, authenticated ownership checks, secret brokers, resource quotas and audited approval identity.

No provider keys are included in CI. Keys are read only from the service environment and are never forwarded to repository subprocesses. OPENAI_BASE_URL requires HTTPS or explicit localhost. Real-provider failure is visible; FakeModelProvider is never selected implicitly.

## Operational limitations

Task workspaces are retained for review and have no automatic garbage collection. Operators should remove reviewed `.repopilot` data using normal filesystem controls when the service is stopped. Retention policy, database migration tooling, remote tenancy and hard provider-side spend reservations are deliberately outside this portfolio's implemented scope.
