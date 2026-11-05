"""Tests for recorder/network_capture.py using synthetic CDP events (no
real browser needed -- NetworkCapture only depends on the CDP session
object having .send()/.on(), which we fake here)."""

from recorder.network_capture import NetworkCapture


class _FakeCDPSession:
    def __init__(self):
        self.sent = []
        self._handlers = {}

    def send(self, method, params=None):
        self.sent.append((method, params))
        return {}

    def on(self, event, handler):
        self._handlers[event] = handler

    def fire(self, event, payload):
        self._handlers[event](payload)


def test_enables_network_domain_on_construction():
    session = _FakeCDPSession()
    NetworkCapture(session)
    assert ("Network.enable", None) in session.sent


def test_request_without_response_has_null_status():
    session = _FakeCDPSession()
    capture = NetworkCapture(session)

    session.fire(
        "Network.requestWillBeSent",
        {
            "requestId": "req-1",
            "type": "XHR",
            "request": {"method": "GET", "url": "https://api.example.com/cart?token=abc"},
        },
    )

    events = capture.drain()
    assert len(events) == 1
    assert events[0]["method"] == "GET"
    assert events[0]["url_redacted"] == "https://api.example.com/cart?token=%5BTOKEN%5D"
    assert events[0]["status"] is None
    assert events[0]["resource_type"] == "XHR"
    assert events[0]["request_id"] == "req-1"
    assert events[0]["redacted_headers"] == []


def test_authorization_header_is_never_in_the_output_only_its_name():
    session = _FakeCDPSession()
    capture = NetworkCapture(session)
    session.fire(
        "Network.requestWillBeSent",
        {
            "requestId": "req-auth",
            "type": "XHR",
            "request": {
                "method": "GET",
                "url": "https://api.example.com/me",
                "headers": {"Authorization": "Bearer sk_live_super_secret_token"},
            },
        },
    )

    events = capture.drain()
    dump = str(events)
    assert "sk_live_super_secret_token" not in dump
    assert "Bearer" not in dump
    assert events[0]["redacted_headers"] == ["authorization"]


def test_cookie_and_set_cookie_headers_are_flagged_not_leaked():
    session = _FakeCDPSession()
    capture = NetworkCapture(session)
    session.fire(
        "Network.requestWillBeSent",
        {
            "requestId": "req-cookie",
            "type": "XHR",
            "request": {"method": "GET", "url": "https://x.test/", "headers": {"Cookie": "sessionid=abc123secret"}},
        },
    )
    session.fire(
        "Network.responseReceived",
        {"requestId": "req-cookie", "response": {"status": 200, "headers": {"Set-Cookie": "sid=xyz; HttpOnly"}}},
    )

    events = capture.drain()
    dump = str(events)
    assert "abc123secret" not in dump
    assert "sid=xyz" not in dump
    assert set(events[0]["redacted_headers"]) == {"cookie", "set-cookie"}


def test_ordinary_headers_are_not_flagged():
    session = _FakeCDPSession()
    capture = NetworkCapture(session)
    session.fire(
        "Network.requestWillBeSent",
        {
            "requestId": "req-plain",
            "type": "XHR",
            "request": {"method": "GET", "url": "https://x.test/", "headers": {"Accept": "application/json"}},
        },
    )
    events = capture.drain()
    assert events[0]["redacted_headers"] == []


def test_response_status_is_merged_in_before_drain():
    session = _FakeCDPSession()
    capture = NetworkCapture(session)

    session.fire(
        "Network.requestWillBeSent",
        {"requestId": "req-2", "type": "Fetch", "request": {"method": "POST", "url": "https://api.example.com/checkout"}},
    )
    session.fire("Network.responseReceived", {"requestId": "req-2", "response": {"status": 201}})

    events = capture.drain()
    assert events[0]["status"] == 201


def test_beacon_type_passes_through_as_resource_type():
    session = _FakeCDPSession()
    capture = NetworkCapture(session)
    session.fire(
        "Network.requestWillBeSent",
        {"requestId": "req-3", "type": "Ping", "request": {"method": "POST", "url": "https://track.example.com/beacon"}},
    )
    events = capture.drain()
    assert events[0]["resource_type"] == "Ping"


def test_drain_clears_the_buffer():
    session = _FakeCDPSession()
    capture = NetworkCapture(session)
    session.fire(
        "Network.requestWillBeSent",
        {"requestId": "req-4", "type": "Document", "request": {"method": "GET", "url": "https://example.com/"}},
    )
    first = capture.drain()
    second = capture.drain()
    assert len(first) == 1
    assert second == []


def test_response_after_drain_does_not_resurrect_the_event():
    session = _FakeCDPSession()
    capture = NetworkCapture(session)
    session.fire(
        "Network.requestWillBeSent",
        {"requestId": "req-5", "type": "XHR", "request": {"method": "GET", "url": "https://example.com/slow"}},
    )
    capture.drain()
    # Response arrives after the step that would have included it already
    # captured -- this must not raise, and must not leak into a future drain.
    session.fire("Network.responseReceived", {"requestId": "req-5", "response": {"status": 200}})
    assert capture.drain() == []


def test_no_request_id_is_ignored_without_crashing():
    session = _FakeCDPSession()
    capture = NetworkCapture(session)
    session.fire("Network.requestWillBeSent", {"type": "XHR", "request": {"method": "GET", "url": "https://x.test/"}})
    assert capture.drain() == []


def test_response_for_unknown_request_id_is_ignored():
    session = _FakeCDPSession()
    capture = NetworkCapture(session)
    session.fire("Network.responseReceived", {"requestId": "never-seen", "response": {"status": 500}})
    assert capture.drain() == []
