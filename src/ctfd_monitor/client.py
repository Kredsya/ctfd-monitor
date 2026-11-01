"""CTFd HTTP authentication, route negotiation and attachment access."""
from __future__ import annotations
import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from . import __version__


class ApiError(RuntimeError):
    def __init__(self, path: str, status: int, message: str, code: str = "") -> None:
        super().__init__(f"{path}: HTTP {status} - {message}")
        self.path = path
        self.status = status
        self.message = message
        self.code = code

    @property
    def competition_unavailable(self) -> bool:
        # HTTP 403 alone also means banned accounts, missing teams, etc.
        return self.status in {401, 403} and self.code in {
            'competition_closed', 'competition_not_started', 'competition_ended',
        }


class NonceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.nonce = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "input" and values.get("name") == "nonce" and values.get("value"):
            self.nonce = str(values["value"])


def normalize_contest_end(value: object) -> str:
    """Normalize CTFd Unix seconds or a timezone-qualified ISO deadline."""
    if value is None or value == "" or value == 0 and not isinstance(value, bool):
        return ""
    if isinstance(value, bool):
        raise ValueError("invalid contest end")
    if isinstance(value, (int, float)) or isinstance(value, str) and re.fullmatch(r"\d+(?:\.\d+)?", value):
        if float(value) == 0:
            return ""
        end = datetime.fromtimestamp(float(value), timezone.utc)
    elif isinstance(value, str):
        end = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if end.tzinfo is None:
            raise ValueError("contest end requires a timezone")
    else:
        raise ValueError("invalid contest end")
    return end.astimezone(timezone.utc).isoformat()


class ContestTimeParser(HTMLParser):
    """Read top-level window.init data without executing JavaScript."""
    def __init__(self):
        super().__init__()
        self.script = None
        self.found = False
        self.end = None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.script = ""

    def handle_data(self, data):
        if self.script is not None:
            self.script += data

    def handle_endtag(self, tag):
        if tag != "script" or self.script is None:
            return
        script, self.script = self.script, None
        match = re.search(r"\bwindow\.init\s*=\s*\{", script)
        if not match:
            return
        rest = script[match.end():].lstrip()
        decoder = json.JSONDecoder()
        while rest:
            key = re.match(r"(['\"])(\w+)\1\s*:\s*", rest)
            if not key:
                return
            try:
                value, offset = decoder.raw_decode(rest[key.end():])
            except ValueError:
                return
            if key[2] == "end":
                self.end, self.found = value, True
                return
            rest = rest[key.end() + offset:].lstrip()
            if not rest.startswith(","):
                return
            rest = rest[1:].lstrip()


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
        self.public_opener = urllib.request.build_opener(SafeRedirect())
        self.logged_in = False
        self.selected_routes: dict[tuple[str, ...], str] = {}

    def record_retry_after(self, headers) -> None:
        delay = 60.0
        raw = headers.get("Retry-After", "")
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

    def request_json(self, path: str, *, method: str = "GET", payload: dict[str, object] | None = None) -> dict[str, object]:
        target = urllib.parse.urljoin(self.base_url + "/", path.lstrip("/"))
        origin = urllib.parse.urlsplit(self.base_url)
        destination = urllib.parse.urlsplit(target)
        if (destination.scheme, destination.netloc) != (origin.scheme, origin.netloc):
            raise ValueError("API requests must stay on the configured CTFd origin")
        if time.monotonic() < self.retry_until:
            raise ApiError(path, 429, "waiting for server Retry-After")
        data = None
        headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": f"ctfd-monitor/{__version__}"}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(target, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                try:
                    result = json.load(response)
                except (ValueError, UnicodeError) as error:
                    raise ApiError(path, 502, "expected a JSON response") from error
        except urllib.error.HTTPError as error:
            if error.code == 429:
                self.record_retry_after(error.headers)
            body = error.read().decode("utf-8", errors="replace")
            try:
                result = json.loads(body)
            except json.JSONDecodeError:
                result = {}
            if not isinstance(result, dict):
                result = {}
            message = str(result.get("message") or result.get("code") or error.reason)
            code = str(result.get("code") or "")
            # Official CTFd 3.8.9's during_ctf_time_only emits a message, no code.
            # Restrict matching to challenge routes and exact measured messages.
            if not code and error.code == 403 and re.fullmatch(r'/api/v[12]/challenges(?:/\d+|/attempt)?', path):
                if re.fullmatch(r'.+ has not started yet', message):
                    code = 'competition_not_started'
                elif re.fullmatch(r'.+ has ended', message):
                    code = 'competition_ended'
            raise ApiError(path, error.code, message, code) from error
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

    def fetch_contest_end(self) -> str:
        try:
            data = self.request_json_routes(("/api/v2/config/", "/api/v2/config")).get("data")
        except ApiError as error:
            if error.status not in {404, 405} and error.code != "route_not_allowed":
                raise
        else:
            competition = data.get("competition") if isinstance(data, dict) else None
            if isinstance(competition, dict) and "end" in competition:
                try:
                    return normalize_contest_end(competition["end"])
                except (ValueError, OverflowError, OSError) as error:
                    raise ApiError("/api/v2/config", 502, "invalid contest end") from error
        # Stock CTFd exposes timing in window.init on its login page, even
        # before the event starts. A token does not need a browser login.
        if time.monotonic() < self.retry_until:
            raise ApiError("/login", 429, "waiting for server Retry-After")
        request = urllib.request.Request(self.base_url + "/login", headers={"User-Agent": f"ctfd-monitor/{__version__}"})
        try:
            with self.public_opener.open(request, timeout=10) as response:
                page = response.read(2 * 1024 * 1024 + 1)
            if len(page) > 2 * 1024 * 1024:
                raise ValueError("timing page too large")
            parser = ContestTimeParser()
            parser.feed(page.decode("utf-8"))
            if not parser.found:
                raise ValueError("public contest timing unavailable")
            return normalize_contest_end(parser.end)
        except urllib.error.HTTPError as error:
            if error.code == 429:
                self.record_retry_after(error.headers)
            raise ApiError("/login", error.code, "cannot read public contest timing") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise ApiError("/login", 0, "cannot read public contest timing") from error
        except (ValueError, OverflowError, OSError) as error:
            raise ApiError("/login", 502, "invalid public contest timing") from error

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
            try:
                with self.opener.open(request, timeout=30) as response:
                    response.read(1)
            except urllib.error.HTTPError as error:
                # Stock CTFd redirects a successful login to /challenges, which
                # is forbidden before start. Authenticate against users/me.
                if error.code != 403 or urllib.parse.urlsplit(error.url).path != '/challenges':
                    raise
            me = self.request_json("/api/v1/users/me")
        except (urllib.error.URLError, ApiError) as error:
            raise ApiError("/login", 401, "login failed") from error
        self.logged_in = True
        return {"success": True, "user": me.get("data", {})}

    def open_file(self, url: str, timeout: int = 10):
        target = urllib.parse.urljoin(self.base_url + "/", url)
        if urllib.parse.urlsplit(target).scheme not in {"http", "https"}:
            raise ValueError("attachments require an HTTP(S) URL")
        headers = {"User-Agent": f"ctfd-monitor/{__version__}"}
        origin = urllib.parse.urlsplit(self.base_url)
        destination = urllib.parse.urlsplit(target)
        if self.token and (origin.scheme, origin.netloc) == (destination.scheme, destination.netloc):
            headers.update({"Authorization": f"Token {self.token}", "Content-Type": "application/json"})
        request = urllib.request.Request(target, headers=headers)
        return self.opener.open(request, timeout=timeout)


