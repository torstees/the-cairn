from starlette.requests import Request

from cairn.templating import _user_context


def _request(state_user=None) -> Request:
    scope = {"type": "http", "headers": [], "query_string": b"", "path": "/", "method": "GET"}
    request = Request(scope)
    if state_user is not None:
        request.state.user = state_user
    return request


def test_user_context_returns_state_user_when_set() -> None:
    sentinel = object()
    assert _user_context(_request(sentinel)) == {"user": sentinel}


def test_user_context_defaults_to_none_when_unset() -> None:
    assert _user_context(_request()) == {"user": None}
