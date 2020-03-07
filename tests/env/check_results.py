import json
from pathlib import Path


class ResultChecker:
    def __init__(self):
        self.tasks = 0
        self.changed = 0

    def check(self, filename: str, expected: dict, changed=True):
        self.tasks += 2
        self.changed += 2 if changed else 0

        data = json.load(open(f"results/{ filename }"))
        if isinstance(data, list):
            assert len(data) == 1
            data = data[0]
        for key, expected_value in expected.items():
            assert (
                expected_value == data[key]
            ), f"unexpected value '{data[key]}' for key '{key}' ({filename})"

    def check_statistic(self, outfile: str):
        output = Path(f"results/{outfile}").read_text()
        assert f"ok={self.tasks}" in output, self.tasks
        assert f"changed={self.changed}" in output, self.changed
        assert "failed=0" in output


checker = ResultChecker()
checker.check("pending.json", dict(ip="172.1.0.101"))
checker.check(
    "registration.json",
    dict(name="bamboo-agent", type="REMOTE", active=True, enabled=True),
)
checker.check("disabled.json", dict(enabled=False))
checker.check("changed_name.json", dict(name="new-name"))
checker.check(
    "current_state.json",
    dict(name="new-name", enabled=False, busy=False, active=True),
    changed=True,
)
checker.check("unchanged.json", dict(name="new-name", enabled=False), changed=False)
checker.check_statistic("ansible.out")
