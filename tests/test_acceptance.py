import sys
import json
import threading
import subprocess
from pathlib import Path
from functools import partialmethod
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from typing import List, Optional
from proxy import Request, Response, Method
from http.server import HTTPServer, BaseHTTPRequestHandler

from . import templates
from .proxy import Method, Request, Response
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


class BambooAgentAcceptanceTest(RequestTestCase):
    Home = BambooHome()
    Arguments = dict(authentication=dict(user="", password=""))
    Responses: List[Response] = list()
    ExpectedRequests: List[Request] = list()
    ExpectedResult = dict()
    ExpectChange = False
    ExpectFailure = False

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
            self.assertEqual(result, self.ExpectedResult)

    def _execute_module_in_process(self):
        with TemporaryDirectory() as tempdir:
            self._HttpServer.reset(self.Responses)
            arguments_file_path = Path(tempdir, "arguments.json")
            with open(arguments_file_path, mode="w+") as arguments_file:
                arguments = {
                    **BambooAgentAcceptanceTest.Arguments,
                    **self.Arguments,
                }
                json.dump(
                    dict(
                        ANSIBLE_MODULE_ARGS=dict(
                            host=self._HttpServer.url,
                            home=str(self.Home.create(tempdir)),
                            **arguments,
                        )
                    ),
                    arguments_file,
                )

            process = subprocess.run(
                [
                    sys.executable,
                    "bamboo-agent-configuration.py",
                    str(arguments_file_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        if process.returncode and not self.ExpectFailure:
            raise RuntimeError(process.returncode, process.stdout, process.stderr)
        return json.loads(process.stdout), self._HttpServer.requests


class TestNewAgentRegistration(BambooAgentAcceptanceTest):
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


class TestErrorHandling(BambooAgentAcceptanceTest):
    Uuid = "00000000-1111-2222-3333-444444444444"
    Home = BambooHome().temp_uuid(Uuid)
    ExpectFailure = True
    ExpectedRequests = [
        templates.Pending.request(),
    ]
    Responses = [
        ActionResponse(status_code=400),
    ]


class TestUnchanged(BambooAgentAcceptanceTest):
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


class TestAgentDisable(BambooAgentAcceptanceTest):
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


class TestSetAgentName(BambooAgentAcceptanceTest):
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


class TestAssignments(BambooAgentAcceptanceTest):
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

