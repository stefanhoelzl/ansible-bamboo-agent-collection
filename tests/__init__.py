import shutil
import socket
import unittest
import textwrap
from pathlib import Path
from .proxy import Request, Response
from typing import List, Optional, Callable
from contextlib import contextmanager
from tempfile import TemporaryDirectory

IpAddress = socket.gethostbyname(socket.gethostname())

Action = Callable[[], None]


class ActionResponse(Response):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._action: Optional[Action] = None

    def action(self, action: Action):
        self._action = action
        return self

    def __call__(self):
        if self._action is not None:
            self._action()


class RequestTestCase(unittest.TestCase):
    def assert_requests(self, requests: List[Request], *expected_requests: Request):
        for index, expected in enumerate(expected_requests):
            if len(requests) <= index:
                raise AssertionError(f"missing request ({index}): {expected}")
            requests[index].header.pop("Authorization", None)

            self.assertEqual(requests[index].path, expected.path, msg=f"index: {index}")
            self.assertEqual(
                requests[index].method, expected.method, msg=f"index: {index}"
            )
            self.assertEqual(
                requests[index].header, expected.header, msg=f"index: {index}"
            )
            self.assertEqual(
                requests[index].content, expected.content, msg=f"index: {index}"
            )
            self.assertEqual(
                requests[index].__dict__, expected.__dict__, msg=f"index: {index}"
            )


class BambooHome:
    def __init__(self):
        self.files = {}
        self.path = None

    def file(self, filename: str, content: str) -> "BambooHome":
        self.files[filename] = content
        return self

    def temp_uuid(self, uuid: str) -> "BambooHome":
        content = textwrap.dedent(
            f"""
                #Agent UUID stored here temporarily until the agent is approved
                #Mon Mar 02 18:15:15 GMT 2020
                agentUuid={uuid}
            """.strip()
        )
        return self.file("uuid-temp.properties", content)

    def config(
        self,
        uuid: str = "0000",
        aid: Optional[int] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> "BambooHome":
        content = textwrap.dedent(
            f"""
                <?xml version="1.0" encoding="UTF-8" standalone="no"?>
                <configuration>
                <buildWorkingDirectory>?????</buildWorkingDirectory>
                <agentUuid>{ uuid }</agentUuid>
                <agentDefinition>
            """.lstrip()
        )
        if aid:
            content += f"<id>{ aid }</id>\n"
        if name:
            content += f"<name>{ name }</name>\n"
        if description:
            content += f"<description>{ description }</description>\n"
        content += textwrap.dedent(
            """
        </agentDefinition>
        </configuration>
        """.lstrip()
        )

        return self.file("bamboo-agent.cfg.xml", content)

    @contextmanager
    def temp(self):
        with TemporaryDirectory() as tempdir:
            yield self.create(Path(tempdir))

    def create(self, path) -> Path:
        path = Path(path)
        if path.name != "bamboo-agent-home":
            path = path / "bamboo-agent-home"
        shutil.rmtree(str(path), ignore_errors=True)
        path.mkdir(parents=True)
        for filename, content in self.files.items():
            (path / filename).write_text(content)
        self.path = path
        return path

