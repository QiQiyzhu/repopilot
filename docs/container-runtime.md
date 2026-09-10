# Actual container runtime acceptance

The built application passed its first real Docker Compose runtime acceptance in [Linux CI run 34445670524](https://github.com/QiQiyzhu/repopilot/actions/runs/34445670524), against commit `75759baf3686784a03613f01627a467c01605839`. The backend, frontend and containers jobs all passed. This adds runtime evidence to the earlier image-build checks; Docker was not installed on the Windows development host.

The CI runner starts the images from `compose.yaml`, waits for initial backend health, and uses the **published port 8080** for every application request. Python on the host runs only a standard-library HTTP probe. It does not import the application or execute its tests on the host in place of the container.

| Runtime check | Actual observed result |
|---|---|
| Nginx frontend | HTTP 200 HTML with the React mount and production JS reference; the referenced asset returns JavaScript rather than the SPA fallback |
| Reverse proxy / API | `/api/health` returns through Nginx and reports the image's `/workspace` root and demo repository |
| Task submission | HTTP 202 creates `d18ccdd0-bfb3-4889-ba3d-141988804f85` using the deterministic provider and actual MCP stdio transport |
| Tool execution | MCP reads the fixture, reproduces failed pytest, then passes pytest after the native patch; MCP diff succeeds |
| Independent verification | The explicitly submitted pytest acceptance command exits 0 with **3 passed**; file and diff contracts pass; `model_judge=false` |
| Patch | Only `calculator.py` changes, from `max(high, value)` to `min(high, value)` |
| HTTP observability | Task list, context and packaged skills respond; SSE emits trace and terminal events through Nginx |
| Backend restart | The same task remains succeeded with persisted verification and byte-identical diff after `docker compose restart backend` |
| Cleanup | Both containers, the CI network and the named workspace volume are removed; a shell EXIT trap and an always-run fallback perform cleanup |

The diff SHA-256 before and after restart is `77d7ae36a67aa01ef35dfc67ac4cc220a004174d3c10424f9ef5f577f3f3ffdb`. Startup probe time was 2,093.26 ms and the post-restart probe took 1,056.65 ms; these are single CI executions including HTTP polling, **not** performance benchmarks or LLM latency measurements.

The periodic Docker health indicator is `starting` in the final `compose-status.json` snapshot because the restarted backend had not reached its next scheduled healthcheck tick. The probe independently received `/api/health` HTTP 200 and reran the persisted-task checks before cleanup. Initial Compose startup did wait for the configured Docker healthcheck.

## Evidence

[Checked-in raw evidence](evidence/container-runtime/) contains the original task JSON before/after restart, both probe summaries with request headers and assertions, the patch, SSE events, frontend HTML, health response, Compose status and startup/restart/cleanup logs. These files were copied from the successful CI artifact without manufacturing or editing task outcomes. The artifact manifest records SHA-256 for every raw artifact file.

The run's `container-runtime-evidence` artifact additionally contains the fetched JavaScript bundle, request/poll details and other endpoint responses. Download all original files with:

```sh
gh run download 34445670524 --name container-runtime-evidence --dir outputs/container-runtime
```

## Reproduce with Docker available

From the repository root:

```sh
docker compose --project-name repopilot-check up --build --detach --wait
python scripts/container_smoke.py --output outputs/container-check
docker compose --project-name repopilot-check restart backend
python scripts/container_smoke.py --output outputs/container-check --resume
docker compose --project-name repopilot-check down --volumes --remove-orphans
```

Use a fresh, disposable Compose project for this acceptance flow; the cleanup command removes that project's demo workspace volume. CI implements cleanup in an EXIT trap even when a request or assertion fails.

The task uses the **known deterministic fixture** and explicitly trusts only that fixture's repository code. The evidence proves that the packaged services, MCP subprocess, mounted workspace, verification and proxy work together. It does not establish real-model coding accuracy, production scale, hardened multi-tenant isolation, or compatibility with every host platform.
