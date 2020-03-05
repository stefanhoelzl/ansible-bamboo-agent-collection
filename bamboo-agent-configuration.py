#!/usr/bin/python

# Copyright: (c) 2020, Stefan Hoelzl <stefan.hoelzl@posteo.de>
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)

ANSIBLE_METADATA = {
    "metadata_version": "0.1",
    "status": ["preview"],
    "supported_by": "community",
}

DOCUMENTATION = """
---
module: bamboo-agent

short_description: bamboo agent registration

version_added: "2.9.5"

description:
- "Handles bamboo agent registraion. Allows agent assignments."

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
    authentication:
        description:
        - authentication information
        required: false
        type: dict
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
    assignments:
        description:
        - agent assignments
        required: false
        type: dict
        suboptions:
            type:
                description:
                - assignment type
                required: true
                type: str
                choices:
                - plan
                - project
            id:
                description:
                    - entity id for assignment
                required: true
                type: int
    timeouts:
        required: True
        type: dict
        suboptions:
            authentication:
                description:
                - timeout after the authentication fails if the agent does not show up in Bamboo
                required: False
                type: float
                default: 240

author:
    - Stefan Hoelzl (@stefanhoelzl)

seealso:
    - name: Bamboo REST API documentation
      link: https://docs.atlassian.com/atlassian-bamboo/REST/
"""

EXAMPLES = """
- name: agent registration
  bamboo-agent:
    host: https://bamboo-host
    home: /home/bamboo/bamboo-agent-home/
"""

RETURN = ""

import re
import ssl
import json
import time
import base64
from enum import Enum
from pathlib import Path
from urllib.parse import urljoin
import urllib.request as urlrequest
from typing import NamedTuple, List, Dict, Optional, Union, Tuple, Callable

from ansible.module_utils.basic import AnsibleModule

ArgumentSpec = dict(
    host=dict(type=str, required=True),
    home=dict(type=str, required=True),
    authentication=dict(
        type=dict,
        required=True,
        suboptions=dict(
            user=dict(type=str, required=True), password=dict(type=str, required=True),
        ),
    ),
    timeouts=dict(
        type=dict,
        required=False,
        suboptions=dict(authentication=dict(type=float, required=False, default=240.0)),
    ),
)


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
        self,
        path: str,
        method: Method = Method.Get,
        content: Content = None,
        header: Header = None,
    ):
        super().__init__(content)
        self.path = path
        self.method = method
        self.header = header or dict()

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


class HttpRequestHandler:
    def __init__(
        self, host: str, auth: Tuple[str, str], urlopen=urlrequest.urlopen,
    ):
        self.host = host
        self.auth = auth
        self._urlopen = urlopen

    def __call__(self, request: Request) -> Response:
        request = urlrequest.Request(
            urljoin(self.host, request.path), method=str(request.method)
        )
        user, passwd = self.auth
        auth_string = (
            base64.encodebytes(f"{user}:{passwd}".encode("utf-8"))
            .decode("ascii")
            .replace("\n", "")
        )
        request.add_header("Authorization", f"Basic {auth_string}")
        with self._urlopen(request, context=ssl.SSLContext()) as response:
            return Response(response.read(), status_code=response.getcode())


def timeout(query, timeout: float, interval: float = 1):
    start = time.time()
    while True:
        try:
            return query()
        except TimeoutError:
            if time.time() > start + timeout:
                raise
        time.sleep(interval)


class BambooAgentConfiguration:
    def __init__(
        self,
        host: str,
        home: str,
        authentication: Dict[str, str],
        timeouts: Dict[str, float] = dict(),
        request_handler=HttpRequestHandler,
    ):
        self.home = home
        self.timeouts = timeouts or dict()
        self.changed = False
        self.request_handler = request_handler(
            host=host, auth=(authentication["user"], authentication["password"])
        )

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

    def authentication_pending(self, uuid: str) -> bool:
        pending_agents = self.request(
            Request("/rest/api/latest/agent/authentication?pending=true")
        ).content
        uuid = next(filter(lambda pa: pa["uuid"] == uuid, pending_agents), {},).get(
            "uuid", None
        )
        return uuid is not None

    def register(self):
        uuid = self.uuid()
        if self.authentication_pending(uuid):
            self.request(
                Request(
                    f"/rest/api/latest/agent/authentication/{uuid}", method=Method.Put
                ),
                response_code=204,
            )

            def agent_available():
                agent_id = self.id()
                if agent_id is None:
                    raise TimeoutError("no id in config file found")
                else:
                    agents = self.request(Request("/rest/api/latest/agent/")).content
                    agent_found = any(
                        agent for agent in agents if agent["id"] == agent_id
                    )
                    if not agent_found:
                        raise TimeoutError("agent id not known by host")

            timeout(agent_available, timeout=self.timeouts.get("authentication", 240.0))
            self.changed = True

    def request(self, request: Request, response_code: int = 200) -> Response:
        response = self.request_handler(request)
        if response.status_code != response_code:
            raise ConnectionError(f"{response.status_code}: {request.path}")
        return response


def main():
    module = AnsibleModule(argument_spec=ArgumentSpec)
    bac = BambooAgentConfiguration(**module.params)
    bac.register()
    module.exit_json(changed=bac.changed)


if __name__ == "__main__":
    main()
