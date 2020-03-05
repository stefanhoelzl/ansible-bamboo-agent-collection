import time
import ssl
from functools import partial
from unittest import TestCase
from unittest.mock import Mock
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
    timeout,
)


class TestTimeout(TestCase):
    def test_query_result(self):
        self.assertTrue(timeout(Mock(return_value=True), timeout=0))

    def test_raise(self):
        self.assertRaises(
            TimeoutError, partial(timeout, Mock(side_effect=TimeoutError), timeout=0)
        )

    def test_retry(self):
        self.assertTrue(timeout(Mock(side_effect=[TimeoutError, True]), timeout=0.1))

    def test_interval(self):
        mock = Mock(side_effect=[TimeoutError] * 3)
        self.assertRaises(
            TimeoutError, partial(timeout, mock, timeout=0.02, interval=0.01)
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
        response = self.responses.pop(0) if self.responses else None
        if callable(response):
            response()
        return response


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
    def test_uuid_is_none(self):
        with BambooHome().temp() as home:
            bac = make_bamboo_agent_configuration(home=home)
            self.assertIsNone(bac.uuid())

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

    def test_id_is_none(self):
        with BambooHome().temp() as home:
            bac = make_bamboo_agent_configuration(home=home)
            self.assertIsNone(bac.id())

    def test_id_config(self):
        with BambooHome().config(aid=1234).temp() as home:
            bac = make_bamboo_agent_configuration(home=home)
            self.assertEqual(bac.id(), 1234)

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
    def test_skip(self):
        rh = MockRequestHandler(responses=[Response(list())])
        bac = make_bamboo_agent_configuration(rh)
        bac.register()
        self.assert_requests(rh.requests, templates.Pending.request())
        self.assertFalse(bac.changed)

    def test_new_agent(self):
        with BambooHome().config(uuid="0000").temp() as home:
            rh = MockRequestHandler(
                responses=[
                    templates.Pending.response(uuid="0000"),
                    templates.Authentication.response().action(
                        lambda: BambooHome().config(aid=1234).create(home)
                    ),
                    templates.Agents.response([dict(id=1234)]),
                ]
            )
            bac = make_bamboo_agent_configuration(rh, home=home)
            bac.register()

        self.assert_requests(
            rh.requests,
            templates.Pending.request(),
            templates.Authentication.request(uuid="0000"),
            templates.Agents.request(),
        )
        self.assertTrue(bac.changed)

    def test_timeout_missing_config_file(self):
        with BambooHome().config(uuid="0000").temp() as home:
            rh = MockRequestHandler(
                responses=[
                    templates.Pending.response(uuid="0000"),
                    templates.Authentication.response(),
                    templates.Agents.response([dict(id=1234)]),
                ]
            )
            bac = make_bamboo_agent_configuration(
                rh, home=home, timeouts=dict(authentication=0)
            )
            self.assertRaises(TimeoutError, bac.register)

    def test_timeout_missing_id_in_response(self):
        with BambooHome().config(uuid="0000").temp() as home:
            rh = MockRequestHandler(
                responses=[
                    templates.Pending.response(uuid="0000"),
                    templates.Authentication.response().action(
                        lambda: BambooHome().config(aid=1234).create(home)
                    ),
                    templates.Agents.response([]),
                ]
            )
            bac = make_bamboo_agent_configuration(
                rh, home=home, timeouts=dict(authentication=0.0)
            )
            self.assertRaises(TimeoutError, bac.register)

    def test_timeout_retries(self):
        with BambooHome().config(uuid="0000").temp() as home:
            rh = MockRequestHandler(
                responses=[
                    templates.Pending.response(uuid="0000"),
                    templates.Authentication.response().action(
                        lambda: BambooHome().config(aid=1234).create(home)
                    ),
                    templates.Agents.response([]),
                    templates.Agents.response([]).action(partial(time.sleep, 0.1)),
                ]
            )
            bac = make_bamboo_agent_configuration(
                rh, home=home, timeouts=dict(authentication=0.1)
            )
            self.assertRaises(TimeoutError, bac.register)
            self.assert_requests(
                rh.requests,
                templates.Pending.request(),
                templates.Authentication.request(uuid="0000"),
                templates.Agents.request(),
                templates.Agents.request(),
            )

    def test_connection_error(self):
        rh = MockRequestHandler(
            responses=[
                templates.Pending.response(uuid="0000"),
                templates.Authentication.response(500),
            ]
        )
        with BambooHome().config(uuid="0000").temp() as home:
            bac = make_bamboo_agent_configuration(rh, home=home)
            self.assertRaises(ConnectionError, bac.register)
