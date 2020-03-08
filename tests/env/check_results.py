import json
import unittest
from pathlib import Path
from functools import partial, wraps


def from_file(filename: str, changed=True, task=True):
    def decorator(fn):
        @wraps(fn)
        def wrapper(self):
            path = Path("results", filename)
            with open(str(path)) as f:
                content = json.load(f) if filename.endswith("json") else f.read()
            return fn(self, content)

        return wrapper

    return decorator


class TestResults(unittest.TestCase):
    @from_file("registration.json")
    def test_registration(self, registration):
        self.assertEqual(len(registration), 1)
        self.assertEqual(registration[0]["name"], "bamboo-agent")
        self.assertEqual(registration[0]["type"], "REMOTE")
        self.assertTrue(registration[0]["enabled"])
        self.assertTrue(registration[0]["active"])

    @from_file("disabled.json")
    def test_disabled(self, disabled):
        self.assertEqual(len(disabled), 1)
        self.assertFalse(disabled[0]["enabled"])

    @from_file("changed_name.json")
    def test_changed_name(self, changed_name):
        self.assertEqual(len(changed_name), 1)
        self.assertEqual(changed_name[0]["name"], "new-name")

    @from_file("current_state.json")
    def test_current_state(self, current_state):
        self.assertEqual(current_state["name"], "new-name")
        self.assertFalse(current_state["enabled"])
        self.assertTrue(current_state["active"])
        self.assertFalse(current_state["busy"])

    @from_file("unchanged.json")
    def test_unchanged(self, unchanged):
        self.assertEqual(len(unchanged), 1)
        self.assertEqual(unchanged[0]["name"], "new-name")
        self.assertFalse(unchanged[0]["enabled"])

    @from_file("ansible.logs", task=False)
    def test_statistic(self, ansible_log: str):
        self.assertIn("ok=12", ansible_log)
        self.assertIn("changed=10", ansible_log)
        self.assertIn("failed=0", ansible_log)


if __name__ == "__main__":
    unittest.main(verbosity=2)
