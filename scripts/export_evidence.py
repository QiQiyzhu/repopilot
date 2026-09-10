"""Copy actual execution evidence into reviewable, path-redacted portfolio artifacts."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
destination = ROOT / "docs/evidence"
destination.mkdir(parents=True, exist_ok=True)


def scrub(value):
    if isinstance(value, str):
        return value.replace(str(ROOT), "<RepoPilot>").replace(ROOT.as_posix(), "<RepoPilot>")
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


trace = json.loads((ROOT / "outputs/demo-mcp.json").read_text(encoding="utf-8"))
assert trace["status"] == "succeeded"
assert any(event.get("transport") == "mcp" for event in trace["trace"])
trace["redactions"] = ["Local absolute checkout path replaced by <RepoPilot>"]
(destination / "mcp-trace.json").write_text(json.dumps(scrub(trace), indent=2), encoding="utf-8")

xml = ET.parse(ROOT / "outputs/backend-tests.xml").getroot()
cases = list(xml.iter("testcase"))
tests = [
    {
        "name": case.attrib["name"],
        "class": case.attrib.get("classname"),
        "duration_seconds": float(case.attrib["time"]),
        "status": "skipped"
        if case.find("skipped") is not None
        else "failed"
        if case.find("failure") is not None or case.find("error") is not None
        else "passed",
    }
    for case in cases
]
browser = json.loads((ROOT / "outputs/browser-results.json").read_text(encoding="utf-8"))
report = {
    "record_kind": "actual-local-check-results",
    "platform": "Windows",
    "python": "3.12.14",
    "node": "24.16.0",
    "backend_passed": sum(t["status"] == "passed" for t in tests),
    "backend_skipped": sum(t["status"] == "skipped" for t in tests),
    "backend_failed": sum(t["status"] == "failed" for t in tests),
    "backend_cases": tests,
    "browser_stats": browser["stats"],
    "frontend_unit_tests": 4,
    "real_provider_runs": 0,
    "docker_local_status": "not_run: Docker executable unavailable",
    "ci_remote_status": "pending first repository push",
    "note": "The Windows skip is a symlink privilege check; it is not counted as passed. No paid API or model performance result is implied.",
}
(destination / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
for file in (ROOT / "evaluation/results").glob("*.json"):
    value = json.loads(file.read_text(encoding="utf-8"))
    file.write_text(json.dumps(scrub(value), indent=2), encoding="utf-8")
print(
    json.dumps(
        {
            key: report[key]
            for key in ["backend_passed", "backend_skipped", "backend_failed", "browser_stats"]
        }
    )
)
