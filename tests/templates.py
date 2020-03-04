from .proxy import Request, Response, Method


class Pending:
    @staticmethod
    def request() -> Request:
        return Request("/rest/api/latest/agent/authentication?pending=true")

    @staticmethod
    def response(uuid: str) -> Response:
        return Response([dict(uuid=uuid)])


class Authentication:
    @staticmethod
    def request(uuid: str) -> Request:
        return Request(
            f"/rest/api/latest/agent/authentication/{uuid}", method=Method.Put
        )

    @staticmethod
    def response(status_code: int = 204) -> Response:
        return Response(status_code=status_code)
