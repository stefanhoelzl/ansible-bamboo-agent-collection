import json
from pathlib import Path


class ResultChecker:
    def __init__(self):
        self.tasks = 0
        self.changed = 0

    def check(self, filename: str, expected: dict, changed=True, after_task=True):
        self.tasks += 2 if after_task else 1
        self.changed += 1 if after_task else 0
        self.changed += 1 if changed else 0

        data = json.load(open(f"results/{ filename }"))
        assert len(data) == 1
        for key, expected_value in expected.items():
            assert (
                expected_value == data[0][key]
            ), f"unexpected value '{data[0][key]}' for key '{key}' ({filename})"

    def check_statistic(self, outfile: str):
        output = Path(f"results/{outfile}").read_text()
        assert f"ok={self.tasks + 1}" in output, self.tasks
        assert f"changed={self.changed}" in output, self.changed


checker = ResultChecker()
checker.check("pending.json", dict(ip="172.1.0.101"), after_task=False)
checker.check(
    "registration.json",
    dict(name="bamboo-agent", type="REMOTE", active=True, enabled=True),
)
checker.check("disabled.json", dict(enabled=False))
checker.check("changed_name.json", dict(name="new-name"))
checker.check_statistic("ansible.out")
