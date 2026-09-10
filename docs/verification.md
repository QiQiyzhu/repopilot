# Verification record

The checked-in [validation JSON](evidence/validation.json) is generated from actual pytest JUnit and Playwright reports. The latest backend suite has **57 passing cases and one explicitly skipped Windows symlink privilege test**. Four frontend request/metric unit tests and six real-backend browser workflows pass. Ruff, mypy, frontend typecheck/lint/build also pass.

The browser suite covers MCP execution, persisted task reload, diff, verifier, context, retry, memory invalidation, evaluation labels, missing-provider failure, mobile layout and approval/rejection/cancellation of a fixture deletion. The video and screenshots are captures of the running local application, not UI mockups. The updated diff preserves CRLF and changes only the repaired comparison.

The pinned ARC baseline independently passes 92 regression tests, typecheck and build. All 36 task contracts pass positive and negative controls; the six add-test reference cases also reject their intended mutation. The five-profile deterministic harness ablation uses one known fixture per profile and must not be read as an LLM success-rate comparison.

Dependency audit on the frontend reports zero known vulnerabilities at the recorded check. Vitest was moved to 4.1.11 after inspection of the [official advisory](https://github.com/advisories/GHSA-82fw-gwwq-j7x9). This does not guarantee that all dependencies are vulnerability-free.

Local runtime: Python 3.12.14, Node 24.16.0, Windows, Edge browser. Docker and the Node 22/Linux CI targets are configured but their runtime results depend on the first remote CI run; Docker is not installed on this development host. No paid provider call or production-usage claim is included.
