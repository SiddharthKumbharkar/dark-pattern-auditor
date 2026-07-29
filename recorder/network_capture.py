"""CDP Network-domain request capture (Layer 1).

Uses the raw Chrome DevTools Protocol Network domain (via
BrowserContext.new_cdp_session) rather than Playwright's own
page.on("request")/page.on("response") events, per the interactive-v2
recorder's requirement to include XHR/fetch/beacon traffic reliably.
Stage 1 explicitly does not fetch or store request/response bodies.

Request/response HEADERS are read from the CDP events (needed to detect
Authorization/Cookie/bearer-token presence) but are held only in the
internal, transient `_events` buffer and are masked away by
recorder.masking.network_masker before drain() ever returns anything --
the public events this class hands out never carry a header value, only
`redacted_headers` (names).
"""

from typing import Dict, List, Optional

from recorder.masking.network_masker import mask_network_event


class NetworkCapture:
    """One instance per tracked page. Registers CDP Network listeners on
    construction and buffers events until drain() is called (once per
    captured step) -- "all network requests fired since the previous step"."""

    def __init__(self, cdp_session, query_param_denylist: Optional[List[str]] = None):
        self._session = cdp_session
        self._query_param_denylist = query_param_denylist
        self._events: Dict[str, Dict] = {}  # request_id -> RAW (pre-mask) event dict

        self._session.send("Network.enable")
        self._session.on("Network.requestWillBeSent", self._on_request_will_be_sent)
        self._session.on("Network.responseReceived", self._on_response_received)

    def _on_request_will_be_sent(self, event: Dict) -> None:
        request_id = event.get("requestId")
        request = event.get("request") or {}
        if not request_id:
            return
        self._events[request_id] = {
            "method": request.get("method", ""),
            "url": request.get("url", ""),
            "request_headers": request.get("headers") or {},
            "response_headers": None,
            # Filled in by _on_response_received if the response arrives
            # before this event is drained; otherwise stays null -- an
            # honest reflection of "not yet known at capture time", not a
            # failure.
            "status": None,
            "resource_type": event.get("type", ""),
            "request_id": request_id,
        }

    def _on_response_received(self, event: Dict) -> None:
        request_id = event.get("requestId")
        entry = self._events.get(request_id)
        if entry is None:
            return
        response = event.get("response") or {}
        entry["status"] = response.get("status")
        entry["response_headers"] = response.get("headers") or {}

    def drain(self) -> List[Dict]:
        """Returns every network event buffered since the last drain,
        masked (see recorder.masking.network_masker), and clears the
        buffer. A request whose response arrives after its event has
        already been drained will not have its status backfilled -- see
        the docstring on `status` in network_masker.mask_network_event."""
        raw_events = list(self._events.values())
        self._events.clear()
        return [mask_network_event(event, self._query_param_denylist) for event in raw_events]
