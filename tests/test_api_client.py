"""Tests for the HiLink API client.

Regression tests for EDGE_CASES.md items:
- #1  one lie-for-all HTTP failure → three distinct causes
- #4  mode switch response body never checked (HTTP 200 + XML error code)
- #11 token endpoint fallback hides that the device actually answered
"""

from __future__ import annotations

import pytest
import requests
import responses

from core.api_client import HiLinkApiClient
from utils.exceptions import (
    CableNotDataError,
    DeviceNotOnNetworkError,
    DeviceRejectedError,
    DeviceUnreachableError,
)

BASE = "http://192.168.8.1"


def client() -> HiLinkApiClient:
    return HiLinkApiClient(retry_delay=0)


class TestSessionToken:
    @responses.activate
    def test_fetches_token_from_ses_tok_info(self) -> None:
        responses.get(
            f"{BASE}/api/webserver/SesTokInfo",
            body="<response><SesInfo>SessionID=abc</SesInfo><TokInfo>tok123</TokInfo></response>",
        )
        c = client()
        assert c.fetch_token() == "tok123"
        assert c.session.headers["__RequestVerificationToken"] == "tok123"

    @responses.activate
    def test_falls_back_to_token_endpoint_on_404(self) -> None:
        responses.get(f"{BASE}/api/webserver/SesTokInfo", status=404)
        responses.get(f"{BASE}/api/webserver/token", body="<response>tok456</response>")
        assert client().fetch_token() == "tok456"

    @responses.activate
    def test_fallback_failure_keeps_device_rejected_context(self) -> None:
        """#11: both endpoints failing still means the device answered."""
        responses.get(f"{BASE}/api/webserver/SesTokInfo", status=404)
        responses.get(f"{BASE}/api/webserver/token", status=404)
        with pytest.raises(DeviceRejectedError):
            client().fetch_token()

    @responses.activate
    def test_ses_tok_info_without_token_raises(self) -> None:
        responses.get(f"{BASE}/api/webserver/SesTokInfo", body="<response></response>")
        with pytest.raises(DeviceRejectedError):
            client().fetch_token()

    @responses.activate
    def test_legacy_endpoint_without_token_raises(self) -> None:
        # Body deliberately carries no <tag>value</tag> pair, so there is no
        # token to extract. (A value like <response>tok456</response> *is* a
        # token — see test_falls_back_to_token_endpoint_on_404.)
        responses.get(f"{BASE}/api/webserver/SesTokInfo", status=404)
        responses.get(f"{BASE}/api/webserver/token", body="<response></response>")
        with pytest.raises(DeviceRejectedError):
            client().fetch_token()


# EDGE_CASES #1: the three HTTP failure shapes map to three different errors,
# each telling the user to fix a different thing.


class TestHttpFailureTaxonomy:
    @responses.activate
    def test_connection_refused_means_no_device(self) -> None:
        """#1: nothing at the address → DeviceNotOnNetworkError (cable advice)."""
        responses.get(
            f"{BASE}/api/webserver/SesTokInfo",
            body=requests.exceptions.ConnectionError("connection refused"),
        )
        with pytest.raises(DeviceNotOnNetworkError):
            client().fetch_token()

    @responses.activate
    def test_timeout_means_unreachable_not_cable(self) -> None:
        """#1: device on wrong IP / interface down → NOT the cable message."""
        responses.get(
            f"{BASE}/api/webserver/SesTokInfo",
            body=requests.exceptions.ConnectTimeout("timed out"),
        )
        with pytest.raises(DeviceUnreachableError):
            client().fetch_token()

    @responses.activate
    def test_http_500_means_device_answered_and_refused(self) -> None:
        """#1: device responded and rejected us → DeviceRejectedError, not cable."""
        responses.get(f"{BASE}/api/webserver/SesTokInfo", status=500)
        with pytest.raises(DeviceRejectedError) as exc_info:
            client().fetch_token()
        assert "500" in str(exc_info.value)

    @responses.activate
    def test_retry_on_transient_errors_only(self) -> None:
        """Timeouts/conn errors are retried; HTTP errors are not."""
        responses.get(
            f"{BASE}/api/webserver/SesTokInfo",
            body=requests.exceptions.ConnectionError("refused"),
        )
        c = client()
        with pytest.raises(DeviceNotOnNetworkError):
            c.fetch_token()
        assert len(responses.calls) == c.retries

    @responses.activate
    def test_cable_error_remains_backward_compatible_alias(self) -> None:
        responses.get(
            f"{BASE}/api/webserver/SesTokInfo",
            body=requests.exceptions.ConnectionError("connection refused"),
        )
        with pytest.raises(CableNotDataError):
            client().fetch_token()


# EDGE_CASES #4: HTTP 200 with a rejection XML body must not "succeed".


class TestModeSwitchBody:
    @responses.activate
    def _prepare(self) -> HiLinkApiClient:
        responses.get(
            f"{BASE}/api/webserver/SesTokInfo",
            body="<response><TokInfo>tok123</TokInfo></response>",
        )
        c = client()
        c.fetch_token()
        return c

    @responses.activate
    def test_ok_body_succeeds(self) -> None:
        responses.get(
            f"{BASE}/api/webserver/SesTokInfo",
            body="<response><TokInfo>tok123</TokInfo></response>",
        )
        responses.post(f"{BASE}/api/device/mode", body="<response>OK</response>")
        c = client()
        c.fetch_token()
        c.switch_to_mode_1()

    @responses.activate
    def test_error_code_body_is_rejected(self) -> None:
        """#4: <code>100003</code> with HTTP 200 must raise, not silently pass."""
        responses.get(
            f"{BASE}/api/webserver/SesTokInfo",
            body="<response><TokInfo>tok123</TokInfo></response>",
        )
        responses.post(f"{BASE}/api/device/mode", body="<response><code>100003</code></response>")
        c = client()
        c.fetch_token()
        with pytest.raises(DeviceRejectedError) as exc_info:
            c.switch_to_mode_1()
        assert "100003" in str(exc_info.value)

    @responses.activate
    def test_zero_error_code_is_success(self) -> None:
        responses.get(
            f"{BASE}/api/webserver/SesTokInfo",
            body="<response><TokInfo>tok123</TokInfo></response>",
        )
        responses.post(f"{BASE}/api/device/mode", body="<response><code>0</code></response>")
        c = client()
        c.fetch_token()
        c.switch_to_mode_1()  # must not raise

    @responses.activate
    def test_unrecognised_body_is_rejected(self) -> None:
        responses.get(
            f"{BASE}/api/webserver/SesTokInfo",
            body="<response><TokInfo>tok123</TokInfo></response>",
        )
        responses.post(f"{BASE}/api/device/mode", body="<response>garbage??</response>")
        c = client()
        c.fetch_token()
        with pytest.raises(DeviceRejectedError):
            c.switch_to_mode_1()

    @responses.activate
    def test_posts_mode_1_with_token_header(self) -> None:
        responses.get(
            f"{BASE}/api/webserver/SesTokInfo",
            body="<response><TokInfo>tok123</TokInfo></response>",
        )
        responses.post(f"{BASE}/api/device/mode", body="<response>OK</response>")
        c = client()
        c.fetch_token()
        c.switch_to_mode_1()
        request = responses.calls[1].request
        assert request.headers["__RequestVerificationToken"] == "tok123"
        assert "<mode>1</mode>" in request.body  # type: ignore[operator]
