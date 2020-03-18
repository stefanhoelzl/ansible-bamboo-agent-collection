import sys
import json
import textwrap
import threading
import subprocess
from pathlib import Path
from functools import partialmethod
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from typing import List, Optional
from http.server import HTTPServer, BaseHTTPRequestHandler

from . import templates
from plugins.modules.configuration import Method, Request, Response
from tests import IpAddress, RequestTestCase, BambooHome, ActionResponse


class HttpRequestHandler(BaseHTTPRequestHandler):
    Responses: List[Response] = list()
    Requests: List[Request] = list()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for method in Method.__members__.values():
            setattr(cls, f"do_{method}", partialmethod(cls.do, method=method))

    def do(self, method: Method):
        content_length = int(self.headers.get("Content-Length", 0))
        self.Requests.append(
            Request(self.path, content=self.rfile.read(content_length), method=method,)
        )

        response = self.Responses.pop(0)
        response()
        self.send_response(response.status_code)
        for header, value in (response.header or {}).items():
            self.send_header(header, value)
        self.end_headers()
        self.wfile.write(bytes(response))

    def log_request(self, code="-", size="-"):
        pass


class RequestHandler(HttpRequestHandler):
    Responses = []
    Requests = []


class HttpServerMock:
    def __init__(self):
        self.url = "http://localhost:7000"
        threading.Thread(
            target=HTTPServer(("localhost", 7000), RequestHandler).serve_forever,
            daemon=True,
        ).start()

    @property
    def requests(self):
        return RequestHandler.Requests

    def reset(self, responses):
        RequestHandler.Responses = responses
        RequestHandler.Requests = []
        return RequestHandler.Requests


class BambooAgentIntegrationTest(RequestTestCase):
    Home = BambooHome()
    Arguments = dict(credentials=dict(user="", password=""))
    Responses: List[Response] = list()
    ExpectedRequests: List[Request] = list()
    ExpectedResult = dict()
    ExpectChange = False
    ExpectFailure = False
    CheckMode = False

    _HttpServer = HttpServerMock()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        setattr(cls, f"test_{cls.__name__}", cls._test)

    def _test(self):
        result, requests = self._execute_module_in_process()
        del result["invocation"]

        self.assert_requests(requests, *self.ExpectedRequests)
        if self.ExpectFailure:
            self.assertTrue(result["failed"])
        else:
            self.assertEqual(result.pop("changed"), self.ExpectChange)
        for key, expected in self.ExpectedResult.items():
            self.assertEqual(result[key], expected, key)

    def _execute_module_in_process(self):
        with TemporaryDirectory() as tempdir:
            self._HttpServer.reset(self.Responses)
            arguments_file_path = Path(tempdir, "arguments.json")
            with open(arguments_file_path, mode="w+") as arguments_file:
                arguments = {
                    **BambooAgentIntegrationTest.Arguments,
                    **self.Arguments,
                }
                arguments.setdefault("timings", {}).setdefault("http_timeout", 1)
                json.dump(
                    dict(
                        ANSIBLE_MODULE_ARGS=dict(
                            host=self._HttpServer.url,
                            home=str(self.Home.create(tempdir)),
                            _ansible_check_mode=self.CheckMode,
                            **arguments,
                        ),
                    ),
                    arguments_file,
                )

            process = subprocess.run(
                [
                    sys.executable,
                    "plugins/modules/configuration.py",
                    str(arguments_file_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        if process.returncode and not self.ExpectFailure:
            error_msg = "\n".join(
                [
                    f"RETURN_CODE: {process.returncode}",
                    "STDOUT:",
                    textwrap.indent(process.stdout.decode("utf-8"), prefix="  "),
                    "STDERR:",
                    textwrap.indent(process.stderr.decode("utf-8"), prefix="  "),
                ]
            )
            raise RuntimeError(error_msg)
        return json.loads(process.stdout), self._HttpServer.requests


class TestNewAgentRegistration(BambooAgentIntegrationTest):
    Uuid = "00000000-1111-2222-3333-444444444444"
    Home = BambooHome().temp_uuid(Uuid)
    ExpectChange = True
    ExpectedRequests = [
        templates.Pending.request(),
        templates.Authentication.request(uuid=Uuid),
        templates.Agents.request(),
    ]
    Responses = [
        templates.Pending.response(uuid=Uuid),
        templates.Authentication.response().action(
            lambda: BambooHome()
            .config(aid=1234)
            .create(TestNewAgentRegistration.Home.path)
        ),
        templates.Agents.response([dict(id=1234, enabled=True)]),
    ]
    ExpectedResult = dict(id=1234, enabled=True, authenticated=True)


class TestNewAgentWithCheckMode(BambooAgentIntegrationTest):
    Uuid = "00000000-1111-2222-3333-444444444444"
    Home = BambooHome().temp_uuid(Uuid)
    CheckMode = True
    ExpectChange = True
    ExpectedRequests = [
        templates.Pending.request(),
    ]
    Responses = [
        templates.Pending.response(uuid=Uuid),
    ]
    ExpectedResult = dict(authenticated=True)


class TestErrorHandling(BambooAgentIntegrationTest):
    Uuid = "00000000-1111-2222-3333-444444444444"
    Home = BambooHome().temp_uuid(Uuid)
    ExpectFailure = True
    ExpectedRequests = [templates.Pending.request()]
    Responses = [ActionResponse(status_code=400)]


class TestHttpTimeout(BambooAgentIntegrationTest):
    Uuid = "00000000-1111-2222-3333-444444444444"
    Arguments = dict(timings=dict(http_timeout=0))
    Home = BambooHome().temp_uuid(Uuid)
    ExpectFailure = True


class TestUnchanged(BambooAgentIntegrationTest):
    Arguments = dict(
        enabled=True, name="agent-name", assignments=[dict(type="plan", key="PL")]
    )
    Home = BambooHome().config(aid=1234)
    ExpectChange = False
    ExpectedRequests = [
        templates.Pending.request(),
        templates.Agents.request(),
        templates.SearchAssignment.request(etype="PLAN"),
        templates.Assignments.request(agent_id=1234),
    ]
    Responses = [
        ActionResponse([]),
        templates.Agents.response([dict(id=1234, enabled=True, name="agent-name")]),
        templates.SearchAssignment.response([dict(key="PL", id=1)]),
        templates.Assignments.response([dict(executableType="PLAN", executableId=1)]),
    ]
    ExpectedResult = dict(id=1234, name="agent-name", enabled=True)


class TestCheckMode(BambooAgentIntegrationTest):
    Arguments = dict(
        enabled=True, name="new-name", assignments=[dict(type="plan", key="PL")],
    )
    CheckMode = True
    Home = BambooHome().config(aid=1234)
    ExpectChange = True
    ExpectedRequests = [
        templates.Pending.request(),
        templates.Agents.request(),
        templates.SearchAssignment.request(etype="PLAN"),
        templates.Assignments.request(agent_id=1234),
    ]
    Responses = [
        ActionResponse([]),
        templates.Agents.response([dict(id=1234, enabled=False, name="old-name")]),
        templates.SearchAssignment.response([dict(key="PL", id=1)]),
        templates.Assignments.response(
            [dict(executableType="PROJECT", executableId=2)]
        ),
    ]
    ExpectedResult = dict(id=1234, enabled=True, name="new-name")


class TestAgentDisable(BambooAgentIntegrationTest):
    Arguments = dict(enabled=False)
    Home = BambooHome().config(aid=1234)
    ExpectChange = True
    ExpectedRequests = [
        templates.Pending.request(),
        templates.Agents.request(),
        templates.Disable.request(agent_id=1234),
    ]
    Responses = [
        ActionResponse([]),
        templates.Agents.response([dict(id=1234, enabled=True)]),
        templates.Disable.response(),
    ]
    ExpectedResult = dict(id=1234, enabled=False)


class TestSetAgentName(BambooAgentIntegrationTest):
    Arguments = dict(name="new-name")
    Home = BambooHome().config(aid=1234)
    ExpectChange = True
    ExpectedRequests = [
        templates.Pending.request(),
        templates.Agents.request(),
        templates.SetName.request(agent_id=1234, name="new-name"),
    ]
    Responses = [
        ActionResponse([]),
        templates.Agents.response([dict(id=1234, name="old-name")]),
        templates.SetName.response(),
    ]
    ExpectedResult = dict(id=1234, name="new-name")


class TestAssignments(BambooAgentIntegrationTest):
    Arguments = dict(
        assignments=[dict(type="plan", key="PL"), dict(type="project", key="PR")]
    )
    Home = BambooHome().config(aid=1234)
    ExpectChange = True
    ExpectedRequests = [
        templates.Pending.request(),
        templates.Agents.request(),
        templates.SearchAssignment.request(etype="PLAN"),
        templates.SearchAssignment.request(etype="PROJECT"),
        templates.Assignments.request(agent_id=1234),
        templates.AddAssignment.request(agent_id=1234, etype="PROJECT", eid=1),
        templates.RemoveAssignment.request(agent_id=1234, etype="PROJECT", eid=2),
    ]
    Responses = [
        ActionResponse([]),
        templates.Agents.response([dict(id=1234)]),
        templates.SearchAssignment.response([dict(key="PL", id=0)]),
        templates.SearchAssignment.response([dict(key="PR", id=1)]),
        templates.Assignments.response(
            [
                dict(executableType="PROJECT", executableId=2),
                dict(executableType="PLAN", executableId=0),
            ]
        ),
        templates.AddAssignment.response(),
        templates.RemoveAssignment.response(),
    ]
    ExpectedResult = dict(assignments={"0": "PLAN", "1": "PROJECT"})


class TestBlockWhileBusy(BambooAgentIntegrationTest):
    Home = BambooHome().config(aid=1234)
    Arguments = dict(block_while_busy=True, timings=dict(interval_busy_polling=0))
    ExpectChange = True
    ExpectedRequests = [
        templates.Pending.request(),
        templates.Agents.request(),
        templates.Agents.request(),
    ]
    Responses = [
        ActionResponse([]),
        templates.Agents.response([dict(id=1234, busy=True)]),
        templates.Agents.response([dict(id=1234, busy=False)]),
    ]
    ExpectedResult = dict(id=1234, busy=False)


class TestReturnValues(BambooAgentIntegrationTest):
    Home = BambooHome().config(aid=1234)
    ExpectedRequests = [
        templates.Pending.request(),
        templates.Agents.request(),
    ]
    Responses = [
        ActionResponse([]),
        templates.Agents.response(
            [dict(id=1234, name="agent-name", enabled=True, busy=False, active=True)]
        ),
    ]
    ExpectedResult = dict(
        id=1234, name="agent-name", enabled=True, busy=False, active=True
    )


class TestDiff(BambooAgentIntegrationTest):
    Home = BambooHome().config(aid=1234)
    ExpectedRequests = [
        templates.Pending.request(),
        templates.Agents.request(),
    ]
    Responses = [
        ActionResponse([]),
        templates.Agents.response(
            [dict(id=1234, name="agent-name", enabled=True, busy=False, active=True)]
        ),
    ]
    ExpectedResult = dict(
        diff=dict(
            before=textwrap.dedent(
                """
                {
                    "assignments": {},
                    "authenticated": true,
                    "info": {
                        "active": true,
                        "busy": false,
                        "enabled": true,
                        "id": 1234,
                        "name": "agent-name"
                    }
                }
                """
            ).strip(),
            after=textwrap.dedent(
                """
                {
                    "assignments": {},
                    "authenticated": true,
                    "info": {
                        "active": true,
                        "busy": false,
                        "enabled": true,
                        "id": 1234,
                        "name": "agent-name"
                    }
                }
                """
            ).strip(),
        )
    )
