import time
import ssl
from functools import partial
from unittest import TestCase
from unittest.mock import Mock, call
from typing import List, Optional
from contextlib import contextmanager
from tests import RequestTestCase, IpAddress, BambooHome
from . import templates
from .proxy import (
    BambooAgentController,
    BambooAgent,
    Request,
    Response,
    Method,
    HttpRequestHandler,
    timeout,
    ServerConnectionError,
    MissingUuid,
    SelfRecoverableBambooAgentError,
)


class TestTimeout(TestCase):
    def test_returns_query_result(self):
        self.assertTrue(timeout(Mock(return_value=True), timeout=0))

    def test_raise(self):
        self.assertRaises(
            TimeoutError,
            partial(
                timeout, Mock(side_effect=SelfRecoverableBambooAgentError), timeout=0
            ),
        )

    def test_retry(self):
        self.assertTrue(
            timeout(
                Mock(side_effect=[SelfRecoverableBambooAgentError, True]), timeout=0.1
            )
        )

    def test_interval(self):
        mock = Mock(side_effect=[SelfRecoverableBambooAgentError] * 3)
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
        self.url = None
        self.method = None
        self.header = None

    @contextmanager
    def __call__(self, request, timeout):
        self.url = request.full_url
        self.method = request.method
        self.header = request.headers
        self.timeout = timeout
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
            urlopen.header,
            {
                "Authorization": "Basic dXNlcjpwYXNzd29yZA==",
                "X-atlassian-token": "no-check",
            },
        )
        self.assertEqual(urlopen.timeout, 10)

    def test_response_data_and_status_code(self):
        handler = HttpRequestHandler(
            "http://host/",
            auth=("", ""),
            urlopen=MockUrlOpen(status_code=204, content=b"[1, 2, 3]"),
        )
        response = handler(Request("/my/path"))

        self.assertEqual(response.content, [1, 2, 3])
        self.assertEqual(response.status_code, 204)

    def test_custom_method(self):
        urlopen = MockUrlOpen()
        handler = HttpRequestHandler("http://host/", auth=("", ""), urlopen=urlopen)
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
            response.__call__()
        return response


def make_bamboo_agent(
    request_handler: Optional[MockRequestHandler] = None,
    home: Optional[BambooHome] = None,
) -> BambooAgentController:
    return BambooAgent(
        host="http://localhost",
        home=home or "",
        authentication=dict(user="", password=""),
        request_handler=request_handler or MockRequestHandler(),
    )


class TestRequest(RequestTestCase):
    def test_returns_response(self):
        response = Response(content=b"[]")
        request = Request("/my/path")
        rh = MockRequestHandler(responses=[response])
        agent = make_bamboo_agent(rh)
        self.assertEqual(agent.request(request), response)
        self.assert_requests(rh.requests, request)

    def test_expect_default_response_code(self):
        response = Response(status_code=204)
        rh = MockRequestHandler(responses=[response])
        agent = make_bamboo_agent(rh)
        self.assertRaises(ServerConnectionError, lambda: agent.request(Request("/")))

    def test_expect_custom_response_code(self):
        response = Response(status_code=200)
        rh = MockRequestHandler(responses=[response])
        agent = make_bamboo_agent(rh)
        self.assertRaises(
            ServerConnectionError,
            lambda: agent.request(Request("/"), response_code=204),
        )


class TestBambooAgent(RequestTestCase):
    def test_uuid_is_none(self):
        with BambooHome().temp() as home:
            agent = make_bamboo_agent(home=home)
            self.assertIsNone(agent.uuid())

    def test_uuid_from_temp_properties(self):
        with BambooHome().temp_uuid("0000").temp() as home:
            agent = make_bamboo_agent(home=home)
            self.assertEqual(agent.uuid(), "0000")

    def test_uuid_config(self):
        with BambooHome().config(uuid="0000").temp() as home:
            agent = make_bamboo_agent(home=home)
            self.assertEqual(agent.uuid(), "0000")

    def test_uuid_prefer_from_config(self):
        with BambooHome().temp_uuid("0000").config(uuid="1111", aid=0).temp() as home:
            agent = make_bamboo_agent(home=home)
            self.assertEqual(agent.uuid(), "1111")

    def test_id_is_none(self):
        with BambooHome().temp() as home:
            agent = make_bamboo_agent(home=home)
            self.assertIsNone(agent.id())

    def test_id_config(self):
        with BambooHome().config(uuid="0000", aid=1234).temp() as home:
            agent = make_bamboo_agent(home=home)
            self.assertEqual(agent.id(), 1234)

    def test_not_authenticated_pending(self):
        with BambooHome().temp_uuid(uuid="0000").temp() as home:
            agent = make_bamboo_agent(
                home=home,
                request_handler=MockRequestHandler(
                    responses=[Response([dict(uuid="0000")])]
                ),
            )
            self.assertFalse(agent.authenticated())

    def test_authenticated(self):
        with BambooHome().config(uuid="0000", aid=1234).temp() as home:
            agent = make_bamboo_agent(
                home=home,
                request_handler=MockRequestHandler(
                    responses=[Response([]), templates.Agents.response([dict(id=1234)])]
                ),
            )
            self.assertTrue(agent.authenticated())

    def test_authenticated_no_uuid(self):
        with BambooHome().temp() as home:
            agent = make_bamboo_agent(home=home,)
            self.assertFalse(agent.authenticated())

    def test_available(self):
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(
                home=home,
                request_handler=MockRequestHandler(
                    responses=[templates.Agents.response([dict(id=1234)])]
                ),
            )
            self.assertTrue(agent.available())

    def test_not_available(self):
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(
                home=home,
                request_handler=MockRequestHandler(
                    responses=[templates.Agents.response(list())]
                ),
            )
            self.assertFalse(agent.available())

    def test_available_no_id(self):
        with BambooHome().temp() as home:
            agent = make_bamboo_agent(home=home)
            self.assertFalse(agent.available())

    def test_authenticate(self):
        rh = MockRequestHandler(responses=[templates.Authentication.response()])
        with BambooHome().temp_uuid(uuid="0000").temp() as home:
            agent = make_bamboo_agent(home=home, request_handler=rh)
            agent.authenticate()
        self.assert_requests(rh.requests, templates.Authentication.request(uuid="0000"))

    def test_authenticate_no_uuid(self):
        with BambooHome().temp() as home:
            agent = make_bamboo_agent(home=home)
            self.assertRaises(MissingUuid, agent.authenticate)

    def test_enabled(self):
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(
                home=home,
                request_handler=MockRequestHandler(
                    responses=[templates.Agents.response([dict(id=1234, enabled=True)])]
                ),
            )
            self.assertTrue(agent.enabled())

    def test_not_enabled(self):
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(
                home=home,
                request_handler=MockRequestHandler(
                    responses=[
                        templates.Agents.response([dict(id=1234, enabled=False)])
                    ]
                ),
            )
            self.assertFalse(agent.enabled())

    def test_disable(self):
        rh = MockRequestHandler(responses=[templates.Disable.response()])
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(home=home, request_handler=rh)
            agent.disable()
        self.assert_requests(rh.requests, templates.Disable.request(agent_id=1234))

    def test_enable(self):
        rh = MockRequestHandler(responses=[templates.Enable.response()])
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(home=home, request_handler=rh)
            agent.enable()
        self.assert_requests(rh.requests, templates.Enable.request(agent_id=1234))

    def test_name(self):
        rh = MockRequestHandler(
            responses=[templates.Agents.response([dict(id=1234, name="agent-name")])]
        )
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(home=home, request_handler=rh)
            self.assertEqual(agent.name(), "agent-name")
        self.assert_requests(rh.requests, templates.Agents.request())

    def test_set_name(self):
        rh = MockRequestHandler(responses=[templates.SetName.response()])
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(home=home, request_handler=rh)
            agent.set_name("new-name")
        self.assert_requests(
            rh.requests, templates.SetName.request(agent_id=1234, name="new-name")
        )

    def test_caching(self):
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(
                home=home,
                request_handler=MockRequestHandler(
                    responses=[
                        templates.Agents.response(
                            [dict(id=1234, enabled=True, name="agent-name")]
                        )
                    ]
                ),
            )
            self.assertTrue(agent.available())
            self.assertTrue(agent.enabled())
            self.assertEqual(agent.name(), "agent-name")


def make_bamboo_agent_controller(
    agent: BambooAgent = None, **kwargs
) -> BambooAgentController:
    return BambooAgentController(agent=agent, **kwargs,)


class TestRegistration(TestCase):
    def test_skip(self):
        agent = Mock()
        agent.authenticated.return_value = True
        controller = make_bamboo_agent_controller(agent=agent)
        controller.register()
        self.assertEqual(agent.method_calls, [call.authenticated()])
        self.assertFalse(controller.changed)

    def test_new_agent(self):
        agent = Mock()
        agent.authenticated.return_value = False
        agent.available.return_value = True
        controller = make_bamboo_agent_controller(agent=agent)
        controller.register()
        self.assertEqual(
            agent.method_calls,
            [call.authenticated(), call.authenticate(), call.available()],
        )
        self.assertTrue(controller.changed)

    def test_retries(self):
        agent = Mock()
        agent.authenticated.return_value = False
        agent.available.side_effect = [False, True]
        controller = make_bamboo_agent_controller(agent=agent)
        controller.register()
        self.assertEqual(
            agent.method_calls,
            [
                call.authenticated(),
                call.authenticate(),
                call.available(),
                call.available(),
            ],
        )

    def test_timeout(self):
        agent = Mock()
        agent.authenticated.return_value = False
        agent.available.return_value = False
        controller = make_bamboo_agent_controller(
            agent=agent, timeouts=dict(authentication=0)
        )
        self.assertRaises(TimeoutError, controller.register)


class TestSetEnabled(TestCase):
    def test_unchanged(self):
        agent = Mock()
        controller = make_bamboo_agent_controller(agent=agent)
        controller.set_enabled(None)
        self.assertEqual(agent.method_calls, [])
        self.assertFalse(controller.changed)

    def test_different(self):
        agent = Mock()
        agent.enabled.return_value = True
        controller = make_bamboo_agent_controller(agent=agent)
        controller.set_enabled(True)
        self.assertEqual(agent.method_calls, [call.enabled()])
        self.assertFalse(controller.changed)

    def test_enable(self):
        agent = Mock()
        agent.enabled.return_value = False
        controller = make_bamboo_agent_controller(agent=agent)
        controller.set_enabled(True)
        self.assertEqual(agent.method_calls, [call.enabled(), call.enable()])
        self.assertTrue(controller.changed)

    def test_disable(self):
        agent = Mock()
        agent.enabled.return_value = True
        controller = make_bamboo_agent_controller(agent=agent)
        controller.set_enabled(False)
        self.assertEqual(agent.method_calls, [call.enabled(), call.disable()])
        self.assertTrue(controller.changed)


class TestSetName(TestCase):
    def test_unchanged(self):
        agent = Mock()
        controller = make_bamboo_agent_controller(agent=agent)
        controller.set_name(None)
        self.assertEqual(agent.method_calls, [])
        self.assertFalse(controller.changed)

    def test_same(self):
        agent = Mock()
        agent.name.return_value = "agent-name"
        controller = make_bamboo_agent_controller(agent=agent)
        controller.set_name("agent-name")
        self.assertEqual(agent.method_calls, [call.name()])
        self.assertFalse(controller.changed)

    def test_different(self):
        agent = Mock()
        agent.name.return_value = "old-name"
        controller = make_bamboo_agent_controller(agent=agent)
        controller.set_name("new-name")
        self.assertEqual(agent.method_calls, [call.name(), call.set_name("new-name")])
        self.assertTrue(controller.changed)
