from .proxy import Request, Response, Method
from . import ActionResponse


class Pending:
    @staticmethod
    def request() -> Request:
        return Request("/rest/api/latest/agent/authentication?pending=true")

    @staticmethod
    def response(uuid: str) -> Response:
        return ActionResponse([dict(uuid=uuid)])


class Authentication:
    @staticmethod
    def request(uuid: str) -> Request:
        return Request(
            f"/rest/api/latest/agent/authentication/{uuid}", method=Method.Put
        )

    @staticmethod
    def response(status_code: int = 204) -> Response:
        return ActionResponse(status_code=status_code)


class Agents:
    @staticmethod
    def request() -> Request:
        return Request("/rest/api/latest/agent/")

    @staticmethod
    def response(agents) -> Response:
        return ActionResponse(content=agents)


class Disable:
    @staticmethod
    def request(agent_id: int) -> Request:
        return Request(
            f"/admin/agent/disableAgent.action?agentId={agent_id}", method=Method.Post
        )

    @staticmethod
    def response() -> Response:
        return ActionResponse(status_code=302)


class Enable:
    @staticmethod
    def request(agent_id: int) -> Request:
        return Request(
            f"/admin/agent/enableAgent.action?agentId={agent_id}", method=Method.Post
        )

    @staticmethod
    def response() -> Response:
        return ActionResponse(status_code=302)
