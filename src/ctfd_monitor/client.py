"""CTFd HTTP authentication, route negotiation and attachment access."""
from __future__ import annotations
import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser


class ApiError(RuntimeError):
    def __init__(self, path: str, status: int, message: str, code: str = "") -> None:
        super().__init__(f"{path}: HTTP {status} - {message}")
        self.path = path
        self.status = status
        self.message = message
        self.code = code


class NonceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.nonce = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "input" and values.get("name") == "nonce" and values.get("value"):
            self.nonce = str(values["value"])


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        request = super().redirect_request(req, fp, code, msg, headers, newurl)
        if request is not None:
            old = urllib.parse.urlsplit(req.full_url)
            new = urllib.parse.urlsplit(newurl)
            if (old.scheme, old.netloc) != (new.scheme, new.netloc):
                request.remove_header("Authorization")
                request.remove_header("Cookie")
        return request


class CTFdClient:
    def __init__(self, base_url: str, username: str, password: str, token: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.token = token
        self.retry_until = 0.0
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(SafeRedirect(), urllib.request.HTTPCookieProcessor(self.cookies))
        self.logged_in = False
        self.selected_routes: dict[tuple[str, ...], str] = {}

    def request_json(self, path: str, *, method: str = "GET", payload: dict[str, object] | None = None) -> dict[str, object]:
        if time.monotonic() < self.retry_until:
            raise ApiError(path, 429, "waiting for server Retry-After")
        data = None
        headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "ctfd-monitor/0.2.0"}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(urllib.parse.urljoin(self.base_url + "/", path.lstrip("/")), data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                try:
                    result = json.load(response)
                except (ValueError, UnicodeError) as error:
                    raise ApiError(path, 502, "expected a JSON response") from error
        except urllib.error.HTTPError as error:
            if error.code == 429:
                delay = 60.0
                raw = error.headers.get("Retry-After", "")
                try:
                    delay = float(raw)
                except ValueError:
                    try:
                        delay = (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds()
                    except (ValueError, TypeError, OverflowError):
                        pass
                if not 0 <= delay <= 86400:
                    delay = 60.0
                self.retry_until = time.monotonic() + delay
            body = error.read().decode("utf-8", errors="replace")
            try:
                result = json.loads(body)
            except json.JSONDecodeError:
                result = {}
            if not isinstance(result, dict):
                result = {}
            message = str(result.get("message") or result.get("code") or error.reason)
            raise ApiError(path, error.code, message, str(result.get("code") or "")) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise ApiError(path, 0, str(error)) from error
        if not isinstance(result, dict) or result.get("success") is not True:
            message = result.get("message") if isinstance(result, dict) else result
            raise ApiError(path, 400, str(message or "request failed"))
        return result

    def request_json_routes(self, paths: tuple[str, ...]) -> dict[str, object]:
        """Try API route variants, falling back only when a route is unavailable."""
        last_error: ApiError | None = None
        selected = self.selected_routes.get(paths)
        ordered = (selected,) + tuple(p for p in paths if p != selected) if selected else paths
        for path in ordered:
            try:
                result = self.request_json(path)
                self.selected_routes[paths] = path
                return result
            except ApiError as error:
                last_error = error
                route_unavailable = error.code == "route_not_allowed" or error.status in {404, 405}
                if not route_unavailable:
                    raise
        if last_error is not None:
            raise last_error
        raise ValueError("at least one API route is required")

    def login(self) -> dict[str, object]:
        if self.token:
            result = self.request_json("/api/v1/users/me")
            self.logged_in = True
            return result
        try:
            result = self.request_json("/api/v2/auth/login", method="POST", payload={"name": self.username, "password": self.password})
            self.logged_in = True
            return result
        except ApiError as error:
            if error.status not in {404, 405}:
                raise
        login_url = urllib.parse.urljoin(self.base_url + "/", "login")
        try:
            with self.opener.open(login_url, timeout=30) as response:
                page = response.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as error:
            raise ApiError("/login", 0, str(error)) from error
        parser = NonceParser()
        parser.feed(page)
        form = urllib.parse.urlencode({"name": self.username, "password": self.password, "nonce": parser.nonce}).encode("utf-8")
        request = urllib.request.Request(login_url, data=form, headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "ctfd-monitor/1.0"})
        try:
            with self.opener.open(request, timeout=30) as response:
                response.read(1)
            me = self.request_json("/api/v1/users/me")
        except (urllib.error.URLError, ApiError) as error:
            raise ApiError("/login", 401, "login failed") from error
        self.logged_in = True
        return {"success": True, "user": me.get("data", {})}

    def open_file(self, url: str, timeout: int = 10):
        target = urllib.parse.urljoin(self.base_url + "/", url)
        if urllib.parse.urlsplit(target).scheme not in {"http", "https"}:
            raise ValueError("attachments require an HTTP(S) URL")
        headers = {"User-Agent": "ctfd-monitor/0.2.0"}
        origin = urllib.parse.urlsplit(self.base_url)
        destination = urllib.parse.urlsplit(target)
        if self.token and (origin.scheme, origin.netloc) == (destination.scheme, destination.netloc):
            headers.update({"Authorization": f"Token {self.token}", "Content-Type": "application/json"})
        request = urllib.request.Request(target, headers=headers)
        return self.opener.open(request, timeout=timeout)


