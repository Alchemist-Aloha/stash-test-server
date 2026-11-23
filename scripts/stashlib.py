"""Minimal stdlib-only Stash GraphQL client shared by seed.py and verify.py."""

from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class StashError(RuntimeError):
    pass


class Stash:
    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.cookies = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    # -- transport -------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["ApiKey"] = self.api_key
        return headers

    def gql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps({"query": query, "variables": variables or {}}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/graphql",
            data=body,
            headers={**self._headers(), "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise StashError(f"HTTP {e.code} from /graphql: {detail}") from e
        if payload.get("errors"):
            raise StashError(json.dumps(payload["errors"], indent=2))
        return payload["data"]

    def get(self, path_or_url: str, byte_range: str | None = None) -> tuple[int, bytes]:
        url = path_or_url if "://" in path_or_url else f"{self.base_url}{path_or_url}"
        headers = self._headers()
        if byte_range:
            headers["Range"] = byte_range
        req = urllib.request.Request(url, headers=headers)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return resp.status, resp.read(65536)
        except urllib.error.HTTPError as e:
            return e.code, b""

    def login(self, username: str, password: str) -> None:
        """Create a session cookie via Stash's form login endpoint."""
        form = urllib.parse.urlencode({"username": username, "password": password, "returnURL": "/"}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/login",
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401
                return None

        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies), NoRedirect)
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code  # a 302 surfaces here because redirects are disabled
        if status >= 400 or not any(True for _ in self.cookies):
            raise StashError(f"login failed for {username!r} (HTTP {status}, no session cookie)")

    # -- helpers ---------------------------------------------------------
    def wait_until_up(self, timeout: float = 120) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last: Exception | None = None
        while time.monotonic() < deadline:
            try:
                return self.gql("{ systemStatus { status databaseSchema appSchema ffmpegPath ffprobePath } }")["systemStatus"]
            except StashError as e:
                if "HTTP 401" in str(e):
                    return {"status": "AUTH_REQUIRED"}  # up, but credentials are already configured
                last = e
                time.sleep(1)
            except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
                last = e
                time.sleep(1)
        raise StashError(f"Stash did not respond at {self.base_url} within {timeout}s: {last}")

    def wait_for_job(self, job_id: str, label: str, timeout: float = 1800) -> None:
        deadline = time.monotonic() + timeout
        last_progress = -1.0
        while time.monotonic() < deadline:
            job = self.gql(
                "query($id: ID!) { findJob(input: {id: $id}) { status progress error description } }",
                {"id": job_id},
            )["findJob"]
            if job is None:  # finished jobs can be evicted from the queue
                return
            status = job["status"]
            if status == "FINISHED":
                print(f"  {label}: finished")
                return
            if status in {"FAILED", "CANCELLED"}:
                raise StashError(f"{label} job {status.lower()}: {job.get('error')}")
            progress = job.get("progress") or 0.0
            if progress - last_progress >= 0.1:
                print(f"  {label}: {progress:.0%}")
                last_progress = progress
            time.sleep(1)
        raise StashError(f"{label} job did not finish within {timeout}s")

    def wait_for_idle_queue(self, timeout: float = 1800) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            queue = self.gql("{ jobQueue { id status } }")["jobQueue"] or []
            if not [j for j in queue if j["status"] in {"READY", "RUNNING", "STOPPING"}]:
                return
            time.sleep(1)
        raise StashError("job queue did not drain")


def path_key(server_path: str, root: str) -> str | None:
    """Return the path relative to the `/<root>/` segment, using forward slashes."""
    norm = server_path.replace("\\", "/")
    marker = f"/{root}/"
    idx = norm.rfind(marker)
    return norm[idx + len(marker):] if idx >= 0 else None
