#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2020, Stefan Hoelzl <stefan.hoelzl@posteo.de>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

ANSIBLE_METADATA = {
    "metadata_version": "1.1",
    "status": ["preview"],
    "supported_by": "community",
}

DOCUMENTATION = """
---
module: stefanhoelzl.bamboo_agent.configuration

short_description: bamboo agent configuration

version_added: "2.9.5"

description:
- "Handles bamboo remote agent configuration."
- "Supports agent authentication."
- "Supports agent assignments."
- "Supports enable/disable agent and setting name/description."

options:
    host:
        description:
        - bamboo host
        type: str
        required: true
    home:
        description:
        - path to bamboo-agent-home
        type: str
        required: true
    name:
        type: str
    enabled:
        type: bool
    assignments:
        description:
        - agent assignments
        type: list
        suboptions:
            type:
                description:
                - assignment type
                type: str
                required: true
                choices:
                - plan
                - project
            key:
                description:
                - entity key for assignment
                type: str
                required: true
    block_while_busy:
        description:
        - Waits while the agent is busy before finishing the task.
        - Recommended to enable the agent when using this option, otherwise it cannot be ensured that the agent picks up another job.
        type: bool
    deleted:
        description:
        - Deletes the agent from bamboo server if true.
        - If block_while_busy is true, the agent gets deleted when idle again.
        type: bool
        default: False
    credentials:
        description:
        - bamboo server authentication information
        type: dict
        required: true
        suboptions:
            user:
                description:
                - Username for authentication
                type: str
                required: true
            password:
                description:
                - Password for authentication
                type: str
                required: true
    timings:
        type: dict
        suboptions:
            http_timeout:
                description:
                - timeout for http requests in seconds
                type: float
                default: 10
            authentication_timeout:
                description:
                - seconds after the authentication fails if the agent does not show up in Bamboo
                type: float
                default: 240
            busy_timeout:
                type: float
            busy_polling_interval:
                description:
                - seconds between http request to check if agent is still busy
                type: float
                default: 60

author:
- Stefan Hoelzl (@stefanhoelzl)

seealso:
- name: Bamboo REST API documentation
  link: https://docs.atlassian.com/atlassian-bamboo/REST/latest
"""

EXAMPLES = """
- name: only agent authentication
  stefanhoelzl.bamboo_agent.configuration:
    host: https://bamboo-host
    home: /home/bamboo/bamboo-agent-home/
    credentials:
        user: "user"
        password: "{{ secret_password }}"
- name: agent configuration
  stefanhoelzl.bamboo_agent.configuration:
    host: https://bamboo-host
    home: /home/bamboo/bamboo-agent-home/
    name: "Agent Name"
    enabled: False
    credentials:
        user: "user"
        password: "{{ secret_password }}"
- name: agent assignment
  stefanhoelzl.bamboo_agent.configuration:
    host: https://bamboo-host
    home: /home/bamboo/bamboo-agent-home/
    assignments:
    - type: project
      key: PR
    - type: plan
      key: PR-PL
    credentials:
        user: "user"
        password: "{{ secret_password }}"
- name: block while agent is busy and then delete
  stefanhoelzl.bamboo_agent.configuration:
    host: https://bamboo-host
    home: /home/bamboo/bamboo-agent-home/
    block_while_busy: true
    deleted: true
    timings:
        busy_timoeut: 3600
        busy_polling_interval: 120
    credentials:
        user: "user"
        password: "{{ secret_password }}"
- name: custom timeout
  stefanhoelzl.bamboo_agent.configuration:
    host: https://bamboo-host
    home: /home/bamboo/bamboo-agent-home/
    timings:
        authentication: 600
    credentials:
        user: "user"
        password: "{{ secret_password }}"
"""

RETURN = """
id:
    type: int
    returned: success
name:
    type: str
    returned: success
active:
    type: bool
    returned: success
enabled:
    type: bool
    returned: success
active:
    type: bool
    returned: success
deleted:
    type: bool
    returned: success
assignments:
    type: dict
    suboptions:
        id:
            type: int
        type:
            type: str
            choices:
            - PLAN
            - PROJECT
    returned: success
"""

import re
import ssl
import json
import time
import base64
from enum import Enum
from pathlib import Path
from copy import deepcopy
from functools import lru_cache
import urllib.request as urlrequest
from typing import List, Dict, Optional, Union, Tuple

from ansible.module_utils.basic import AnsibleModule

ArgumentSpec = dict(
    host=dict(type=str, required=True),
    home=dict(type=str, required=True),
    name=dict(type=str),
    enabled=dict(type=bool),
    assignments=dict(
        type=list,
        suboptions=dict(
            type=dict(type=str, required=True, choices=["plan", "project"]),
            key=dict(type=str, required=True),
        ),
    ),
    block_while_busy=dict(type=bool),
    deleted=dict(type=bool, default=False),
    credentials=dict(
        type=dict,
        required=True,
        suboptions=dict(
            user=dict(type=str, required=True), password=dict(type=str, required=True),
        ),
    ),
    timings=dict(
        type=dict,
        suboptions=dict(
            http_timeout=dict(type=float, default=10),
            authentication_timeout=dict(type=float, default=240.0),
            busy_timeout=dict(type=float),
            busy_polling_interval=dict(type=float, default=60.0),
        ),
    ),
)


class BambooAgentError(Exception):
    pass


class RecoverableBambooAgentError(BambooAgentError):
    pass


class SelfRecoverableBambooAgentError(RecoverableBambooAgentError):
    pass


class ServerCommunicationError(RecoverableBambooAgentError):
    def __init__(self, request: "Request", response: "Response"):
        super().__init__(
            f"server communication faild (HTTP {response.status_code}): {request.method} {request.path} content={request.content}"
        )
        self.request = request
        self.response = response


class AgentBusy(SelfRecoverableBambooAgentError):
    pass


class MissingUuid(SelfRecoverableBambooAgentError):
    def __init__(self, home: str):
        super().__init__(f"No UUID found in {home}")
        self.home = home


class AssignmentNotFound(BambooAgentError):
    def __init__(self, etype: str, key: str):
        super().__init__(f"Assignment {etype} {key} not found!")
        self.etype = etype
        self.key = key


class Method(Enum):
    Get = "GET"
    Post = "POST"
    Put = "PUT"
    Delete = "DELETE"

    def __str__(self):
        return str(self.value)


Content = Optional[Union[bytes, List, Dict]]
JsonContent = Optional[Union[List, Dict]]
Header = Optional[Dict[str, str]]


class ContentContainer:
    def __init__(self, content: Content = None):
        self.content: JsonContent = (
            (json.loads(content.decode("utf-8")) if content else None)
            if isinstance(content, bytes)
            else content
        )

    def __bytes__(self) -> bytes:
        return (
            json.dumps(self.content).encode("utf-8")
            if self.content is not None
            else bytes()
        )


class Request(ContentContainer):
    def __init__(
        self, path: str, method: Method = Method.Get, content: Content = None,
    ):
        super().__init__(content)
        self.path = path
        self.method = method

    def __str__(self):
        return f"{self.method} {self.path}"


class Response(ContentContainer):
    def __init__(
        self, content: Content = None, status_code: int = 200, header: Header = None
    ):
        super().__init__(content)
        self.status_code = status_code
        self.header = header or dict()
        if self.content is not None:
            self.header["Content-Length"] = len(bytes(self))


class ForwardHttpError(urlrequest.HTTPErrorProcessor):
    def http_response(self, request, response):
        return response


urlopen_ignoring_redirect = urlrequest.build_opener(
    ForwardHttpError(), urlrequest.HTTPSHandler(context=ssl.SSLContext())
).open


class HttpRequestHandler:
    def __init__(
        self,
        host: str,
        auth: Tuple[str, str],
        timeout: float,
        urlopen=urlopen_ignoring_redirect,
    ):
        self.host = host
        self.auth = auth
        self.timeout = timeout
        self._urlopen = urlopen

    def __call__(self, request: Request, read: bool = True) -> Response:
        request = urlrequest.Request(
            "/".join((self.host.rstrip("/"), request.path.lstrip("/"))),
            method=str(request.method),
        )
        user, passwd = self.auth
        auth_string = (
            base64.encodebytes(f"{user}:{passwd}".encode("utf-8"))
            .decode("ascii")
            .replace("\n", "")
        )
        request.add_header("Authorization", f"Basic {auth_string}")
        request.add_header("X-Atlassian-Token", "no-check")
        with self._urlopen(request, timeout=self.timeout) as response:
            return Response(
                response.read() if read else None, status_code=response.getcode()
            )


def retry(query, timeout: Optional[float], interval: float, msg: Optional[str] = None):
    start = time.time()
    while True:
        try:
            return query()
        except SelfRecoverableBambooAgentError:
            if timeout is not None and time.time() > start + timeout:
                raise TimeoutError(f"Timeout: {msg or ''} ({timeout:.2f} sec)")
        time.sleep(interval)


class State:
    def __init__(self, **initial):
        self.initial = initial
        self.current = deepcopy(self.initial)

    @property
    def changed(self):
        return self.current != self.initial

    def set(self, key, value):
        if key not in self.initial:
            self.initial[key] = deepcopy(value)
        self.current[key] = value

    def __getitem__(self, key):
        if key not in self.current:
            self.set(key, dict())
        return self.current[key]


def _update_state(key: str):
    def decorator(fn):
        def wrapper(self, *args, **kwargs):
            self.state.set(key, fn(self, *args, **kwargs))
            return self.state[key]

        return wrapper

    return decorator


class BambooAgent:
    def __init__(
        self,
        host: str,
        home: str,
        credentials: Dict[str, str],
        http_timeout: int,
        request_handler=HttpRequestHandler,
        check_mode: bool = False,
    ):
        self.home = home
        self.check_mode = check_mode
        self.state = State(deleted=False)
        self.request_handler = request_handler(
            host=host,
            auth=(credentials["user"], credentials["password"]),
            timeout=http_timeout,
        )

    @lru_cache()
    def _search_assignments(self, etype):
        return self.request(
            Request(
                f"/rest/api/latest/agent/assignment/search?searchTerm=&executorType=AGENT&entityType={etype}"
            )
        ).content["searchResults"]

    @lru_cache()
    @_update_state("info")
    def info(self):
        agents = self.request(Request("/rest/api/latest/agent/")).content
        return next((agent for agent in agents if agent["id"] == self.id()), None)

    def request(
        self,
        request: Request,
        allow_redirect: bool = False,
        read_response_data: bool = True,
    ) -> Response:
        expected_status_code = (
            204 if request.method in [Method.Put, Method.Delete] else 200
        )
        response = self.request_handler(request, read=read_response_data)
        valid_redirect = allow_redirect and response.status_code == 302
        if (response.status_code == expected_status_code) or valid_redirect:
            return response
        raise ServerCommunicationError(request, response)

    def change(self, request: Request, state_update, allow_redirect=False):
        if not self.check_mode:
            self.request(
                request, allow_redirect=allow_redirect, read_response_data=False
            )
        if state_update:
            state_update(self.state)

    def uuid(self) -> Optional[str]:
        config_file = Path(self.home, "bamboo-agent.cfg.xml")
        if config_file.is_file():
            uuid_pattern = "<agentUuid>([A-z0-9-]+)</agentUuid>"
            return re.search(uuid_pattern, config_file.read_text()).group(1)

        uuid_file = Path(self.home, "uuid-temp.properties")
        if uuid_file.is_file():
            return re.search("agentUuid=([A-z0-9-]+)$", uuid_file.read_text()).group(1)

        return None

    def id(self) -> Optional[int]:
        config_file = Path(self.home, "bamboo-agent.cfg.xml")
        if config_file.is_file():
            id_pattern = "<id>([0-9]+)</id>"
            match = re.search(id_pattern, config_file.read_text())
            if match:
                return int(match.group(1))
        return None

    @_update_state("authenticated")
    def authenticated(self) -> bool:
        uuid = self.uuid()
        if uuid is None:
            return False
        pending_agents = self.request(
            Request("/rest/api/latest/agent/authentication?pending=true")
        ).content
        uuid = next(filter(lambda pa: pa["uuid"] == uuid, pending_agents), {},).get(
            "uuid", None
        )
        if uuid is None:
            return self.available()
        return False

    def available(self) -> bool:
        aid = self.id()
        if aid is None:
            return False
        self.info.cache_clear()
        return self.info() is not None

    def authenticate(self):
        uuid = self.uuid()
        if uuid is None:
            raise MissingUuid(self.home)
        self.change(
            Request(
                f"/rest/api/latest/agent/authentication/{uuid}", method=Method.Put,
            ),
            state_update=lambda state: state.set("authenticated", True),
        )

    def enabled(self) -> bool:
        return self.info()["enabled"]

    def disable(self):
        self.change(
            Request(
                f"/admin/agent/disableAgent.action?agentId={self.id()}",
                method=Method.Post,
            ),
            state_update=lambda state: state["info"].__setitem__("enabled", False),
            allow_redirect=True,
        )

    def enable(self):
        self.change(
            Request(
                f"/admin/agent/enableAgent.action?agentId={self.id()}",
                method=Method.Post,
            ),
            state_update=lambda state: state["info"].__setitem__("enabled", True),
            allow_redirect=True,
        )

    def delete(self):
        self.change(
            Request(
                f"/admin/agent/removeAgent.action?agentId={self.id()}",
                method=Method.Post,
            ),
            state_update=lambda state: state.set("deleted", True),
            allow_redirect=True,
        )

    def busy(self):
        self.info.cache_clear()
        return self.info()["busy"]

    def name(self) -> str:
        return self.info()["name"]

    def set_name(self, name: str):
        self.change(
            Request(
                f"/admin/agent/updateAgentDetails.action?agentId={ self.id() }&agentName={ name }&save=Update",
                method=Method.Post,
            ),
            state_update=lambda state: state["info"].__setitem__("name", name),
            allow_redirect=True,
        )

    @lru_cache()
    @_update_state("assignments")
    def assignments(self) -> Dict[int, str]:
        return {
            assignment["executableId"]: assignment["executableType"]
            for assignment in self.request(
                Request(
                    f"/rest/api/latest/agent/assignment?executorType=AGENT&executorId={ self.id() }"
                )
            ).content
        }

    def add_assignment(self, etype: str, eid: int):
        self.change(
            Request(
                f"/rest/api/latest/agent/assignment?executorType=AGENT&executorId={ self.id() }&assignmentType={ etype }&entityId={ eid }",
                method=Method.Post,
            ),
            state_update=lambda state: state["assignments"].__setitem__(eid, etype),
        )

    def remove_assignment(self, etype: str, eid: int):
        self.change(
            Request(
                f"/rest/api/latest/agent/assignment?executorType=AGENT&executorId={ self.id() }&assignmentType={ etype }&entityId={ eid }",
                method=Method.Delete,
            ),
            state_update=lambda state: state["assignments"].pop(eid),
        )

    def resolve_assignments(
        self, assignments: Optional[List[Dict[str, str]]]
    ) -> Optional[Dict[int, str]]:
        if assignments is None:
            return None

        resolved = dict()
        for assignment in assignments:
            key, etype = assignment["key"], assignment["type"].upper()
            eid = next(
                (
                    result["searchEntity"]["id"]
                    for result in self._search_assignments(etype)
                    if result["id"] == key
                ),
                None,
            )
            if eid is None:
                raise AssignmentNotFound(etype, key)
            resolved[eid] = etype
        return resolved


class BambooAgentController:
    def __init__(
        self, agent: BambooAgent, timings: Dict[str, float] = None,
    ):
        self.agent = agent
        self.timings = timings or dict()

    def authenticate(self):
        if not self.agent.authenticated():
            self.agent.authenticate()

            def available():
                if not self.agent.available():
                    raise SelfRecoverableBambooAgentError()

            if not self.agent.check_mode:
                retry(
                    available,
                    timeout=self.timings.get("authentication_timeout", 240),
                    interval=1.0,
                    msg="agent not available after authentication",
                )

    def set_enabled(self, enabled: Optional[bool]):
        if enabled is not None and enabled != self.agent.enabled():
            if enabled:
                self.agent.enable()
            else:
                self.agent.disable()

    def set_name(self, name: Optional[str]):
        if name is not None and self.agent.name() != name:
            self.agent.set_name(name)

    def update_assignments(self, assignments: Optional[Dict[int, str]]):
        if assignments is None:
            return

        current_assignments = self.agent.assignments()
        if current_assignments != assignments:
            all(
                self.agent.add_assignment(etype, eid)
                for eid, etype in assignments.items()
                if eid not in current_assignments
            )
            all(
                self.agent.remove_assignment(etype, eid)
                for eid, etype in current_assignments.items()
                if eid not in assignments
            )

    def block_while_busy(self):
        def block():
            if self.agent.busy():
                raise AgentBusy()

        if not self.agent.check_mode:
            retry(
                block,
                timeout=self.timings.get("busy_timeout", None),
                interval=self.timings.get("busy_polling_interval", 60),
                msg="agent busy",
            )


def main():
    module = AnsibleModule(argument_spec=ArgumentSpec, supports_check_mode=True)

    enabled = module.params.pop("enabled")
    delete = module.params.pop("deleted")
    name = module.params.pop("name")
    assignments = module.params.pop("assignments")
    should_block_while_busy = module.params.pop("block_while_busy")
    timings = module.params.pop("timings") or dict()
    http_timeout = timings.pop("http_timeout", 10)

    controller = BambooAgentController(
        agent=BambooAgent(
            host=module.params.pop("host"),
            home=module.params.pop("home"),
            credentials=module.params.pop("credentials"),
            http_timeout=http_timeout,
            check_mode=module.check_mode,
        ),
        timings=timings,
        **module.params,
    )
    try:
        controller.authenticate()
        controller.set_enabled(enabled)
        controller.set_name(name)
        controller.update_assignments(controller.agent.resolve_assignments(assignments))
        if should_block_while_busy:
            controller.block_while_busy()
        if delete:
            controller.agent.delete()
    except (BambooAgentError, urlrequest.URLError) as error:
        module.fail_json(msg=str(error))

    module.exit_json(
        changed=controller.agent.state.changed,
        authenticated=controller.agent.state["authenticated"],
        assignments=controller.agent.state["assignments"],
        deleted=controller.agent.state["deleted"],
        diff=dict(
            before=json.dumps(controller.agent.state.initial, indent=4, sort_keys=True),
            after=json.dumps(controller.agent.state.current, indent=4, sort_keys=True),
        ),
        **(controller.agent.state["info"] or dict()),
    )


if __name__ == "__main__":
    main()
