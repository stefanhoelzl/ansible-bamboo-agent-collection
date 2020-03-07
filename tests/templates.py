from plugins.modules.configuration import Request, Response, Method
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


class SetName:
    @staticmethod
    def request(agent_id: int, name: str) -> Request:
        return Request(
            f"/admin/agent/updateAgentDetails.action?agentId={ agent_id }&agentName={ name }&save=Update",
            method=Method.Post,
        )

    @staticmethod
    def response() -> Response:
        return ActionResponse(status_code=302)


class Assignments:
    @staticmethod
    def request(agent_id: int) -> Request:
        return Request(
            f"/rest/api/latest/agent/assignment?executorType=AGENT&executorId={ agent_id }"
        )

    @staticmethod
    def response(assignments: list) -> Response:
        return ActionResponse(content=assignments)


class AddAssignment:
    @staticmethod
    def request(agent_id: int, etype: str, eid: int) -> Request:
        return Request(
            f"/rest/api/latest/agent/assignment?executorType=AGENT&executorId={ agent_id }&assignmentType={ etype }&entityId={ eid }",
            method=Method.Post,
        )

    @staticmethod
    def response() -> Response:
        return ActionResponse()


class RemoveAssignment:
    @staticmethod
    def request(agent_id: int, etype: str, eid: int) -> Request:
        return Request(
            f"/rest/api/latest/agent/assignment?executorType=AGENT&executorId={ agent_id }&assignmentType={ etype }&entityId={ eid }",
            method=Method.Delete,
        )

    @staticmethod
    def response() -> Response:
        return ActionResponse(status_code=204)


class SearchAssignment:
    @staticmethod
    def request(etype: str) -> Request:
        return Request(
            f"/rest/api/latest/agent/assignment/search?searchTerm=&executorType=AGENT&entityType={ etype }",
        )

    @staticmethod
    def response(results: list) -> Response:
        return ActionResponse(
            content=dict(
                size=len(results),
                searchResults=[
                    dict(id=r["key"], searchEntity=dict(id=r["id"])) for r in results
                ],
            )
        )
