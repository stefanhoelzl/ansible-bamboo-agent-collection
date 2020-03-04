import ssl
from functools import partial
from unittest import TestCase
from typing import List, Optional
from contextlib import contextmanager
from tests import RequestTestCase, IpAddress, BambooHome
from . import templates
from .proxy import (
    BambooAgentConfiguration,
    Request,
    Response,
    Method,
    HttpRequestHandler,
)


class MockUrlOpen:
    class MockResponse:
        def __init__(self, status_code: int, content: bytes):
            self.status_code = status_code
            self.content = content

        def read(self) -> bytes:
            return self.content

        def getcode(self) -> int:
            return self.status_code

    def __init__(self, status_code: int = 200, content: bytes = b""):
        self.response = self.MockResponse(status_code, content)
        self.context = None
        self.url = None
        self.method = None
        self.header = None

    @contextmanager
    def __call__(self, request, context):
        self.context = context
        self.url = request.full_url
        self.method = request.method
        self.header = request.headers
        yield self.response


class TestHttpRequestHandler(TestCase):
    def test_default_request(self):
        urlopen = MockUrlOpen()
        handler = HttpRequestHandler(
            "http://host/", urlopen=urlopen, auth=("user", "password")
        )
        handler(Request("/my/path"))

        self.assertEqual(urlopen.url, "http://host/my/path")
        self.assertEqual(urlopen.method, "GET")
        self.assertEqual(
            urlopen.header, dict(Authorization="Basic dXNlcjpwYXNzd29yZA==")
        )
        self.assertTrue(isinstance(urlopen.context, ssl.SSLContext))

    def test_response_data_and_status_code(self):
        handler = HttpRequestHandler(
            "http://host/",
            urlopen=MockUrlOpen(status_code=204, content=b"[1, 2, 3]"),
            auth=("", ""),
        )
        response = handler(Request("/my/path"))

        self.assertEqual(response.content, [1, 2, 3])
        self.assertEqual(response.status_code, 204)

    def test_custom_method(self):
        urlopen = MockUrlOpen()
        handler = HttpRequestHandler("http://host/", urlopen=urlopen, auth=("", ""))
        handler(Request("/my/path", method=Method.Put))

        self.assertEqual(urlopen.method, "PUT")


class MockRequestHandler:
    def __init__(self, responses: Optional[List[Response]] = None):
        self.responses = responses or []
        self.requests = []

    def __call__(self, host: str, auth):
        return self.handler

    def handler(self, request: Request) -> Optional[Response]:
        self.requests.append(request)
        return self.responses.pop(0) if self.responses else None


def make_bamboo_agent_configuration(
    request_handler: Optional[MockRequestHandler] = None,
    home: Optional[BambooHome] = None,
    **kwargs
) -> BambooAgentConfiguration:
    return BambooAgentConfiguration(
        request_handler=request_handler or MockRequestHandler(),
        host="http://localhost",
        home=home or "",
        authentication=dict(user="", password=""),
        **kwargs,
    )


class TestRequest(RequestTestCase):
    def test_returns_response(self):
        response = Response(content=b"[]")
        request = Request("/my/path")
        rh = MockRequestHandler(responses=[response])
        bac = make_bamboo_agent_configuration(rh)
        self.assertEqual(bac.request(request), response)
        self.assert_requests(rh.requests, request)

    def test_expect_default_response_code(self):
        response = Response(status_code=204)
        rh = MockRequestHandler(responses=[response])
        bac = make_bamboo_agent_configuration(rh)
        self.assertRaises(ConnectionError, lambda: bac.request(Request("/")))

    def test_expect_custom_response_code(self):
        response = Response(status_code=200)
        rh = MockRequestHandler(responses=[response])
        bac = make_bamboo_agent_configuration(rh)
        self.assertRaises(
            ConnectionError, lambda: bac.request(Request("/"), response_code=204)
        )


class TestData(RequestTestCase):
    def test_uuid_from_temp_properties(self):
        with BambooHome().temp_uuid("0000").temp() as home:
            bac = make_bamboo_agent_configuration(home=home)
            self.assertEqual(bac.uuid(), "0000")

    def test_uuid_config(self):
        with BambooHome().config(uuid="0000").temp() as home:
            bac = make_bamboo_agent_configuration(home=home)
            self.assertEqual(bac.uuid(), "0000")

    def test_uuid_prefer_from_config(self):
        with BambooHome().temp_uuid("0000").config(uuid="1111", aid=0).temp() as home:
            bac = make_bamboo_agent_configuration(home=home)
            self.assertEqual(bac.uuid(), "1111")

    def test_pending(self):
        bac = make_bamboo_agent_configuration(
            request_handler=MockRequestHandler(
                responses=[Response([dict(uuid="0000")])]
            )
        )
        self.assertTrue(bac.authentication_pending(uuid="0000"))

    def test_not_pending(self):
        bac = make_bamboo_agent_configuration(
            request_handler=MockRequestHandler(responses=[Response([])])
        )
        self.assertFalse(bac.authentication_pending(uuid="0000"))


class TestRegistration(RequestTestCase):
    def test_register_new_agent(self):
        rh = MockRequestHandler(
            responses=[
                templates.Pending.response(uuid="0000"),
                templates.Authentication.response(),
            ]
        )
        with BambooHome().config(uuid="0000").temp() as home:
            bac = make_bamboo_agent_configuration(rh, home=home)
            bac.register()
        self.assert_requests(
            rh.requests,
            templates.Pending.request(),
            templates.Authentication.request(uuid="0000"),
        )
        self.assertTrue(bac.changed)

    def test_register_failure(self):
        rh = MockRequestHandler(
            responses=[
                templates.Pending.response(uuid="0000"),
                templates.Authentication.response(500),
            ]
        )
        with BambooHome().config(uuid="0000").temp() as home:
            bac = make_bamboo_agent_configuration(rh, home=home)
            self.assertRaises(ConnectionError, bac.register)

    def test_skip_registration(self):
        rh = MockRequestHandler(responses=[Response(list())])
        bac = make_bamboo_agent_configuration(rh)
        bac.register()
        self.assert_requests(rh.requests, templates.Pending.request())
        self.assertFalse(bac.changed)
