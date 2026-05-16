"""mitmproxy addon: inject 5xx for first N Anthropic requests; resettable.

Control:
  curl 'http://localhost:8080/__reset__?n=3'           # set N=3, reset count
  curl 'http://localhost:8080/__reset__?n=2&status=503' # also override status
  curl 'http://localhost:8080/__state__'                # read current state
"""

import json
from urllib.parse import parse_qs, urlparse

from mitmproxy import http

state = {"N": 3, "count": 0, "status": 500}


def _state_response() -> http.Response:
    return http.Response.make(200, json.dumps(state).encode(), {"Content-Type": "application/json"})


def request(flow: http.HTTPFlow) -> None:
    if flow.request.path.startswith("/__reset__"):
        q = parse_qs(urlparse(flow.request.path).query)
        if "n" in q:
            state["N"] = int(q["n"][0])
        if "status" in q:
            state["status"] = int(q["status"][0])
        state["count"] = 0
        flow.response = _state_response()
        return

    if flow.request.path == "/__state__":
        flow.response = _state_response()
        return

    if "anthropic.com" in flow.request.host and state["count"] < state["N"]:
        state["count"] += 1
        flow.response = http.Response.make(
            state["status"],
            f"Injected {state['status']} (#{state['count']}/{state['N']})".encode(),
            {"Content-Type": "text/plain"},
        )
