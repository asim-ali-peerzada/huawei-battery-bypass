"""HiLink API client for Huawei/Zong Bolt+ devices."""

from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.parse import urljoin

import requests

from utils.exceptions import (
    DeviceNotOnNetworkError,
    DeviceRejectedError,
    DeviceUnreachableError,
)

logger = logging.getLogger("zerocell.api")

# Fixed private-LAN gateway address of the Huawei router; these devices expose
# only an HTTP admin interface, so HTTPS does not apply.
_DEFAULT_URL = "http://192.168.8.1"  # NOSONAR S1313,S5332
_MODE_BODY = "<request><mode>{mode}</mode></request>"
_TOKEN_RE = re.compile(r"<TokInfo>\s*(\S+)\s*</TokInfo>")
ANY_TOKEN_RE = re.compile(r"<(\w+)>(\S+)</\1>")
_CODE_RE = re.compile(r"<code>\s*(\d+)\s*</code>")


class HiLinkApiClient:
    def __init__(
        self,
        base_url: str = _DEFAULT_URL,
        session: requests.Session | None = None,
        retries: int = 3,
        retry_delay: float = 0.5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.retries = retries
        self.retry_delay = retry_delay

    def _url(self, path: str) -> str:
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = self.session.request(method, self._url(path), timeout=5, **kwargs)
                resp.raise_for_status()
                return resp
            except requests.HTTPError as exc:
                # The device answered and refused us — retrying will not help.
                raise DeviceRejectedError(f"HTTP {exc.response.status_code}") from exc
            except requests.Timeout as exc:
                last_exc = exc
                logger.debug("%s %s attempt %d timed out", method, path, attempt)
            except requests.ConnectionError as exc:
                last_exc = exc
                logger.debug("%s %s attempt %d refused", method, path, attempt)
            except requests.RequestException as exc:
                last_exc = exc
                logger.debug("%s %s attempt %d failed: %s", method, path, attempt, exc)
            if attempt < self.retries:
                time.sleep(self.retry_delay)

        if isinstance(last_exc, requests.Timeout):
            raise DeviceUnreachableError() from last_exc
        raise DeviceNotOnNetworkError() from last_exc

    def _get(self, path: str, **kwargs: Any) -> requests.Response:
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, body: str, **kwargs: Any) -> requests.Response:
        return self._request(
            "POST",
            path,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            **kwargs,
        )

    def fetch_token(self) -> str:
        try:
            resp = self._get("/api/webserver/SesTokInfo")
        except DeviceRejectedError as exc:
            if "404" not in str(exc.detail):
                raise
            # Older firmware has no SesTokInfo endpoint — use the legacy one.
            resp = self._get("/api/webserver/token")
            text = resp.text
            m = ANY_TOKEN_RE.search(text)
            if not m:
                raise DeviceRejectedError("no token in /token response") from None
            token = m.group(2)
            self.session.headers["__RequestVerificationToken"] = token
            logger.info("token acquired (legacy endpoint)")
            return token
        text = resp.text
        m = _TOKEN_RE.search(text)
        if not m:
            raise DeviceRejectedError("no token in SesTokInfo response")
        token = m.group(1)
        self.session.headers["__RequestVerificationToken"] = token
        logger.info("token acquired")
        return token

    def switch_to_mode_1(self) -> None:
        body = _MODE_BODY.format(mode=1)
        resp = self._post("/api/device/mode", body)
        self._check_mode_response(resp.text)

    @staticmethod
    def _check_mode_response(text: str) -> None:
        """Huawei returns HTTP 200 even for a rejected switch.

        A success body is ``<response>OK</response>``; a rejection carries a
        non-zero ``<code>``. Silence here means the later serial step fails with
        a misleading message, so we fail loudly at the right step instead.
        """
        code = _CODE_RE.search(text)
        if code and code.group(1) != "0":
            raise DeviceRejectedError(f"error code {code.group(1)}")
        if code:
            return
        if "OK" not in text.upper():
            raise DeviceRejectedError("unrecognised mode response")
        logger.info("switched to mode 1")

    def close(self) -> None:
        self.session.close()
