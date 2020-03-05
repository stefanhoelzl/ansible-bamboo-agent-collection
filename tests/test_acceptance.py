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
from tests import IpAddress, RequestTestCase, BambooHome


class HttpRequestHandler(BaseHTTPRequestHandler):
    Responses: List[Response] = list()
    Requests: List[Request] = list()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for method in Method.__members__.values():
            setattr(cls, f"do_{method}", partialmethod(cls.do, method=method))

    def do(self, method: Method):
        header = dict(**self.headers)
        header.pop("Host")
        header.pop("User-Agent")
        header.pop("Accept-Encoding")
        header.pop("Connection")
        content_length = int(header.pop("Content-Length", 0))
        self.Requests.append(
            Request(
                self.path,
                content=self.rfile.read(content_length),
                method=method,
                header=header,
            )
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


@contextmanager
def bamboo_server(port: int, responses: list) -> str:
    requests = []

    class _RequestHandler(HttpRequestHandler):
        Responses = responses
        Requests = requests

    httpd = HTTPServer(("localhost", port), _RequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://localhost:{port}", requests
    httpd.server_close()
    httpd.shutdown()
    thread.join()


class BambooAgentAcceptanceTest(RequestTestCase):
    Home = BambooHome()
    Arguments = dict(authentication=dict(user="", password=""))
    Responses: List[Response] = list()
    ExpectedRequests: List[Request] = list()
    ExpectedResult = dict()
    ExpectChange = False

    _NextServerPort = 7000

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        setattr(cls, f"test_{cls.__name__}", cls._test)
        cls.ServerPort = BambooAgentAcceptanceTest._NextServerPort
        BambooAgentAcceptanceTest._NextServerPort += 1

    def _test(self):
        result, requests = self._run_module()
        self.assert_requests(requests, *self.ExpectedRequests)
        self.assertEqual(result.pop("changed"), self.ExpectChange)
        self._check_result(result)

    def _run_module(self):
        with TemporaryDirectory() as tempdir:
            with bamboo_server(self.ServerPort, self.Responses) as (url, requests):
                arguments_file_path = Path(tempdir, "arguments.json")
                with open(arguments_file_path, mode="w+") as arguments_file:
                    arguments = {
                        **BambooAgentAcceptanceTest.Arguments,
                        **self.Arguments,
                    }
                    json.dump(
                        dict(
                            ANSIBLE_MODULE_ARGS=dict(
                                host=url,
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

        if process.returncode:
            raise RuntimeError(process.returncode, process.stdout, process.stderr)
        return json.loads(process.stdout), requests

    def _check_result(self, result):
        del result["invocation"]
        self.assertEqual(result, self.ExpectedResult)


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
        templates.Agents.response([dict(id=1234)]),
    ]
