"""Bounded HTTPS reads from The Odds API; credentials never enter audit records."""

from datetime import datetime, timezone
from http.client import HTTPException
import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .. import __version__

HOST = "https://api.the-odds-api.com"
SPORT = "basketball_nba"
MARKET = "player_points"
MAX_BYTES = 8 * 1024 * 1024


class CaptureError(ValueError):
    """A fixed, credential-free message suitable for a user or manifest."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError
    return result


def quota(headers) -> dict:
    result = {}
    for label in ("remaining", "used", "last"):
        value = (headers or {}).get("x-requests-" + label)
        result[label] = int(value) if isinstance(value, str) and re.fullmatch(r"[0-9]{1,12}", value) else None
    return result


class Client:
    """Exactly one event-list call followed by at most one event-odds call.

    No retries, redirect following, environment proxy settings, or arbitrary
    endpoint/host overrides. Query-string authentication is required by this API.
    """

    def __init__(self, key: str):
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key):
            raise CaptureError("ODDS_API_KEY is missing or has an invalid format")
        self._key = key
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())
        self.requests = []

    def get(self, operation: str, event_id: str | None = None):
        if operation == "events" and not self.requests:
            path = f"/v4/sports/{SPORT}/events"
            parameters = {"dateFormat": "iso"}
        elif operation == "odds" and len(self.requests) == 1 and self.requests[0]["operation"] == "events":
            if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", event_id):
                raise CaptureError("Invalid event ID")
            path = f"/v4/sports/{SPORT}/events/{event_id}/odds"
            parameters = {"regions": "us", "markets": MARKET, "oddsFormat": "american", "dateFormat": "iso"}
        else:
            raise CaptureError("Capture request limit reached or invalid request order")
        parameters["apiKey"] = self._key
        request = Request(HOST + path + "?" + urlencode(parameters),
                          headers={"User-Agent": "odds-analysis/" + __version__})
        record = {"operation": operation, "status": "network_error", "quota": {}}
        self.requests.append(record)
        try:
            with self._opener.open(request, timeout=30) as response:
                record.update(status=response.status, quota=quota(response.headers))
                raw = response.read(MAX_BYTES + 1)
                captured_at = datetime.now(timezone.utc)
        except HTTPError as error:
            record.update(status=error.code, quota=quota(error.headers))
            error.close()
            raise CaptureError(f"Provider returned HTTP {record['status']}; no retry was attempted") from None
        except (URLError, OSError, TimeoutError, HTTPException):
            raise CaptureError("Provider request failed; billing may be unknown; no retry was attempted") from None
        if record["status"] != 200:
            raise CaptureError("Unexpected provider response status")
        if len(raw) > MAX_BYTES:
            raise CaptureError("Provider response exceeded the size limit")
        try:
            data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                              parse_constant=_reject_constant, parse_float=_finite_float)
            # Check both raw bytes and decoded strings (including JSON escapes).
            decoded = json.dumps(data, ensure_ascii=False)
            if self._key in decoded or self._key.encode() in raw:
                raise CaptureError("Provider response contained credential material; body was not saved")
        except (UnicodeError, ValueError) as error:
            if isinstance(error, CaptureError):
                raise
            raise CaptureError("Provider returned invalid JSON; body was not saved") from None
        return data, raw, captured_at
