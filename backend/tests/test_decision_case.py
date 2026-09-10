import sys

from repopilot.decision_case import decide
from repopilot.evaluation import contract_rejected
from repopilot.security import run_process


def test_mutation_acceptance_requires_the_intended_assertion_not_a_process_failure():
    green = {"passed": True, "exit_code": 0, "output": "one candidate test executed"}
    assert not decide(green, green)["accepted"]
    assert not decide(green, {"passed": False, "exit_code": None, "output": ""})["accepted"]
    assert not decide(green, {"passed": False, "exit_code": 1, "output": "SyntaxError"})["accepted"]
    killed = {"passed": False, "exit_code": 1, "output": "7 !== 5"}
    assert decide(green, killed)["accepted"]
    assert not decide({"passed": False}, killed)["accepted"]


async def test_real_process_timeout_is_not_a_successful_negative_control(tmp_path):
    result = await run_process(
        [sys.executable, "-c", "import time; time.sleep(2)"], tmp_path, timeout=0.05
    )
    assert result.error == "command_timeout" and result.exit_code is None
    assert not contract_rejected({"passed": result.ok, "exit_code": result.exit_code})
    assert not contract_rejected({"passed": False, "exit_code": 137})
    assert contract_rejected({"passed": False, "exit_code": 1})
