import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from repopilot.evaluation import ROOT
from repopilot.security import run_process, validate_command
from repopilot.workspace import GitWorkspace
from run_model_benchmark import npm_command


async def main(repository: Path):
    data = ROOT / ".repopilot/baseline"
    manifest = json.loads((ROOT / "evaluation/tasks/arc-shift.json").read_text())
    factory = GitWorkspace(data, repository.resolve().parent)
    workspace, sha = await factory.create(
        str(repository.resolve()), manifest["repository_commit"], str(uuid4())
    )
    root = Path(workspace)
    checks = []
    setup = await run_process(
        npm_command(["ci", "--ignore-scripts", "--no-audit", "--no-fund"]), root, timeout=300
    )
    checks.append({"name": "dependency-install", **setup.model_dump()})
    if setup.ok:
        for name in ["test", "typecheck", "build"]:
            result = await run_process(
                validate_command(["npm", "run", name], root, True), root, timeout=180
            )
            checks.append({"name": name, **result.model_dump()})
            print(
                json.dumps({"name": name, "ok": result.ok, "exit_code": result.exit_code}),
                flush=True,
            )
    report = {
        "id": "arc-pinned-baseline",
        "title": "Pinned ARC//SHIFT regression baseline",
        "evidence_type": "real-repository-checks",
        "is_model_benchmark": False,
        "repository_commit": sha,
        "passed": all(c["ok"] for c in checks),
        "checks": checks,
        "note": "Tests/build execute only in a fresh archive of the pinned commit, not the user's working tree. This validates the evaluation baseline, not a model-generated patch.",
    }
    (ROOT / "evaluation/results/arc-pinned-baseline.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    asyncio.run(main(parser.parse_args().repository))
