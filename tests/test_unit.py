import time
import ssl
import yaml
from functools import partial
from unittest import TestCase
from unittest.mock import Mock, call
from typing import List, Optional
from contextlib import contextmanager
from tests import RequestTestCase, IpAddress, BambooHome, ActionResponse
from . import templates
from plugins.modules.configuration import (
    DOCUMENTATION,
    ArgumentSpec,
    BambooAgentController,
    BambooAgent,
    State,
    Request,
    Response,
    Method,
    HttpRequestHandler,
    retry,
    ServerCommunicationError,
    MissingUuid,
    SelfRecoverableBambooAgentError,
    AssignmentNotFound,
    AgentBusy,
)


class TestDocumentation(TestCase):
    def test_spec_matches_docstring(self):
        def clean(spec):
            spec.pop("description", None)
            for key, value in spec.items():
                if isinstance(value, dict):
                    clean(value)
                elif key == "type":
                    spec[key] = {
                        t.__name__: t for t in [str, int, bool, float, dict, list]
                    }[value]

        doc_spec = yaml.load(DOCUMENTATION)["options"]
        clean(doc_spec)
        self.assertEqual(doc_spec, ArgumentSpec)


class TestRetry(TestCase):
    def test_returns_query_result(self):
        self.assertTrue(retry(Mock(return_value=True), timeout=0, interval=0))

    def test_raise(self):
        self.assertRaises(
            TimeoutError,
            partial(
                retry,
                Mock(side_effect=SelfRecoverableBambooAgentError()),
                timeout=0,
                interval=0,
            ),
        )

    def test_retry(self):
        self.assertTrue(
            retry(
                Mock(side_effect=[SelfRecoverableBambooAgentError(), True]),
                timeout=0.1,
                interval=0,
            )
        )

    def test_interval(self):
        mock = Mock(side_effect=[SelfRecoverableBambooAgentError()] * 3)
        self.assertRaises(
            TimeoutError, partial(retry, mock, timeout=0.02, interval=0.01)
        )

    def test_no_timeout(self):
        self.assertTrue(
            retry(
                Mock(side_effect=[SelfRecoverableBambooAgentError(), True]),
                timeout=None,
                interval=0,
            )
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
            "http://host/sub", urlopen=urlopen, auth=("user", "password"), timeout=0
        )
        handler(Request("/my/path"))

        self.assertEqual(urlopen.url, "http://host/sub/my/path")
        self.assertEqual(urlopen.method, "GET")
        self.assertEqual(
            urlopen.header,
            {
                "Authorization": "Basic dXNlcjpwYXNzd29yZA==",
                "X-atlassian-token": "no-check",
            },
        )

    def test_response_data_and_status_code(self):
        handler = HttpRequestHandler(
            "http://host/",
            auth=("", ""),
            timeout=0,
            urlopen=MockUrlOpen(status_code=204, content=b"[1, 2, 3]"),
        )
        response = handler(Request("/my/path"))

        self.assertEqual(response.content, [1, 2, 3])
        self.assertEqual(response.status_code, 204)

    def test_read_no_data(self):
        handler = HttpRequestHandler(
            "http://host/",
            auth=("", ""),
            timeout=0,
            urlopen=MockUrlOpen(status_code=204, content=b"[1, 2, 3]"),
        )
        response = handler(Request("/my/path"), read=False)

        self.assertEqual(response.content, None)
        self.assertEqual(response.status_code, 204)

    def test_custom_method(self):
        urlopen = MockUrlOpen()
        handler = HttpRequestHandler(
            "http://host/", auth=("", ""), timeout=0, urlopen=urlopen
        )
        handler(Request("/my/path", method=Method.Put))

        self.assertEqual(urlopen.method, "PUT")

    def test_timeout(self):
        urlopen = MockUrlOpen()
        handler = HttpRequestHandler(
            "http://host/", auth=("", ""), timeout=0, urlopen=urlopen
        )
        handler(Request("/my/path", method=Method.Put))
        self.assertEqual(urlopen.timeout, 0)


class MockRequestHandler:
    def __init__(self, responses: Optional[List[Response]] = None):
        self.responses = responses or []
        self.requests = []
        self.timeout = None

    def __call__(self, host: str, auth, timeout: int):
        self.timeout = timeout
        return self.handler

    def handler(self, request: Request, read) -> Optional[Response]:
        self.requests.append(request)
        response = self.responses.pop(0) if self.responses else None
        if callable(response):
            response.__call__()
        return response


class TestState(TestCase):
    def test_set_get(self):
        state = State()
        state.set("key", "value")
        self.assertEqual(state["key"], "value")

    def test_init(self):
        state = State(key="value")
        self.assertEqual(state["key"], "value")

    def test_get_default_dict(self):
        state = State()
        self.assertEqual(state["key"], dict())

    def test_init_value(self):
        state = State()
        state.set("key", "value")
        self.assertEqual(state.initial, dict(key="value"))
        self.assertEqual(state.current, dict(key="value"))

    def test_update_value(self):
        state = State()
        state.set("key", "initial")
        state.set("key", "current")
        self.assertEqual(state.current, dict(key="current"))
        self.assertEqual(state.initial, dict(key="initial"))

    def test_copy_value(self):
        state = State()
        state.set("key", dict(sub="initial"))
        state["key"]["sub"] = "current"
        self.assertEqual(state.initial, dict(key=dict(sub="initial")))
        self.assertEqual(state.current, dict(key=dict(sub="current")))

    def test_changed(self):
        state = State()
        state.set("key", "initial")
        self.assertFalse(state.changed)
        state.set("key", "updated")
        self.assertTrue(state.changed)


def make_bamboo_agent(
    request_handler: Optional[MockRequestHandler] = None,
    home: Optional[BambooHome] = None,
    http_timeout: int = 0,
    check_mode: bool = False,
) -> BambooAgentController:
    return BambooAgent(
        host="http://localhost",
        home=home or "",
        credentials=dict(user="", password=""),
        request_handler=request_handler or MockRequestHandler(),
        http_timeout=http_timeout,
        check_mode=check_mode,
    )


class TestRequest(RequestTestCase):
    def test_returns_response(self):
        response = Response(content=b"[]")
        request = Request("/my/path")
        rh = MockRequestHandler(responses=[response])
        agent = make_bamboo_agent(rh)
        self.assertEqual(agent.request(request), response)
        self.assert_requests(rh.requests, request)

    def test_valid_response_codes(self):
        rh = MockRequestHandler(
            responses=[
                Response(status_code=200),
                Response(status_code=200),
                Response(status_code=204),
                Response(status_code=204),
            ]
        )
        agent = make_bamboo_agent(rh)
        agent.request(Request("/", method=Method.Get))
        agent.request(Request("/", method=Method.Post))
        agent.request(Request("/", method=Method.Delete))
        agent.request(Request("/", method=Method.Put))

    def test_allow_redirect(self):
        rh = MockRequestHandler(
            responses=[
                Response(status_code=200),
                Response(status_code=302),
                Response(status_code=302),
            ]
        )
        agent = make_bamboo_agent(rh)
        agent.request(Request("/", method=Method.Post), allow_redirect=True)
        agent.request(Request("/", method=Method.Post), allow_redirect=True)
        self.assertRaises(
            ServerCommunicationError,
            partial(agent.request, Request("/", method=Method.Post)),
        )

    def test_timeout(self):
        rh = MockRequestHandler(responses=[Response(status_code=200)])
        agent = make_bamboo_agent(rh, http_timeout=0)
        agent.request(Request("/"))
        self.assertEqual(rh.timeout, 0)


class TestChange(RequestTestCase):
    def test_forward_request(self):
        request = Request("/my/path")
        rh = MockRequestHandler(responses=[Response()])
        agent = make_bamboo_agent(rh)
        agent.change(request, state_update=None)
        self.assert_requests(rh.requests, request)

    def test_suppress_change_in_check_mode(self):
        rh = MockRequestHandler()
        agent = make_bamboo_agent(rh, check_mode=True)
        agent.change(Request("/"), state_update=None)
        self.assertEqual(len(rh.requests), 0)

    def test_change_state(self):
        rh = MockRequestHandler(responses=[ActionResponse()])
        agent = make_bamboo_agent(rh)
        agent.state.set("key", dict(sub="value"))
        agent.change(Request("/"), state_update=lambda s: s["key"].pop("sub"))
        self.assertEqual(agent.state["key"], dict())


class TestBambooAgent(RequestTestCase):
    def test_info(self):
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(
                home=home,
                request_handler=MockRequestHandler(
                    responses=[templates.Agents.response([dict(id=1234, key="value")])]
                ),
            )
            self.assertEqual(agent.info(), dict(id=1234, key="value"))
            self.assertEqual(agent.state["info"], dict(id=1234, key="value"))

    def test_info_caching(self):
        request_handler = MockRequestHandler(
            responses=[
                templates.Agents.response(
                    [dict(id=1234, enabled=True, name="agent-name")]
                )
            ]
        )
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(home=home, request_handler=request_handler,)
            agent.info()
            agent.info()
        self.assert_requests(request_handler.requests, templates.Agents.request())

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
            self.assertTrue(agent.state["authenticated"])

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
            agent.state.set("authenticated", False)
            agent.authenticate()
        self.assert_requests(rh.requests, templates.Authentication.request(uuid="0000"))
        self.assertTrue(agent.state["authenticated"])

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

    def test_disable(self):
        rh = MockRequestHandler(responses=[templates.Disable.response()])
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(home=home, request_handler=rh)
            agent.state.set("info", dict(enabled=True))
            agent.disable()
        self.assert_requests(rh.requests, templates.Disable.request(agent_id=1234))
        self.assertFalse(agent.state["info"]["enabled"])

    def test_disable_with_redirect(self):
        rh = MockRequestHandler(responses=[templates.Disable.response(status_code=302)])
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(home=home, request_handler=rh)
            agent.disable()

    def test_enable(self):
        rh = MockRequestHandler(responses=[templates.Enable.response()])
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(home=home, request_handler=rh)
            agent.state.set("info", dict(enabled=False))
            agent.enable()
        self.assert_requests(rh.requests, templates.Enable.request(agent_id=1234))
        self.assertTrue(agent.state["info"]["enabled"])

    def test_enable_with_redirect(self):
        rh = MockRequestHandler(responses=[templates.Enable.response(status_code=302)])
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(home=home, request_handler=rh)
            agent.enable()

    def test_busy(self):
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(
                home=home,
                request_handler=MockRequestHandler(
                    responses=[templates.Agents.response([dict(id=1234, busy=True)])]
                ),
            )
            self.assertTrue(agent.busy())

    def test_busy_no_caching(self):
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(
                home=home,
                request_handler=MockRequestHandler(
                    responses=[
                        templates.Agents.response([dict(id=1234, busy=True)]),
                        templates.Agents.response([dict(id=1234, busy=False)]),
                    ]
                ),
            )
            self.assertTrue(agent.busy())
            self.assertFalse(agent.busy())

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
        self.assertEqual(agent.state["info"]["name"], "new-name")

    def test_set_name_with_redirect(self):
        rh = MockRequestHandler(responses=[templates.SetName.response(status_code=302)])
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(home=home, request_handler=rh)
            agent.set_name("name")

    def test_assignments(self):
        rh = MockRequestHandler(
            responses=[
                templates.Assignments.response(
                    [dict(executableType="PROJECT", executableId=123456)]
                )
            ]
        )
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(home=home, request_handler=rh)
            self.assertEqual(agent.assignments(), {123456: "PROJECT"})
            self.assertEqual(agent.state["assignments"], {123456: "PROJECT"})
        self.assert_requests(rh.requests, templates.Assignments.request(agent_id=1234))

    def test_add_assignment(self):
        rh = MockRequestHandler(responses=[templates.AddAssignment.response()])
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(home=home, request_handler=rh)
            agent.add_assignment(etype="PROJECT", eid=2)
        self.assert_requests(
            rh.requests,
            templates.AddAssignment.request(agent_id=1234, eid=2, etype="PROJECT"),
        )
        self.assertEqual(agent.state["assignments"], {2: "PROJECT"})

    def test_remove_assignment(self):
        rh = MockRequestHandler(responses=[templates.RemoveAssignment.response()])
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(home=home, request_handler=rh)
            agent.state.set("assignments", {2: "PROJECT"})
            agent.remove_assignment(etype="PROJECT", eid=2)
        self.assert_requests(
            rh.requests,
            templates.RemoveAssignment.request(agent_id=1234, eid=2, etype="PROJECT"),
        )
        self.assertEqual(agent.state["assignments"], dict())

    def test_resolve_assignments(self):
        rh = MockRequestHandler(
            responses=[
                templates.SearchAssignment.response([dict(id=2, key="PR")]),
                templates.SearchAssignment.response(
                    [dict(id=0, key="P0"), dict(id=1, key="P1")]
                ),
            ]
        )
        agent = make_bamboo_agent(request_handler=rh)
        resolved = agent.resolve_assignments(
            [
                dict(type="project", key="PR"),
                dict(type="plan", key="P0"),
                dict(type="plan", key="P1"),
            ]
        )
        self.assertEqual(resolved, {0: "PLAN", 1: "PLAN", 2: "PROJECT"})
        self.assert_requests(
            rh.requests,
            templates.SearchAssignment.request(etype="PROJECT"),
            templates.SearchAssignment.request(etype="PLAN"),
        )

    def test_resolve_assignments_not_found(self):
        rh = MockRequestHandler(
            responses=[templates.SearchAssignment.response([dict(id=0, key="XX")]),]
        )
        agent = make_bamboo_agent(request_handler=rh)
        self.assertRaises(
            AssignmentNotFound,
            partial(agent.resolve_assignments, [dict(type="project", key="AA")],),
        )

    def test_delete(self):
        rh = MockRequestHandler(responses=[templates.Delete.response()])
        with BambooHome().config(aid=1234).temp() as home:
            agent = make_bamboo_agent(home=home, request_handler=rh)
            agent.delete()
        self.assert_requests(rh.requests, templates.Delete.request(agent_id=1234))
        self.assertTrue(agent.state["deleted"])


def make_bamboo_agent_controller(
    agent: BambooAgent = None, **kwargs
) -> BambooAgentController:
    return BambooAgentController(agent=agent, **kwargs)


class AgentMock(Mock):
    def __init__(
        self,
        busy=False,
        check_mode=False,
        authenticated=False,
        available=False,
        name="",
        enabled=False,
        assignments=None,
    ):
        super().__init__(spec=BambooAgent)
        self.check_mode = check_mode
        self.authenticated = Mock(return_value=authenticated)
        self.name = Mock(return_value=name)
        self.enabled = Mock(return_value=enabled)
        self.assignments = Mock(return_value=assignments or dict())
        self.set_name = Mock()
        self.enable = Mock()
        self.disable = Mock()
        self.authenticate = Mock()
        self.add_assignment = Mock()
        self.remove_assignment = Mock()

        self.available = Mock()
        if isinstance(available, bool):
            self.available.return_value = available
        else:
            self.available.side_effect = available

        self.busy = Mock()
        if isinstance(busy, bool):
            self.busy.return_value = busy
        else:
            self.busy.side_effect = busy


class TestAuthentication(TestCase):
    def test_skip(self):
        agent = AgentMock(authenticated=True)
        controller = make_bamboo_agent_controller(agent=agent)
        controller.authenticate()
        self.assertEqual(agent.method_calls, [call.authenticated()])

    def test_new_agent(self):
        agent = AgentMock(authenticated=False, available=True)
        controller = make_bamboo_agent_controller(agent=agent)
        controller.authenticate()
        self.assertEqual(
            agent.method_calls,
            [call.authenticated(), call.authenticate(), call.available()],
        )

    def test_retries(self):
        agent = AgentMock(authenticated=False, available=[False, True])
        controller = make_bamboo_agent_controller(agent=agent)
        controller.authenticate()
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
        agent = AgentMock(authenticated=False, available=False)
        controller = make_bamboo_agent_controller(
            agent=agent, timings=dict(authentication_timeout=0)
        )
        self.assertRaises(TimeoutError, controller.authenticate)

    def test_done_wait_in_check_mode(self):
        agent = AgentMock(check_mode=True, authenticated=False)
        controller = make_bamboo_agent_controller(agent=agent)
        controller.authenticate()
        self.assertEqual(
            agent.method_calls, [call.authenticated(), call.authenticate()],
        )


class TestSetEnabled(TestCase):
    def test_unchanged(self):
        agent = AgentMock()
        controller = make_bamboo_agent_controller(agent=agent)
        controller.set_enabled(None)
        self.assertEqual(agent.method_calls, [])

    def test_different(self):
        agent = AgentMock(enabled=True)
        controller = make_bamboo_agent_controller(agent=agent)
        controller.set_enabled(True)
        self.assertEqual(agent.method_calls, [call.enabled()])

    def test_enable(self):
        agent = AgentMock(enabled=False)
        controller = make_bamboo_agent_controller(agent=agent)
        controller.set_enabled(True)
        self.assertEqual(agent.method_calls, [call.enabled(), call.enable()])

    def test_disable(self):
        agent = AgentMock(enabled=True)
        controller = make_bamboo_agent_controller(agent=agent)
        controller.set_enabled(False)
        self.assertEqual(agent.method_calls, [call.enabled(), call.disable()])


class TestSetName(TestCase):
    def test_unchanged(self):
        agent = AgentMock()
        controller = make_bamboo_agent_controller(agent=agent)
        controller.set_name(None)
        self.assertEqual(agent.method_calls, [])

    def test_same(self):
        agent = AgentMock(name="agent-name")
        controller = make_bamboo_agent_controller(agent=agent)
        controller.set_name("agent-name")
        self.assertEqual(agent.method_calls, [call.name()])

    def test_different(self):
        agent = AgentMock(name="old-name")
        controller = make_bamboo_agent_controller(agent=agent)
        controller.set_name("new-name")
        self.assertEqual(agent.method_calls, [call.name(), call.set_name("new-name")])


class TestAssignments(TestCase):
    def test_unchanged(self):
        agent = AgentMock()
        controller = make_bamboo_agent_controller(agent=agent)
        controller.update_assignments(None)
        self.assertEqual(agent.method_calls, [])

    def test_keep_assignments(self):
        agent = AgentMock(assignments={1: "PROJECT", 2: "PLAN"})
        controller = make_bamboo_agent_controller(agent=agent)
        controller.update_assignments({1: "PROJECT", 2: "PLAN"})
        self.assertEqual(
            agent.method_calls, [call.assignments()],
        )

    def test_add_assignments(self):
        agent = AgentMock(assignments=dict())
        controller = make_bamboo_agent_controller(agent=agent)
        controller.update_assignments({1: "PROJECT", 2: "PLAN"})
        self.assertEqual(
            agent.method_calls,
            [
                call.assignments(),
                call.add_assignment("PROJECT", 1),
                call.add_assignment("PLAN", 2),
            ],
        )

    def test_delete_assignments(self):
        agent = AgentMock(assignments={1: "PROJECT", 2: "PLAN"})
        controller = make_bamboo_agent_controller(agent=agent)
        controller.update_assignments(dict())
        self.assertEqual(
            agent.method_calls,
            [
                call.assignments(),
                call.remove_assignment("PROJECT", 1),
                call.remove_assignment("PLAN", 2),
            ],
        )

    def test_update_assignments(self):
        agent = AgentMock(assignments={1: "PROJECT", 2: "PLAN"})
        controller = make_bamboo_agent_controller(agent=agent)
        controller.update_assignments({2: "PLAN", 3: "PROJECT"})
        self.assertEqual(
            agent.method_calls,
            [
                call.assignments(),
                call.add_assignment("PROJECT", 3),
                call.remove_assignment("PROJECT", 1),
            ],
        )


class TestBlockWhileBusy(TestCase):
    def test_agent_is_ready(self):
        agent = AgentMock(busy=False)
        controller = make_bamboo_agent_controller(
            agent=agent, timings=dict(busy_timeout=None, busy_polling_interval=0)
        )
        controller.block_while_busy()
        self.assertEqual(
            agent.method_calls, [call.busy()],
        )

    def test_wait_while_agent_is_busy(self):
        agent = AgentMock(busy=[True, False])
        controller = make_bamboo_agent_controller(
            agent=agent, timings=dict(busy_timeout=None, busy_polling_interval=0)
        )
        controller.block_while_busy()
        self.assertEqual(
            agent.method_calls, [call.busy(), call.busy()],
        )

    def test_timeout(self):
        agent = AgentMock(busy=True)
        controller = make_bamboo_agent_controller(
            agent=agent, timings=dict(busy_timeout=0, busy_polling_interval=0)
        )
        self.assertRaises(TimeoutError, controller.block_while_busy)

    def test_dont_block_in_check_mode(self):
        agent = AgentMock(busy=True, check_mode=True)
        controller = make_bamboo_agent_controller(
            agent=agent, timings=dict(busy_timeout=None, busy_polling_interval=0)
        )
        controller.block_while_busy()
