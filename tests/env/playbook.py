import sys
import json
import unittest
import itertools
import functools
from pathlib import Path


class AcceptanceTest(unittest.TestCase):
    Tasks = []
    UnchangedTasks = 0

    IsTask = True
    CheckMode = False
    Arguments = dict()
    Query = None
    Changed = True

    def __init_subclass__(cls, **kwargs):
        def wrapper(self, fn, filename):
            path = Path("results", filename)
            return getattr(type(self), fn)(self, json.loads(path.read_text()))

        super().__init_subclass__(**kwargs)
        cls.Tasks.extend(cls.tasks())
        if not cls.Changed:
            AcceptanceTest.UnchangedTasks += 1

        if cls.Query:
            setattr(
                cls,
                "test_query",
                functools.partialmethod(
                    wrapper, fn="check_query", filename=f"{cls.__name__}.query.json"
                ),
            )

        setattr(
            cls,
            "test_value",
            functools.partialmethod(
                wrapper, fn="check_value", filename=f"{cls.__name__}.value.json"
            ),
        )

    @classmethod
    def tasks(cls):
        if cls.IsTask:
            yield {
                "name": f"run {cls.__name__}",
                "check_mode": "yes" if cls.CheckMode else "no",
                "stefanhoelzl.bamboo_agent.configuration": dict(
                    host="http://bamboo-server:8085",
                    home="/home/bamboo/bamboo-agent-home",
                    credentials=dict(user="admin", password="admin"),
                    **cls.Arguments,
                ),
                "register": cls.__name__,
            }
            yield dict(
                name=f"save {cls.__name__} value",
                copy=dict(
                    content=f"{{{{ {cls.__name__} | to_json }}}}",
                    dest=f"/results/{cls.__name__}.value.json",
                ),
            )
            if cls.Query:
                yield dict(
                    name=f"save { cls.__name__ } query",
                    uri=dict(
                        url=cls.Query,
                        method="GET",
                        force_basic_auth=True,
                        user="admin",
                        password="admin",
                        status_code=200,
                        dest=f"/results/{cls.__name__}.query.json",
                    ),
                )


class RegistrationCheckMode(AcceptanceTest):
    CheckMode = True
    Arguments = dict(timings=dict(http_timeout=60))
    Query = (
        "http://bamboo-server:8085/rest/api/latest/agent/authentication?pending=true"
    )

    def check_value(self, content):
        self.assertTrue(content["authenticated"])

    def check_query(self, content):
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["ip"], "172.1.0.101")


class Registration(AcceptanceTest):
    Query = "http://bamboo-server:8085/rest/api/latest/agent/"

    def check_value(self, content):
        self.assertTrue(content["authenticated"])
        self.assertEqual(content["assignments"], dict())
        self.assertEqual(content["name"], "bamboo-agent")
        self.assertTrue(content["enabled"])
        self.assertFalse(content["busy"])
        self.assertTrue(content["active"])
        self.assertFalse(content["deleted"])

    def check_query(self, content):
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["name"], "bamboo-agent")
        self.assertEqual(content[0]["type"], "REMOTE")
        self.assertTrue(content[0]["enabled"])
        self.assertFalse(content[0]["busy"])
        self.assertTrue(content[0]["active"])


class Disable(AcceptanceTest):
    Arguments = dict(enabled=False)
    Query = "http://bamboo-server:8085/rest/api/latest/agent/"

    def check_value(self, content):
        self.assertFalse(content["enabled"])

    def check_query(self, content):
        self.assertEqual(len(content), 1)
        self.assertFalse(content[0]["enabled"])


class SetName(AcceptanceTest):
    Arguments = dict(name="new-name")
    Query = "http://bamboo-server:8085/rest/api/latest/agent/"

    def check_value(self, content):
        self.assertEqual(content["name"], "new-name")

    def check_query(self, content):
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["name"], "new-name")


class Assignment(AcceptanceTest):
    Arguments = dict(assignments=[dict(type="project", key="DP")])

    def check_value(self, content):
        self.assertEqual(len(content["assignments"]), 1)


class NoChange(AcceptanceTest):
    Arguments = dict(
        name="new-name", enabled=False, assignments=[dict(type="project", key="DP")]
    )
    Changed = False
    Query = "http://bamboo-server:8085/rest/api/latest/agent/"
    AssignmentCount = 1

    def check_value(self, content):
        self.assertTrue(content["authenticated"])
        self.assertEqual(len(content["assignments"]), self.AssignmentCount)
        self.assertEqual(content["name"], "new-name")
        self.assertFalse(content["enabled"])
        self.assertFalse(content["deleted"])

    def check_query(self, content):
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["name"], "new-name")
        self.assertFalse(content[0]["enabled"])


class NoArguments(NoChange):
    Arguments = dict()
    AssignmentCount = 0


class DiffAndCheckMode(AcceptanceTest):
    CheckMode = True
    Arguments = dict(name="old-name", enabled=True, assignments=list(), deleted=True)
    Query = "http://bamboo-server:8085/rest/api/latest/agent/"

    def check_value(self, content):
        self.assertEqual(content["name"], "old-name")
        self.assertEqual(content["assignments"], dict())
        self.assertTrue(content["enabled"])
        self.assertTrue(content["deleted"])
        self.assertIn("diff", content)

    def check_query(self, content):
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["name"], "new-name")
        self.assertFalse(content[0]["enabled"])


class Delete(AcceptanceTest):
    Arguments = dict(deleted=True)
    Query = "http://bamboo-server:8085/rest/api/latest/agent/"

    def check_value(self, content):
        self.assertTrue(content["deleted"])

    def check_query(self, content):
        self.assertEqual(len(content), 0)


class TestAnsibleOutput(unittest.TestCase):
    def test_logs(self):
        logs = Path("results", "ansible.logs").read_text()
        self.assertIn(f"ok={1+len(AcceptanceTest.Tasks)}", logs)
        self.assertIn(
            f"changed={len(AcceptanceTest.Tasks) - AcceptanceTest.UnchangedTasks}", logs
        )
        self.assertIn("failed=0", logs)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        playbook = [
            dict(
                name="Automated tests against real bamboo server",
                hosts="bamboo-agent",
                tasks=AcceptanceTest.Tasks,
            )
        ]
        Path(sys.argv[1]).write_text(json.dumps(playbook, indent=2))
    else:
        unittest.main(verbosity=2)
