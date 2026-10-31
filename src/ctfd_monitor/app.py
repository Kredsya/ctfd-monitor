#!/usr/bin/env python3
"""Live CTFd challenge monitor and downloader with competition profiles."""

from __future__ import annotations

from .archives import extract

import argparse
import tomllib
import concurrent.futures
import copy
import fcntl
import hashlib
import html
import http.cookiejar
import json
import math
import os
import re
import select
import signal
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


TEST_MODE = os.environ.get("CTFD_MONITOR_TEST") == "1"
BASE_URL = os.environ.get("CTFD_MONITOR_URL", "")
USERNAME = os.environ.get("CTFD_MONITOR_USER", "")
PASSWORD = os.environ.get("CTFD_MONITOR_PASSWORD", "")
TOKEN = os.environ.get("CTFD_MONITOR_TOKEN", "")
TITLE = "CTFd Monitor"
KOTH_ENABLED = False
CODEX_ENABLED = False
AGENTS_TEMPLATE = None
AUTO_EXTRACT = False
MAX_DOWNLOAD_BYTES = 2 * 1024**3
HEADLESS = False
CONTEST_END = ""
POLL_INTERVAL = 0.5 if TEST_MODE else 5.0
BADGE_TTL = 5.0 if TEST_MODE else 300.0
DONE_TTL = 5.0
MAX_WORKERS = 4
UI_REFRESH_INTERVAL = 1.0
RESOURCE_SAMPLE_INTERVAL = 1.0
RESOURCE_HISTORY_SECONDS = 120.0
RESOURCE_MAX_BUCKET_SECONDS = RESOURCE_HISTORY_SECONDS / 8
RESOURCE_RETENTION_SECONDS = RESOURCE_HISTORY_SECONDS + RESOURCE_MAX_BUCKET_SECONDS
RESOURCE_HISTORY_SAMPLES = int(RESOURCE_RETENTION_SECONDS / RESOURCE_SAMPLE_INTERVAL) + 2

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = Path(os.environ.get("CTFD_MONITOR_ROOT", SCRIPT_DIR))
STATE_DIR = Path(os.environ.get("CTFD_MONITOR_STATE", BASE_DIR / ".ctfd-monitor"))
CURRENT_FILE = STATE_DIR / "current.json"
EVENT_FILE = STATE_DIR / "events.jsonl"
SNAPSHOT_DIR = STATE_DIR / "snapshots"
ARCHIVE_DIR = STATE_DIR / "archive"
MANIFEST_FILE = STATE_DIR / "manifest.json"
KOTH_FILE = STATE_DIR / "koth.json"
CODEX_USAGE_FILE = STATE_DIR / "codex-usage.json"
LOCK_FILE = STATE_DIR / "monitor.lock"
STAGING_DIR = STATE_DIR / "staging"
HELPER_FILES = ()
KOTH_POLL_INTERVAL = 2.0 if TEST_MODE else 10.0
KOTH_MAX_POINTS = 1500.0
CODEX_USAGE_POLL_INTERVAL = 10.0 if TEST_MODE else 12.0
SOLVE_POLL_INTERVAL = 2.0 if TEST_MODE else 10.0
CONFIG_POLL_INTERVAL = 10.0 if TEST_MODE else 60.0
MIN_TERMINAL_COLUMNS = 109
MIN_TERMINAL_ROWS = 54

ESC = "\033["
RESET = f"{ESC}0m"
BOLD = f"{ESC}1m"
RED = f"{ESC}38;5;203m"
GREEN = f"{ESC}38;5;84m"
YELLOW = f"{ESC}38;5;220m"
CYAN = f"{ESC}38;5;45m"
BLUE = f"{ESC}38;5;75m"
GRAY = f"{ESC}38;5;245m"
WHITE = f"{ESC}38;5;255m"
GREEN_BG = f"{ESC}48;5;22m"
RED_BG = f"{ESC}48;5;88m"
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PARTIAL_BLOCKS = " ▁▂▃▄▅▆▇█"


class ApiError(RuntimeError):
    def __init__(self, path: str, status: int, message: str, code: str = "") -> None:
        super().__init__(f"{path}: HTTP {status} - {message}")
        self.path = path
        self.status = status
        self.message = message
        self.code = code


class DescriptionParser(HTMLParser):
    BLOCK_TAGS = {
        "address", "article", "blockquote", "br", "div", "h1", "h2", "h3",
        "h4", "h5", "h6", "hr", "li", "ol", "p", "pre", "section", "table",
        "tr", "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        value = html.unescape("".join(self.parts)).replace("\r\n", "\n")
        value = re.sub(r"[ \t]+\n", "\n", value)
        return re.sub(r"\n{3,}", "\n\n", value).strip()


class NonceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.nonce = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "input" and values.get("name") == "nonce" and values.get("value"):
            self.nonce = str(values["value"])


def paint(text: str, color: str, *, bold: bool = False) -> str:
    return f"{BOLD if bold else ''}{color}{text}{RESET}"


def display_width(text: str) -> int:
    width = 0
    for character in ANSI_RE.sub("", text):
        if unicodedata.combining(character):
            continue
        width += 2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
    return width


def truncate(text: str, width: int) -> str:
    if display_width(text) <= width:
        return text
    result: list[str] = []
    used = 0
    position = 0
    while position < len(text):
        ansi = ANSI_RE.match(text, position)
        if ansi:
            result.append(ansi.group())
            position = ansi.end()
            continue
        character = text[position]
        character_width = 0 if unicodedata.combining(character) else (2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1)
        if used + character_width > max(0, width - 1):
            break
        result.append(character)
        used += character_width
        position += 1
    return "".join(result) + "…" + RESET


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def boxed(title: str, lines: list[str], width: int, color: str) -> list[str]:
    label = f" {truncate(title, max(1, width - 4))} "
    output = [paint("┌" + label + "─" * max(0, width - display_width(label) - 2) + "┐", color, bold=True)]
    inner = width - 2
    for line in lines or [""]:
        line = truncate(line, inner - 2)
        output.append(paint("│", color) + " " + pad(line, inner - 1) + paint("│", color))
    output.append(paint("└" + "─" * (width - 2) + "┘", color))
    return output


def description_text(value: object) -> str:
    parser = DescriptionParser()
    parser.feed(str(value or ""))
    return parser.text()


def safe_directory_name(value: object) -> str:
    name = re.sub(r"\s+", "_", str(value).strip())
    name = re.sub(r"[/\x00-\x1f\x7f]", "_", name)
    if name in {"", ".", ".."}:
        name = "unnamed_challenge"
    encoded = name.encode("utf-8")
    if len(encoded) > 220:
        name = encoded[:220].decode("utf-8", errors="ignore").rstrip("._ ")
    return name or "unnamed_challenge"


def safe_file_name(value: str, fallback: str) -> str:
    name = Path(urllib.parse.unquote(value)).name
    name = re.sub(r"[/\\\x00-\x1f\x7f]", "_", name).strip()
    return name if name not in {"", ".", ".."} else fallback


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def timestamp_name() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DownloadCancelled(RuntimeError):
    pass


class InstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.handle.close()
            self.handle = None
            return False
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(f"{os.getpid()}\n")
        self.handle.flush()
        return True

    def release(self) -> None:
        if self.handle is None:
            return
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None


def legacy_monitor_running() -> bool:
    """Detect a monitor started before lock-file support was loaded."""
    if TEST_MODE:
        return False
    script = Path(__file__).resolve()
    for process in Path("/proc").glob("[0-9]*"):
        if process.name == str(os.getpid()):
            continue
        try:
            arguments = [value for value in (process / "cmdline").read_bytes().split(b"\0") if value]
            working_directory = (process / "cwd").resolve()
        except OSError:
            continue
        for argument in arguments[1:]:
            try:
                candidate = Path(os.fsdecode(argument))
                if not candidate.is_absolute():
                    candidate = working_directory / candidate
                if candidate.resolve() == script:
                    return True
            except (OSError, UnicodeError):
                continue
    return False


def file_url(entry: object) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        for key in ("url", "path", "location"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def is_koth_challenge(challenge: object) -> bool:
    if not isinstance(challenge, dict):
        return False
    return str(challenge.get("type") or "").casefold() == "koth_challenge" or str(challenge.get("category") or "").casefold() == "koth"


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
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(SafeRedirect(), urllib.request.HTTPCookieProcessor(self.cookies))
        self.logged_in = False

    def request_json(self, path: str, *, method: str = "GET", payload: dict[str, object] | None = None) -> dict[str, object]:
        data = None
        headers = {"Accept": "application/json", "User-Agent": "ctfd-monitor/1.0"}
        if TOKEN:
            headers["Authorization"] = f"Token {TOKEN}"
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
            body = error.read().decode("utf-8", errors="replace")
            try:
                result = json.loads(body)
            except json.JSONDecodeError:
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
        for path in paths:
            try:
                return self.request_json(path)
            except ApiError as error:
                last_error = error
                route_unavailable = error.code == "route_not_allowed" or error.status in {404, 405}
                if not route_unavailable:
                    raise
        if last_error is not None:
            raise last_error
        raise ValueError("at least one API route is required")

    def login(self) -> dict[str, object]:
        if TOKEN:
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

    def cookie_header(self) -> str:
        return "; ".join(f"{cookie.name}={cookie.value}" for cookie in self.cookies)

    def open_file(self, url: str, timeout: int = 10):
        request = urllib.request.Request(urllib.parse.urljoin(self.base_url + "/", url), headers={"User-Agent": "ctfd-monitor/1.0"})
        return self.opener.open(request, timeout=timeout)


@dataclass
class TransferJob:
    challenge_id: int
    challenge: str
    filename: str
    action: str
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    percent: int = 0
    progress: str = ""
    state: str = "ACTIVE"
    done_at: float | None = None
    created_at: float = field(default_factory=time.monotonic)


class ResourceSampler:
    """Collect a stable rolling window of host CPU and memory usage."""

    def __init__(self) -> None:
        self.samples: deque[tuple[float, float, float]] = deque(maxlen=RESOURCE_HISTORY_SAMPLES)
        self.previous_cpu = self.read_cpu_times()
        self.last_sample = time.monotonic()
        try:
            self.cpu_cores = len(os.sched_getaffinity(0))
        except (AttributeError, OSError):
            self.cpu_cores = os.cpu_count() or 1
        memory_percent, used_gib, total_gib = self.read_memory()
        self.current_cpu = 0.0
        self.current_memory = memory_percent
        self.used_gib = used_gib
        self.total_gib = total_gib
        self.samples.append((self.last_sample, self.current_cpu, self.current_memory))

    @staticmethod
    def read_cpu_times() -> tuple[int, int]:
        fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:9]
        values = [int(value) for value in fields]
        return sum(values), values[3] + values[4]

    @staticmethod
    def read_memory() -> tuple[float, float, float]:
        values: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, remainder = line.partition(":")
            if remainder:
                values[key] = int(remainder.split()[0])
        total_kib = values.get("MemTotal", 0)
        available_kib = values.get("MemAvailable", values.get("MemFree", 0) + values.get("Buffers", 0) + values.get("Cached", 0))
        used_kib = max(0, total_kib - available_kib)
        percent = used_kib * 100 / total_kib if total_kib else 0.0
        return percent, used_kib / (1024 * 1024), total_kib / (1024 * 1024)

    def sample(self) -> dict[str, object]:
        now = time.monotonic()
        if now - self.last_sample >= RESOURCE_SAMPLE_INTERVAL:
            try:
                total, idle = self.read_cpu_times()
                previous_total, previous_idle = self.previous_cpu
                total_delta = total - previous_total
                idle_delta = idle - previous_idle
                if total_delta > 0:
                    self.current_cpu = max(0.0, min(100.0, (total_delta - idle_delta) * 100 / total_delta))
                self.previous_cpu = (total, idle)
                self.current_memory, self.used_gib, self.total_gib = self.read_memory()
            except (OSError, ValueError, IndexError):
                pass
            self.last_sample = now
            self.samples.append((now, self.current_cpu, self.current_memory))

        # Keep one extra maximum-width bucket. The graph only advances on a
        # completed bucket boundary, so dropping at exactly two minutes would
        # make its left edge disappear before the next visual tick.
        cutoff = now - RESOURCE_RETENTION_SECONDS
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()
        return {
            "now": now,
            "cpu": self.current_cpu,
            "memory": self.current_memory,
            "cpu_cores": self.cpu_cores,
            "used_gib": self.used_gib,
            "total_gib": self.total_gib,
            "samples": list(self.samples),
        }


class SharedState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.status = "PRE-START"
        self.team_name = "-"
        self.score = 0
        self.rank = "-"
        self.scoreboard: list[dict[str, object]] = []
        self.contest_end = CONTEST_END
        self.challenges: dict[str, dict[str, object]] = {}
        self.koth: dict[str, dict[str, object]] = {}
        self.codex_usage: dict[str, object] = {"status": "WAITING"}
        self.events: list[dict[str, object]] = []
        self.jobs: list[TransferJob] = []

    def add_job(self, job: TransferJob) -> None:
        with self.lock:
            self.jobs.append(job)

    def update_job(self, job: TransferJob, **values: object) -> None:
        with self.lock:
            for key, value in values.items():
                setattr(job, key, value)

    def finish_job(self, job: TransferJob, *, error: str = "") -> None:
        with self.lock:
            job.percent = 100 if not error else job.percent
            job.state = "ERROR" if error else "DONE"
            job.progress = error or job.progress
            job.done_at = time.monotonic()

    def view(self) -> dict[str, object]:
        now = time.monotonic()
        with self.lock:
            self.jobs = [job for job in self.jobs if job.done_at is None or now - job.done_at < DONE_TTL]
            return {"status": self.status, "team_name": self.team_name, "score": self.score, "rank": self.rank, "scoreboard": copy.deepcopy(self.scoreboard), "contest_end": self.contest_end, "challenges": copy.deepcopy(self.challenges), "koth": copy.deepcopy(self.koth), "codex_usage": copy.deepcopy(self.codex_usage), "events": copy.deepcopy(self.events[-100:]), "jobs": copy.copy(self.jobs)}


class Monitor:
    def __init__(self, state: SharedState, stop: threading.Event) -> None:
        self.state = state
        self.stop = stop
        self.client = CTFdClient(BASE_URL, USERNAME, PASSWORD)
        self.koth_client = CTFdClient(BASE_URL, USERNAME, PASSWORD)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
        self.previous = read_json(CURRENT_FILE, {"challenges": {}, "team": {}})
        self.manifest = read_json(MANIFEST_FILE, {})
        if not isinstance(self.manifest, dict):
            self.manifest = {}
        self.helpers = self.find_helpers()
        self.active_files: set[tuple[int, str]] = set()
        self.active_lock = threading.Lock()
        self.manifest_lock = threading.RLock()
        self.validation_cache: dict[str, tuple[int, int, str]] = {}
        self.event_lock = threading.RLock()
        self.event_ids: set[str] = set()
        self.koth_cache = read_json(KOTH_FILE, {"entries": {}, "brick_rounds": {}})
        if not isinstance(self.koth_cache, dict):
            self.koth_cache = {"entries": {}, "brick_rounds": {}}
        self.koth_lock = threading.RLock()
        self.koth_sessions: set[int] = set()
        self.brick_latest_refresh = 0.0
        self.koth_challenges = self.load_koth_challenges()
        self.codex_usage_cache = read_json(CODEX_USAGE_FILE, {})
        if not isinstance(self.codex_usage_cache, dict):
            self.codex_usage_cache = {}
        self.team_solves_cache: dict[int, dict[str, object]] = {}
        self.last_solve_refresh = 0.0
        self.last_config_refresh = 0.0
        self.cleanup_interrupted_work()
        self.load_events()
        self.restore_saved_state()

    def load_koth_challenges(self) -> dict[str, dict[str, object]]:
        challenges = self.previous.get("challenges", {}) if isinstance(self.previous, dict) else {}
        output = {str(key): copy.deepcopy(value) for key, value in challenges.items() if is_koth_challenge(value)} if isinstance(challenges, dict) else {}
        try:
            latest = max(SNAPSHOT_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime_ns)
            raw = read_json(latest, {})
            details = raw.get("challenge_details", []) if isinstance(raw, dict) else []
            for detail in details if isinstance(details, list) else []:
                if not is_koth_challenge(detail):
                    continue
                key = str(detail.get("id"))
                challenge = output.setdefault(key, {"id": detail.get("id")})
                for field in ("name", "category", "type", "value", "koth_url", "launch_url", "koth_namespace"):
                    if detail.get(field) not in (None, ""):
                        challenge[field] = detail[field]
                challenge.setdefault("solved", False)
                challenge.setdefault("directory", safe_directory_name(challenge.get("name") or f"challenge_{key}"))
                if isinstance(challenges, dict) and isinstance(challenges.get(key), dict):
                    challenges[key].update({field: challenge[field] for field in ("type", "koth_url", "launch_url", "koth_namespace") if field in challenge})
        except (OSError, ValueError):
            pass
        return output

    def restore_saved_state(self) -> None:
        challenges = self.previous.get("challenges", {}) if isinstance(self.previous, dict) else {}
        team = self.previous.get("team", {}) if isinstance(self.previous, dict) else {}
        saved_entries = self.koth_cache.get("entries", {}) if isinstance(self.koth_cache, dict) else {}
        koth: dict[str, dict[str, object]] = {}
        for key, challenge in self.koth_challenges.items():
            previous = saved_entries.get(key, {}) if isinstance(saved_entries, dict) else {}
            koth[key] = {
                "id": int(challenge.get("id") or key),
                "name": str(challenge.get("name") or f"KOTH {key}"),
                "rank": None,
                "teams": None,
                "score": None,
                "leader_score": None,
                "points": None,
                "status": "WAITING",
                **(previous if isinstance(previous, dict) else {}),
            }
        with self.state.lock:
            if isinstance(challenges, dict) and challenges:
                self.state.status = "LIVE"
                self.state.challenges = copy.deepcopy(challenges)
            if isinstance(team, dict):
                self.state.team_name = str(team.get("name") or USERNAME)
                self.state.score = int(team.get("score") or 0)
                place = team.get("place")
                self.state.rank = f"#{place}" if place and str(place).isdigit() else str(place or "-")
            self.state.koth = koth

    def update_koth_challenges(self, challenges: object) -> None:
        if not isinstance(challenges, dict):
            return
        latest = {str(key): copy.deepcopy(challenge) for key, challenge in challenges.items() if is_koth_challenge(challenge)}
        with self.koth_lock:
            removed = set(self.koth_challenges) - set(latest)
            self.koth_challenges = latest
            entries = self.koth_cache.get("entries") if isinstance(self.koth_cache, dict) else None
            if isinstance(entries, dict):
                for key in removed:
                    entries.pop(key, None)
            active_ids = {int(challenge.get("id") or 0) for challenge in latest.values()}
            self.koth_sessions.intersection_update(active_ids)
            with self.state.lock:
                for key in removed:
                    self.state.koth.pop(key, None)
                for key, challenge in latest.items():
                    self.state.koth.setdefault(key, {"id": int(challenge.get("id") or 0), "name": str(challenge.get("name") or f"KOTH {key}"), "rank": None, "teams": None, "score": None, "leader_score": None, "points": None, "status": "WAITING"})
            if removed:
                atomic_json(KOTH_FILE, self.koth_cache)

    def ensure_koth_session(self, challenge: dict[str, object], *, force: bool = False) -> None:
        challenge_id = int(challenge.get("id") or 0)
        if challenge_id in self.koth_sessions and not force:
            return
        if not self.koth_client.logged_in:
            self.koth_client.login()
        launch_url = str(challenge.get("launch_url") or "")
        if not launch_url:
            raise RuntimeError("KOTH launch URL is missing")
        request = urllib.request.Request(urllib.parse.urljoin(BASE_URL + "/", launch_url.lstrip("/")), headers={"User-Agent": "ctfd-monitor/1.0"})
        with self.koth_client.opener.open(request, timeout=20) as response:
            response.read()
        self.koth_sessions.add(challenge_id)

    def koth_json(self, challenge: dict[str, object], url: str, *, session: bool = False) -> dict[str, object]:
        if session:
            self.ensure_koth_session(challenge)
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ctfd-monitor/1.0"})
        try:
            with self.koth_client.opener.open(request, timeout=20) as response:
                value = json.load(response)
        except urllib.error.HTTPError as error:
            if not session or error.code not in {401, 403}:
                raise
            self.koth_sessions.discard(int(challenge.get("id") or 0))
            self.ensure_koth_session(challenge, force=True)
            with self.koth_client.opener.open(request, timeout=20) as response:
                value = json.load(response)
        if not isinstance(value, dict):
            raise RuntimeError("unexpected KOTH response")
        return value

    @staticmethod
    def projected_points(score: float, leader_score: float) -> float:
        if leader_score <= 0:
            return 0.0
        return min(KOTH_MAX_POINTS, KOTH_MAX_POINTS * score / leader_score)

    def refresh_brick_koth(self, challenge: dict[str, object], team_name: str) -> dict[str, object]:
        base = str(challenge.get("koth_url") or "").rstrip("/")
        state = self.koth_json(challenge, base + "/api/client-state")
        rounds = [int(value) for value in state.get("leaderboard_rounds", []) if str(value).isdigit()]
        cache = self.koth_cache.setdefault("brick_rounds", {})
        if not isinstance(cache, dict):
            cache = {}
            self.koth_cache["brick_rounds"] = cache
        refresh = {number for number in rounds if str(number) not in cache}
        if rounds and time.monotonic() - self.brick_latest_refresh >= 60.0:
            refresh.add(rounds[-1])
            self.brick_latest_refresh = time.monotonic()
        for number in sorted(refresh):
            first = self.koth_json(challenge, f"{base}/api/leaderboard?round={number}&page=1")
            items = list(first.get("leaderboard", [])) if isinstance(first.get("leaderboard"), list) else []
            pages = max(1, int(first.get("pages") or 1))
            for page in range(2, pages + 1):
                value = self.koth_json(challenge, f"{base}/api/leaderboard?round={number}&page={page}")
                if isinstance(value.get("leaderboard"), list):
                    items.extend(value["leaderboard"])
            scores: dict[str, float] = {}
            for item in items:
                if not isinstance(item, dict):
                    continue
                metrics = item.get("metrics")
                score = metrics.get("score") if isinstance(metrics, dict) else None
                name = str(item.get("team") or "")
                if name and isinstance(score, (int, float)):
                    scores[name] = max(scores.get(name, 0.0), float(score))
            cache[str(number)] = scores
        totals: dict[str, float] = {}
        for number in rounds:
            values = cache.get(str(number), {})
            if isinstance(values, dict):
                for name, score in values.items():
                    if isinstance(score, (int, float)):
                        totals[str(name)] = totals.get(str(name), 0.0) + float(score)
        ordered = sorted(totals.items(), key=lambda item: (-item[1], item[0].casefold()))
        score = totals.get(team_name, 0.0)
        rank = next((index for index, (name, _) in enumerate(ordered, start=1) if name == team_name), None)
        leader = ordered[0][1] if ordered else 0.0
        return {"rank": rank, "teams": len(ordered), "score": score, "leader_score": leader, "points": self.projected_points(score, leader), "rounds": len(rounds)}

    def refresh_neural_koth(self, challenge: dict[str, object], team_name: str) -> dict[str, object]:
        base = str(challenge.get("koth_url") or "").rstrip("/")
        value = self.koth_json(challenge, base + "/api/leaderboard")
        teams = value.get("teams", []) if isinstance(value.get("teams"), list) else []
        own = next((team for team in teams if isinstance(team, dict) and str(team.get("name")) == team_name), None)
        leader = teams[0] if teams and isinstance(teams[0], dict) else {}
        score = float(own.get("koth") or 0) if isinstance(own, dict) else 0.0
        points = float(own.get("normalized_score") or 0) if isinstance(own, dict) else 0.0
        return {"rank": int(own["rank"]) if isinstance(own, dict) and own.get("rank") is not None else None, "teams": len(teams), "score": score, "leader_score": float(leader.get("koth") or 0), "points": points}

    def refresh_shift_koth(self, challenge: dict[str, object]) -> dict[str, object]:
        base = str(challenge.get("koth_url") or "").rstrip("/")
        value = self.koth_json(challenge, base + "/api/score", session=True)
        return {"rank": int(value["rank"]) if value.get("rank") is not None else None, "teams": int(value.get("teams") or 0), "score": float(value.get("accumulated_score") or 0), "leader_score": float(value.get("first_rank_team_score") or 0), "points": float(value.get("score") or 0), "rounds": int(value.get("matches_played") or 0)}

    def refresh_battle_koth(self, challenge: dict[str, object]) -> dict[str, object]:
        base = str(challenge.get("koth_url") or "").rstrip("/")
        value = self.koth_json(challenge, base + "/army/api/standings", session=True)
        standings = value.get("standings") if isinstance(value.get("standings"), dict) else {}
        teams = standings.get("teams", []) if isinstance(standings.get("teams"), list) else []
        own = next((team for team in teams if isinstance(team, dict) and team.get("is_self") is True), None)
        leader = teams[0] if teams and isinstance(teams[0], dict) else {}
        score = float(own.get("points") or 0) if isinstance(own, dict) else 0.0
        leader_score = float(leader.get("points") or 0)
        return {"rank": int(own["rank"]) if isinstance(own, dict) and own.get("rank") is not None else None, "teams": len(teams), "score": score, "leader_score": leader_score, "points": self.projected_points(score, leader_score), "rounds": int(own.get("scored_games") or 0) if isinstance(own, dict) else 0}

    def refresh_koth(self) -> None:
        with self.koth_lock:
            challenges = copy.deepcopy(self.koth_challenges)
        with self.state.lock:
            team_name = self.state.team_name
        entries = self.koth_cache.setdefault("entries", {})
        if not isinstance(entries, dict):
            entries = {}
            self.koth_cache["entries"] = entries
        for key, challenge in sorted(challenges.items(), key=lambda item: int(item[1].get("id") or 0)):
            entry = copy.deepcopy(entries.get(key, {})) if isinstance(entries.get(key), dict) else {}
            entry.update({"id": int(challenge.get("id") or key), "name": str(challenge.get("name") or f"KOTH {key}")})
            try:
                challenge_id = int(challenge.get("id") or 0)
                if challenge_id == 7:
                    metrics = self.refresh_brick_koth(challenge, team_name)
                elif challenge_id == 9:
                    metrics = self.refresh_neural_koth(challenge, team_name)
                elif challenge_id == 16:
                    metrics = self.refresh_shift_koth(challenge)
                elif challenge_id == 17:
                    metrics = self.refresh_battle_koth(challenge)
                else:
                    raise RuntimeError("unsupported KOTH adapter")
                entry.update(metrics)
                entry.update({"status": "LIVE", "error": "", "updated_at": iso_now()})
            except Exception as error:
                entry.update({"status": "ERROR", "error": str(error), "updated_at": iso_now()})
            with self.koth_lock:
                if key not in self.koth_challenges:
                    continue
                entries[key] = entry
                with self.state.lock:
                    self.state.koth[key] = copy.deepcopy(entry)
        with self.koth_lock:
            atomic_json(KOTH_FILE, self.koth_cache)

    def run_koth(self) -> None:
        if not KOTH_ENABLED:
            return
        while not self.stop.is_set():
            if self.koth_challenges:
                self.refresh_koth()
            self.stop.wait(KOTH_POLL_INTERVAL)

    @staticmethod
    def read_codex_weekly_usage() -> dict[str, object]:
        command = shutil.which("codex")
        if not command:
            raise RuntimeError("codex command not found")
        process = subprocess.Popen(
            [command, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        try:
            if process.stdin is None or process.stdout is None:
                raise RuntimeError("Codex app server pipes are unavailable")
            requests = [
                {"method": "initialize", "id": 0, "params": {"clientInfo": {"name": "ctfd_monitor", "title": "CTFd Monitor", "version": "1.0.0"}}},
                {"method": "account/rateLimits/read", "id": 1, "params": {}},
            ]
            for request in requests:
                process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            deadline = time.monotonic() + 12.0
            result: dict[str, object] | None = None
            while time.monotonic() < deadline:
                ready, _, _ = select.select([process.stdout], [], [], min(0.5, deadline - time.monotonic()))
                if not ready:
                    if process.poll() is not None:
                        break
                    continue
                line = process.stdout.readline()
                if not line:
                    break
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict) and message.get("id") == 1:
                    value = message.get("result")
                    result = value if isinstance(value, dict) else None
                    break
            if result is None:
                raise RuntimeError("Codex usage request timed out")
            limits_by_id = result.get("rateLimitsByLimitId")
            codex = limits_by_id.get("codex") if isinstance(limits_by_id, dict) else None
            if not isinstance(codex, dict):
                codex = result.get("rateLimits")
            if not isinstance(codex, dict):
                raise RuntimeError("Codex rate limit data is unavailable")
            windows = [window for window in (codex.get("primary"), codex.get("secondary")) if isinstance(window, dict)]
            if not windows:
                raise RuntimeError("Codex usage window is unavailable")
            weekly = max(windows, key=lambda window: int(window.get("windowDurationMins") or 0))
            used = max(0.0, min(100.0, float(weekly.get("usedPercent") or 0.0)))
            credits = codex.get("credits") if isinstance(codex.get("credits"), dict) else {}
            return {
                "status": "LIVE",
                "used_percent": used,
                "remaining_percent": 100.0 - used,
                "window_minutes": int(weekly.get("windowDurationMins") or 0),
                "credits_balance": str(credits.get("balance") or "") if credits.get("hasCredits") else "",
                "credits_unlimited": bool(credits.get("unlimited")),
                "plan": str(codex.get("planType") or ""),
                "updated_at": iso_now(),
            }
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)

    def run_codex_usage(self) -> None:
        if not CODEX_ENABLED:
            return
        while not self.stop.is_set():
            try:
                usage = self.read_codex_weekly_usage()
            except Exception as error:
                with self.state.lock:
                    previous = self.state.codex_usage
                    self.state.codex_usage = {**previous, "status": "ERROR", "error": str(error)}
            else:
                current_credits = usage.get("credits_balance")
                start_credits = self.codex_usage_cache.get("competition_start_credits")
                with self.state.lock:
                    contest_status = self.state.status
                if current_credits:
                    if contest_status == "PRE-START":
                        self.codex_usage_cache["pre_start_credits"] = current_credits
                        atomic_json(CODEX_USAGE_FILE, self.codex_usage_cache)
                    elif not start_credits:
                        start_credits = self.codex_usage_cache.get("pre_start_credits") or current_credits
                        self.codex_usage_cache["competition_start_credits"] = start_credits
                        self.codex_usage_cache.pop("pre_start_credits", None)
                        atomic_json(CODEX_USAGE_FILE, self.codex_usage_cache)
                usage["competition_start_credits"] = start_credits or current_credits or ""
                with self.state.lock:
                    self.state.codex_usage = usage
            self.stop.wait(CODEX_USAGE_POLL_INTERVAL)

    def cleanup_interrupted_work(self) -> None:
        if STAGING_DIR.is_dir():
            shutil.rmtree(STAGING_DIR, ignore_errors=True)
        try:
            for path in BASE_DIR.glob("*/chall/deploy/.*.ctfd-part-*"):
                if path.is_file() or path.is_symlink():
                    path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            for path in STATE_DIR.rglob(".*.tmp-*"):
                path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def find_helpers() -> dict[str, Path]:
        helpers: dict[str, Path] = {}
        for name in HELPER_FILES:
            for candidate in (BASE_DIR / name, SCRIPT_DIR / name, Path.home() / name):
                if candidate.is_file():
                    helpers[name] = candidate
                    break
            if name not in helpers:
                raise FileNotFoundError(f"{name} not found in {BASE_DIR} or {Path.home()}")
        return helpers

    def load_events(self) -> None:
        events: list[dict[str, object]] = []
        try:
            for line in EVENT_FILE.read_text(encoding="utf-8").splitlines():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    events.append(value)
                    event_id = value.get("event_id")
                    if isinstance(event_id, str):
                        self.event_ids.add(event_id)
        except OSError:
            pass
        with self.state.lock:
            self.state.events = events[-200:]

    def add_event(self, kind: str, message: str, challenge_id: int | None = None, *, event_id: str | None = None) -> None:
        with self.event_lock:
            if event_id and event_id in self.event_ids:
                return
            event = {"time": iso_now(), "kind": kind, "message": message, "challenge_id": challenge_id, "expires_at": time.time() + BADGE_TTL if kind in {"NEW", "UPDATED"} else None}
            if event_id:
                event["event_id"] = event_id
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            with EVENT_FILE.open("a", encoding="utf-8") as output:
                output.write(json.dumps(event, ensure_ascii=False) + "\n")
                output.flush()
                os.fsync(output.fileno())
            if event_id:
                self.event_ids.add(event_id)
            with self.state.lock:
                self.state.events.append(event)

    def marker_for(self, challenge_id: int) -> tuple[str, float] | None:
        now = time.time()
        with self.state.lock:
            for event in reversed(self.state.events):
                if event.get("challenge_id") != challenge_id or event.get("kind") not in {"NEW", "UPDATED"}:
                    continue
                expires = float(event.get("expires_at") or 0)
                return (str(event["kind"]), expires) if expires > now else None
        return None

    def normalize_files(self, files: object) -> list[dict[str, str]]:
        output: list[dict[str, str]] = []
        used: dict[str, int] = {}
        for index, entry in enumerate(files if isinstance(files, list) else [], start=1):
            url = file_url(entry)
            if not url:
                continue
            path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
            name = safe_file_name(path, f"attachment_{index}")
            used[name] = used.get(name, 0) + 1
            local_name = name
            if used[name] > 1:
                local_name = f"{Path(name).stem}_{used[name]}{Path(name).suffix}"
            output.append({"url": url, "path": path, "name": name, "local_name": local_name})
        return output

    @staticmethod
    def normalize_hints(hints: object) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        for hint in hints if isinstance(hints, list) else []:
            if isinstance(hint, dict):
                output.append({"id": hint.get("id"), "name": hint.get("name") or hint.get("title"), "cost": hint.get("cost"), "content": hint.get("content")})
        return output

    def normalize_challenge(self, summary: dict[str, object], detail: dict[str, object]) -> dict[str, object]:
        challenge_id = int(detail.get("id") or summary.get("id") or 0)
        old = self.previous.get("challenges", {}).get(str(challenge_id), {})
        title = str(detail.get("name") or summary.get("name") or f"challenge_{challenge_id}")
        return {
            "id": challenge_id,
            "name": title,
            "category": str(detail.get("category") or summary.get("category") or "unknown"),
            "type": str(detail.get("type") or summary.get("type") or ""),
            "value": int(detail.get("value") or summary.get("value") or 0),
            "solved": bool(summary.get("solved_by_me") or detail.get("solved_by_me")),
            "description": description_text(detail.get("description") or ""),
            "hints": self.normalize_hints(detail.get("hints")),
            "files": self.normalize_files(detail.get("files")),
            "directory": str(old.get("directory") or f"{challenge_id}_{safe_directory_name(title)}"),
            "koth_url": str(detail.get("koth_url") or old.get("koth_url") or ""),
            "launch_url": str(detail.get("launch_url") or old.get("launch_url") or ""),
            "koth_namespace": str(detail.get("koth_namespace") or old.get("koth_namespace") or ""),
        }

    def prepare_challenge(self, challenge: dict[str, object]) -> Path:
        challenge_dir = BASE_DIR / str(challenge["directory"])
        chall_dir = challenge_dir / "chall"
        deploy_dir = chall_dir / "deploy"
        deploy_dir.mkdir(parents=True, exist_ok=True)
        for name, source in self.helpers.items():
            shutil.copy2(source, challenge_dir / name)
        description = f"# {challenge['name']}\n\n{challenge['description']}\n"
        (chall_dir / "README.md").write_text(description, encoding="utf-8")
        agents_path = chall_dir / "AGENTS.md"
        if AGENTS_TEMPLATE and not agents_path.exists():
            agents_path.write_text(AGENTS_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
        return deploy_dir

    def archive_existing(self, challenge_id: int, destination: Path) -> None:
        if destination.is_file():
            target_dir = ARCHIVE_DIR / str(challenge_id) / timestamp_name()
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, target_dir / destination.name)

    @staticmethod
    def manifest_key(challenge_id: int, local_name: str) -> str:
        return f"{challenge_id}/{local_name}"

    def save_manifest(self) -> None:
        with self.manifest_lock:
            atomic_json(MANIFEST_FILE, self.manifest)

    def local_file_is_current(self, challenge_id: int, file_info: dict[str, str], destination: Path) -> bool:
        key = self.manifest_key(challenge_id, file_info["local_name"])
        with self.manifest_lock:
            entry = copy.deepcopy(self.manifest.get(key))
        if not isinstance(entry, dict) or entry.get("source") != file_info["path"] or not destination.is_file():
            return False
        try:
            expected_size = int(entry.get("size", -1))
            expected_hash = str(entry.get("sha256") or "")
            stat = destination.stat()
            signature = (stat.st_size, stat.st_mtime_ns, expected_hash)
            if stat.st_size != expected_size or not expected_hash:
                self.validation_cache.pop(key, None)
                return False
            if self.validation_cache.get(key) == signature:
                return True
            valid = sha256_file(destination) == expected_hash
            if valid:
                self.validation_cache[key] = signature
            else:
                self.validation_cache.pop(key, None)
            return valid
        except (OSError, ValueError):
            return False

    def extraction_is_current(self, challenge_id: int, file_info: dict[str, str], deploy_dir: Path) -> bool:
        key = self.manifest_key(challenge_id, file_info["local_name"])
        with self.manifest_lock:
            entry = copy.deepcopy(self.manifest.get(key))
        extraction = entry.get("extraction") if isinstance(entry, dict) else None
        if not isinstance(extraction, dict) or extraction.get("status") != "complete":
            return False
        paths = extraction.get("paths")
        if not isinstance(paths, list):
            return False
        root = deploy_dir.resolve()
        for relative in paths:
            target = (deploy_dir / str(relative)).resolve()
            if not target.is_relative_to(root) or not target.exists():
                return False
        return True

    def schedule_file(self, challenge: dict[str, object], file_info: dict[str, str], deploy_dir: Path, changed: bool) -> None:
        if self.stop.is_set():
            return
        key = (int(challenge["id"]), file_info["local_name"])
        with self.active_lock:
            if key in self.active_files:
                return
            self.active_files.add(key)
        self.executor.submit(self.download_worker, challenge, file_info, deploy_dir, changed, key)

    def schedule_extract(self, challenge: dict[str, object], file_info: dict[str, str], deploy_dir: Path) -> None:
        if self.stop.is_set():
            return
        key = (int(challenge["id"]), file_info["local_name"])
        with self.active_lock:
            if key in self.active_files:
                return
            self.active_files.add(key)
        self.executor.submit(self.extract_worker, challenge, file_info, deploy_dir, key)

    @staticmethod
    def format_bytes(value: int) -> str:
        if value < 1024:
            return f"{value} B"
        if value < 1024 * 1024:
            return f"{value / 1024:.1f} KB"
        return f"{value / (1024 * 1024):.1f} MB"

    def download_worker(self, challenge: dict[str, object], file_info: dict[str, str], deploy_dir: Path, changed: bool, key: tuple[int, str]) -> None:
        job = TransferJob(int(challenge["id"]), str(challenge["name"]), file_info["local_name"], "DOWNLOAD")
        self.state.add_job(job)
        destination = deploy_dir / file_info["local_name"]
        temporary = destination.with_name(f".{destination.name}.ctfd-part-{uuid.uuid4().hex}")
        try:
            if self.stop.is_set():
                raise DownloadCancelled("download cancelled")
            with self.client.open_file(file_info["url"]) as response, temporary.open("wb") as output:
                total = int(response.headers.get("Content-Length") or 0)
                received = 0
                while True:
                    if self.stop.is_set():
                        raise DownloadCancelled("download cancelled")
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    received += len(chunk)
                    if received > MAX_DOWNLOAD_BYTES:
                        raise OSError("download exceeds max_download_bytes")
                    progress = self.format_bytes(received) + (f"/{self.format_bytes(total)}" if total else "")
                    self.state.update_job(job, percent=min(99, int(received * 100 / total)) if total else 0, progress=progress)
                    if TEST_MODE:
                        time.sleep(0.03)
            if total and received != total:
                raise OSError(f"incomplete download: {received}/{total} bytes")
            if self.stop.is_set():
                raise DownloadCancelled("download cancelled")
            new_hash = sha256_file(temporary)
            if self.stop.is_set():
                raise DownloadCancelled("download cancelled")
            old_hash = sha256_file(destination) if destination.is_file() else ""
            manifest_key = self.manifest_key(int(challenge["id"]), file_info["local_name"])
            with self.manifest_lock:
                existing_entry = copy.deepcopy(self.manifest.get(manifest_key))
            expected_old_hash = str(existing_entry.get("sha256") or "") if isinstance(existing_entry, dict) else ""
            if destination.is_file() and new_hash != old_hash:
                self.archive_existing(int(challenge["id"]), destination)
            if self.stop.is_set():
                raise DownloadCancelled("download cancelled")
            temporary.replace(destination)
            archive = AUTO_EXTRACT and (zipfile.is_zipfile(destination) or tarfile.is_tarfile(destination))
            with self.manifest_lock:
                previous = self.manifest.get(manifest_key)
                previous_extraction = previous.get("extraction") if isinstance(previous, dict) else None
                self.manifest[manifest_key] = {
                    "sha256": new_hash,
                    "size": destination.stat().st_size,
                    "source": file_info["path"],
                    "updated": iso_now(),
                    "extraction": {"status": "pending", "paths": list(previous_extraction.get("paths", [])) if isinstance(previous_extraction, dict) else []} if archive else None,
                }
                atomic_json(MANIFEST_FILE, self.manifest)
            self.state.update_job(job, percent=100, progress=self.format_bytes(destination.stat().st_size))
            self.state.finish_job(job)
            if archive and not self.stop.is_set():
                self.apply_extraction(challenge, file_info, destination, deploy_dir)
        except DownloadCancelled:
            self.state.finish_job(job, error="cancelled")
        except Exception as error:
            self.state.finish_job(job, error=str(error))
            self.add_event("ERROR", f"{challenge['name']} / {file_info['local_name']}: {error}")
        finally:
            if temporary.exists():
                temporary.unlink()
            with self.active_lock:
                self.active_files.discard(key)

    def extract_worker(self, challenge: dict[str, object], file_info: dict[str, str], deploy_dir: Path, key: tuple[int, str]) -> None:
        try:
            archive = deploy_dir / file_info["local_name"]
            if not self.stop.is_set():
                self.apply_extraction(challenge, file_info, archive, deploy_dir)
        finally:
            with self.active_lock:
                self.active_files.discard(key)

    def apply_extraction(self, challenge: dict[str, object], file_info: dict[str, str], archive: Path, deploy_dir: Path) -> None:
        job = TransferJob(int(challenge["id"]), str(challenge["name"]), archive.name, "EXTRACT")
        self.state.add_job(job)
        transaction = STAGING_DIR / job.job_id
        payload = transaction / "payload"
        payload.mkdir(parents=True, exist_ok=True)
        try:
            extract(archive, payload, MAX_DOWNLOAD_BYTES, self.stop.is_set)
            paths: list[str] = []
            deploy_root = deploy_dir.resolve()
            for source in sorted(payload.rglob("*")):
                if not source.is_file():
                    continue
                if self.stop.is_set():
                    raise DownloadCancelled("extraction cancelled")
                relative = source.relative_to(payload)
                destination = (deploy_dir / relative).resolve()
                if not destination.is_relative_to(deploy_root):
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    self.archive_existing(int(challenge["id"]), destination)
                temporary = destination.with_name(f".{destination.name}.ctfd-part-{uuid.uuid4().hex}")
                try:
                    shutil.copy2(source, temporary)
                    temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)
                paths.append(relative.as_posix())

            if self.stop.is_set():
                raise DownloadCancelled("extraction cancelled")

            manifest_key = self.manifest_key(int(challenge["id"]), file_info["local_name"])
            with self.manifest_lock:
                entry = self.manifest.get(manifest_key)
                if not isinstance(entry, dict):
                    raise RuntimeError("archive manifest entry disappeared")
                old_extraction = entry.get("extraction")
                old_paths = set(old_extraction.get("paths", [])) if isinstance(old_extraction, dict) else set()
                claimed_elsewhere: set[str] = set()
                for other_key, other_entry in self.manifest.items():
                    if other_key == manifest_key or not isinstance(other_entry, dict):
                        continue
                    other_extraction = other_entry.get("extraction")
                    if isinstance(other_extraction, dict):
                        claimed_elsewhere.update(str(path) for path in other_extraction.get("paths", []))
                for stale in old_paths - set(paths) - claimed_elsewhere:
                    target = (deploy_dir / str(stale)).resolve()
                    if target.is_relative_to(deploy_root) and (target.is_file() or target.is_symlink()):
                        self.archive_existing(int(challenge["id"]), target)
                        target.unlink(missing_ok=True)
                entry["extraction"] = {"status": "complete", "paths": paths, "updated": iso_now()}
                atomic_json(MANIFEST_FILE, self.manifest)
            self.state.finish_job(job)
        except DownloadCancelled:
            self.state.finish_job(job, error="cancelled")
        except Exception as error:
            self.state.finish_job(job, error=str(error))
            self.add_event("ERROR", f"extract {challenge['name']} / {archive.name}: {error}")
        finally:
            shutil.rmtree(transaction, ignore_errors=True)

    def fetch_team(self) -> dict[str, object]:
        try:
            data = self.client.request_json("/api/v1/teams/me").get("data")
            return data if isinstance(data, dict) else {}
        except ApiError:
            try:
                data = self.client.request_json("/api/v1/users/me").get("data")
                return data if isinstance(data, dict) else {}
            except ApiError:
                return {}

    def fetch_scoreboard(self) -> list[dict[str, object]]:
        try:
            rows = self.client.request_json_routes(("/api/v2/scoreboard/full", "/api/v1/scoreboard")).get("data")
        except ApiError:
            return []
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    @staticmethod
    def scoreboard_team(rows: list[dict[str, object]], team: dict[str, object]) -> dict[str, object] | None:
        return next((row for row in rows if row.get("account_id") == team.get("id") or row.get("id") == team.get("id") or row.get("name") == team.get("name")), None)

    def fetch_rank(self, team: dict[str, object], rows: list[dict[str, object]] | None = None) -> str:
        rows = self.fetch_scoreboard() if rows is None else rows
        if not rows:
            place = team.get("place")
            return f"#{place}" if place else "-"
        own = self.scoreboard_team(rows, team)
        if not own:
            return "-"
        index = rows.index(own) + 1
        return f"#{own.get('pos') or index}"

    def refresh_contest_config(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last_config_refresh < CONFIG_POLL_INTERVAL:
            return
        self.last_config_refresh = now
        try:
            data = self.client.request_json_routes(("/api/v2/config/", "/api/v2/config")).get("data")
        except ApiError:
            return
        competition = data.get("competition") if isinstance(data, dict) and isinstance(data.get("competition"), dict) else {}
        end = str(competition.get("end") or "")
        if end:
            with self.state.lock:
                self.state.contest_end = end

    def fetch_team_solves(self) -> dict[int, dict[str, object]]:
        try:
            data = self.client.request_json_routes(("/api/v1/teams/me/solves", "/api/v1/users/me/solves")).get("data")
        except ApiError:
            return {}
        solves: dict[int, dict[str, object]] = {}
        for solve in data if isinstance(data, list) else []:
            if not isinstance(solve, dict):
                continue
            challenge = solve.get("challenge") if isinstance(solve.get("challenge"), dict) else {}
            try:
                challenge_id = int(solve.get("challenge_id") or challenge.get("id"))
            except (TypeError, ValueError):
                continue
            solves[challenge_id] = solve
        return solves

    def refresh_team_solves(self, *, force: bool = False) -> dict[int, dict[str, object]]:
        now = time.monotonic()
        if not force and now - self.last_solve_refresh < SOLVE_POLL_INTERVAL:
            return self.team_solves_cache
        self.last_solve_refresh = now
        solves = self.fetch_team_solves()
        if solves:
            self.team_solves_cache = solves
            self.enrich_solved_events(solves)
        return self.team_solves_cache

    @staticmethod
    def solve_event_message(challenge: dict[str, object], solve: dict[str, object] | None) -> str:
        solve = solve if isinstance(solve, dict) else {}
        user = solve.get("user") if isinstance(solve.get("user"), dict) else {}
        team = solve.get("team") if isinstance(solve.get("team"), dict) else {}
        solved_challenge = solve.get("challenge") if isinstance(solve.get("challenge"), dict) else {}
        who = str(user.get("name") or team.get("name") or "Team")
        name = str(solved_challenge.get("name") or challenge.get("name") or "challenge")
        return f"{who} solves {name}"

    def enrich_solved_events(self, solves: dict[int, dict[str, object]]) -> None:
        if not solves:
            return
        with self.state.lock:
            challenges = self.previous.get("challenges", {}) if isinstance(self.previous, dict) else {}
            for event in self.state.events:
                if event.get("kind") != "SOLVED":
                    continue
                try:
                    challenge_id = int(event.get("challenge_id"))
                except (TypeError, ValueError):
                    continue
                solve = solves.get(challenge_id)
                if not solve:
                    continue
                challenge = challenges.get(str(challenge_id), {}) if isinstance(challenges, dict) else {}
                event["message"] = self.solve_event_message(challenge if isinstance(challenge, dict) else {}, solve)

    def fetch_snapshot(self) -> tuple[dict[str, object], dict[str, object]]:
        summaries = self.client.request_json_routes(("/api/v2/challenges", "/api/v1/challenges")).get("data")
        if not isinstance(summaries, list):
            raise ApiError("/api/v2/challenges", 500, "unexpected challenge list")
        normalized: dict[str, dict[str, object]] = {}
        raw_details: list[dict[str, object]] = []
        used_directories: set[str] = set()
        for summary in summaries:
            if not isinstance(summary, dict) or "id" not in summary:
                continue
            challenge_id = summary["id"]
            detail = self.client.request_json_routes((f"/api/v2/challenges/{challenge_id}", f"/api/v1/challenges/{challenge_id}")).get("data")
            if not isinstance(detail, dict):
                continue
            challenge = self.normalize_challenge(summary, detail)
            directory = str(challenge["directory"])
            if directory in used_directories:
                directory = safe_directory_name(f"{directory}_{challenge['id']}")
                challenge["directory"] = directory
            used_directories.add(directory)
            normalized[str(challenge["id"])] = challenge
            raw_details.append(detail)
        team = self.fetch_team()
        return {"challenges": normalized, "team": team}, {"captured_at": iso_now(), "challenge_list": summaries, "challenge_details": raw_details, "team": team}

    def process_snapshot(self, current: dict[str, object], raw: dict[str, object]) -> None:
        if self.stop.is_set():
            return
        old_challenges = self.previous.get("challenges", {})
        new_challenges = current.get("challenges", {})
        self.update_koth_challenges(new_challenges)
        def comparable(challenges: object) -> object:
            value = copy.deepcopy(challenges)
            if not isinstance(value, dict):
                return value
            for challenge in value.values():
                if not isinstance(challenge, dict):
                    continue
                for file_info in challenge.get("files", []):
                    if isinstance(file_info, dict):
                        file_info.pop("url", None)
            return value

        changed_any = comparable(old_challenges) != comparable(new_challenges)
        if isinstance(old_challenges, dict) and isinstance(new_challenges, dict):
            for challenge_id in sorted(set(old_challenges) - set(new_challenges), key=lambda value: (0, int(value)) if str(value).isdigit() else (1, str(value))):
                deleted = old_challenges.get(challenge_id)
                if not isinstance(deleted, dict):
                    continue
                number = int(deleted.get("id") or challenge_id)
                self.add_event("DELETED", f"{deleted.get('name') or f'Challenge {number}'} deleted", number)
        newly_solved = {
            int(challenge["id"])
            for challenge_id, challenge in new_challenges.items()
            if isinstance(challenge, dict)
            and challenge.get("solved")
            and not (old_challenges.get(challenge_id, {}).get("solved") if isinstance(old_challenges, dict) and isinstance(old_challenges.get(challenge_id), dict) else False)
            and isinstance(old_challenges, dict)
            and isinstance(old_challenges.get(challenge_id), dict)
        }
        team_solves = self.refresh_team_solves(force=bool(newly_solved))
        for challenge_id, challenge in new_challenges.items():
            if not isinstance(challenge, dict):
                continue
            old = old_challenges.get(challenge_id) if isinstance(old_challenges, dict) else None
            number = int(challenge["id"])
            deploy_dir = self.prepare_challenge(challenge)
            version_hash = hashlib.sha256(json.dumps(comparable({challenge_id: challenge}), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
            if not isinstance(old, dict):
                self.add_event("NEW", f"{challenge['name']} released", number, event_id=f"new:{number}")
            else:
                reasons: list[str] = []
                if old.get("description") != challenge.get("description"):
                    reasons.append("description")
                if old.get("hints") != challenge.get("hints"):
                    reasons.append("hint")
                old_files_view = [(item.get("name"), item.get("path")) for item in old.get("files", [])]
                new_files_view = [(item.get("name"), item.get("path")) for item in challenge.get("files", [])]
                if old_files_view != new_files_view:
                    reasons.append("file")
                if reasons:
                    self.add_event("UPDATED", f"{challenge['name']}: {' + '.join(reasons)} changed", number, event_id=f"updated:{number}:{version_hash}")
                if not old.get("solved") and challenge.get("solved"):
                    self.add_event("SOLVED", self.solve_event_message(challenge, team_solves.get(number)), number, event_id=f"solved:{number}")
            for file_info in challenge.get("files", []):
                if not isinstance(file_info, dict):
                    continue
                destination = deploy_dir / str(file_info["local_name"])
                manifest_key = self.manifest_key(number, str(file_info["local_name"]))
                with self.manifest_lock:
                    known_file = isinstance(self.manifest.get(manifest_key), dict)
                if not self.local_file_is_current(number, file_info, destination):
                    self.schedule_file(challenge, file_info, deploy_dir, known_file or destination.is_file())
                elif AUTO_EXTRACT and (zipfile.is_zipfile(destination) or tarfile.is_tarfile(destination)) and not self.extraction_is_current(number, file_info, deploy_dir):
                    self.schedule_extract(challenge, file_info, deploy_dir)
        team = current.get("team") if isinstance(current.get("team"), dict) else {}
        scoreboard = self.fetch_scoreboard()
        own_scoreboard = self.scoreboard_team(scoreboard, team)
        rank = self.fetch_rank(team, scoreboard)
        display_challenges = copy.deepcopy(new_challenges)
        for challenge in display_challenges.values():
            if not isinstance(challenge, dict):
                continue
            marker = self.marker_for(int(challenge["id"]))
            challenge["marker"] = marker[0] if marker else None
            challenge["marker_expires"] = marker[1] if marker else None
        with self.state.lock:
            self.state.status = "LIVE"
            self.state.team_name = str(team.get("name") or USERNAME)
            fallback_score = int(team.get("score") or sum(int(challenge.get("value") or 0) for challenge in new_challenges.values() if isinstance(challenge, dict) and challenge.get("solved")))
            self.state.score = float(own_scoreboard.get("total_score", own_scoreboard.get("score", fallback_score)) or 0) if own_scoreboard else fallback_score
            self.state.rank = rank
            self.state.scoreboard = scoreboard
            self.state.challenges = display_challenges
        if changed_any:
            SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
            atomic_json(SNAPSHOT_DIR / f"{timestamp_name()}.json", raw)
            atomic_json(CURRENT_FILE, current)
        self.previous = copy.deepcopy(current)

    def run(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            login = self.client.login()
            user = login.get("user")
            with self.state.lock:
                if isinstance(user, dict):
                    team = user.get("team")
                    self.state.team_name = str(team.get("name") if isinstance(team, dict) else user.get("name") or USERNAME)
            self.refresh_team_solves(force=True)
            self.refresh_contest_config(force=True)
        except Exception as error:
            self.add_event("ERROR", f"login: {error}")
        failures = 0
        while not self.stop.is_set():
            try:
                if not self.client.logged_in:
                    self.client.login()
                self.refresh_contest_config()
                team = self.fetch_team()
                with self.state.lock:
                    if team:
                        self.state.team_name = str(team.get("name") or self.state.team_name)
                current, raw = self.fetch_snapshot()
                self.process_snapshot(current, raw)
                failures = 0
            except ApiError as error:
                failures += 1
                with self.state.lock:
                    self.state.status = "STALE"
                if error.status in {401, 403} and (error.code == "competition_closed" or "대회 시간" in error.message or "not started" in error.message.lower() or "started" in error.message.lower()):
                    with self.state.lock:
                        self.state.status = "PRE-START"
                        self.state.challenges = {}
                        self.state.score = 0
                        self.state.rank = "-"
                elif error.status == 401:
                    self.client.logged_in = False
                else:
                    self.add_event("ERROR", str(error))
            except Exception as error:
                failures += 1
                with self.state.lock:
                    self.state.status = "STALE"
                self.add_event("ERROR", str(error))
            self.stop.wait(min(120, POLL_INTERVAL * 2 ** min(failures, 5)))
        self.executor.shutdown(wait=True, cancel_futures=True)


def marker_badge(challenge: dict[str, object]) -> tuple[str, str] | None:
    kind = challenge.get("marker")
    expires = float(challenge.get("marker_expires") or 0)
    remaining = max(0, int(math.ceil(expires - time.time())))
    if not kind or remaining <= 0:
        return None
    minutes, seconds = divmod(remaining, 60)
    return f"{kind} {minutes:02d}:{seconds:02d}", CYAN if kind == "NEW" else YELLOW


def problem_line(challenge: dict[str, object], width: int) -> str:
    marker = marker_badge(challenge)
    prefix = paint(f"[{marker[0]}]", marker[1], bold=True) + " " if marker else ""
    score = paint(str(challenge["value"]) + " pt", GRAY)
    score_width = display_width(score)
    left_width = max(1, width - score_width - 1)
    left = truncate(f"  {prefix}{challenge['name']}", left_width)
    return f"{pad(left, left_width)} {score}"


def challenge_lines(challenges: list[dict[str, object]], width: int, *, compact: bool = False) -> list[str]:
    groups: dict[str, list[dict[str, object]]] = {}
    for challenge in challenges:
        groups.setdefault(str(challenge.get("category") or "unknown"), []).append(challenge)
    lines: list[str] = []
    for group_index, group_name in enumerate(sorted(groups, key=str.casefold)):
        problems = sorted(groups[group_name], key=lambda value: str(value["name"]).casefold())
        if group_index and not compact:
            lines.append("")
        lines.append(paint(f"{group_name.upper()} ({len(problems)})", WHITE, bold=True))
        lines.extend(problem_line(challenge, width) for challenge in problems)
    return lines


def render_challenges(view: dict[str, object], left_width: int, right_width: int, *, compact: bool = False) -> list[str]:
    challenges = [challenge for challenge in view["challenges"].values() if not is_koth_challenge(challenge)]
    if view["status"] == "PRE-START":
        left = boxed("UNSOLVED  0", ["", paint("Competition has not start.", YELLOW, bold=True), "", ""], left_width, RED)
        right = boxed("SOLVED  0", ["", "", "", ""], right_width, GREEN)
    else:
        unsolved = [challenge for challenge in challenges if not challenge.get("solved")]
        solved = [challenge for challenge in challenges if challenge.get("solved")]
        left = boxed(f"UNSOLVED  {len(unsolved)}", challenge_lines(unsolved, left_width - 4, compact=compact), left_width, RED)
        right = boxed(f"SOLVED  {len(solved)}", challenge_lines(solved, right_width - 4, compact=compact), right_width, GREEN)
    rows = max(len(left), len(right))
    left += [" " * left_width] * (rows - len(left))
    right += [" " * right_width] * (rows - len(right))
    return [pad(left[index], left_width) + "  " + right[index] for index in range(rows)]


def render_koth(view: dict[str, object], width: int) -> list[str]:
    entries = sorted(view.get("koth", {}).values(), key=lambda entry: (int(entry.get("id") or 0), str(entry.get("name") or "").casefold()))
    known_points = [float(entry["points"]) for entry in entries if isinstance(entry.get("points"), (int, float))]
    total = sum(known_points)
    maximum = len(entries) * KOTH_MAX_POINTS
    lines: list[str] = []
    for entry in entries:
        name = str(entry.get("name") or "KOTH")
        rank = entry.get("rank")
        teams = entry.get("teams")
        rank_text = f"#{rank}/{teams}" if rank is not None and teams else "--/--"
        score = entry.get("score")
        points = entry.get("points")
        score_text = f"{float(score):.2f}" if isinstance(score, (int, float)) else "--"
        points_text = f"{float(points):.2f}" if isinstance(points, (int, float)) else "--"
        ratio = max(0.0, min(1.0, float(points) / KOTH_MAX_POINTS)) if isinstance(points, (int, float)) else 0.0
        bar_width = 20 if width >= 110 else max(8, min(16, width - 64))
        filled = round(bar_width * ratio)
        bar_color = GREEN if entry.get("status") == "LIVE" else YELLOW
        bar = paint("█" * filled, bar_color) + paint("░" * (bar_width - filled), GRAY)
        state = ""
        if entry.get("status") == "ERROR":
            state = paint("  STALE", RED, bold=True) if points is not None else paint("  UNAVAILABLE", RED, bold=True)
        elif entry.get("status") != "LIVE":
            state = paint("  WAITING", YELLOW, bold=True)
        if width >= 110:
            left = f"{pad(truncate(name, 40), 40)}  KOTH {score_text:>10}{state}"
        else:
            left = f"{pad(truncate(name, 32), 32)}{state}"
        right = f"Rank {rank_text:>9}  {bar}  {points_text:>8} / 1500 pt"
        content_width = width - 4
        left_width = max(1, content_width - display_width(right))
        line = f"{pad(truncate(left, max(1, left_width - 2)), left_width)}{right}"
        lines.append(line)
    if not lines:
        lines = [paint("WAITING", YELLOW, bold=True)]
    title = f"KOTH · {len(entries)} ARENAS · PROJECTED {total:.2f} / {maximum:.0f} pt"
    return boxed(title, lines, width, CYAN)


def comparison_position(row: dict[str, object], fallback: int) -> int:
    try:
        return int(row.get("pos") or fallback)
    except (TypeError, ValueError):
        return fallback


def comparison_status_cell(ours: bool, theirs: bool) -> str:
    if ours and theirs:
        return paint(f"{'✓':^5}", GRAY)
    if theirs:
        return f"{BOLD}{RED_BG}{RED}{'✓':^5}{RESET}"
    if ours:
        return f"{BOLD}{GREEN_BG}{GREEN}{'×':^5}{RESET}"
    return paint(f"{'.':^5}", GRAY)


def comparison_delta_cell(value: float) -> str:
    if value > 0:
        return f"{RED_BG}{RED}{value:+5.0f}{RESET}"
    if value < 0:
        return f"{GREEN_BG}{GREEN}{value:+5.0f}{RESET}"
    return f"{value:+5.0f}"


def render_team_comparison(view: dict[str, object], width: int) -> list[str]:
    rows = [row for row in view.get("scoreboard", []) if isinstance(row, dict)]
    own = next((row for row in rows if str(row.get("name") or "") == str(view.get("team_name") or "")), None)
    if not own:
        return boxed("TEAM COMPARISON · TOP 4 OPPONENTS", [paint("WAITING", YELLOW, bold=True)], width, BLUE)
    own_rank = comparison_position(own, len(rows) + 1)

    opponents = sorted((row for row in rows if row is not own), key=lambda row: (comparison_position(row, len(rows) + 1), str(row.get("name") or "").casefold()))[:4]
    if not opponents:
        return boxed("TEAM COMPARISON · TOP 4 OPPONENTS", [paint("NO OPPONENTS", YELLOW, bold=True)], width, BLUE)
    challenges = sorted(
        (
            (int(challenge.get("id") or key), str(challenge.get("name") or f"Challenge {key}"))
            for key, challenge in view.get("challenges", {}).items()
            if isinstance(challenge, dict) and not is_koth_challenge(challenge)
        ),
        key=lambda item: item[0],
    )
    own_solved = {int(value) for value in own.get("solved_challenge_ids", []) if str(value).isdigit()}
    own_total = float(own.get("total_score") or 0)
    own_koth = own.get("koth_score_detail") if isinstance(own.get("koth_score_detail"), dict) else {}
    koth_names = ["King of the Brick-Breaker", "Neural Dominion", "SHIFT", "BATTLE"]
    solved_by_opponent = [
        {int(value) for value in opponent.get("solved_challenge_ids", []) if str(value).isdigit()}
        for opponent in opponents
    ]
    visible_challenges = [
        (challenge_id, name)
        for challenge_id, name in challenges
        if not (challenge_id in own_solved and all(challenge_id in solved for solved in solved_by_opponent))
    ]

    left_lines = [f"{'RK TEAM':<16}{'ΔPT':>8} {'BRK':^5}{'NEU':^5}{'SHF':^5}{'BAT':^5}", paint("─" * 45, GRAY)]
    for opponent in opponents:
        prefix = f"#{comparison_position(opponent, len(rows) + 1):<2} {pad(truncate(str(opponent.get('name') or 'Team'), 12), 12)} {float(opponent.get('total_score') or 0) - own_total:+7.0f} "
        opponent_koth = opponent.get("koth_score_detail") if isinstance(opponent.get("koth_score_detail"), dict) else {}
        koth = "".join(comparison_delta_cell(float(opponent_koth.get(name) or 0) - float(own_koth.get(name) or 0)) for name in koth_names)
        left_lines.append(prefix + koth)
    left_lines.append(f"#{own_rank:<2} {pad(truncate(str(own.get('name') or 'OUR TEAM'), 12), 12)} {0:+7.0f} " + f"{0:+5.0f}" * 4)

    team_headers = [f"#{comparison_position(opponent, len(rows) + 1)}" for opponent in opponents] + ["US"]
    content_width = width - 4
    divider = paint(" │ ", GRAY)
    left_width = 48 if content_width >= 102 else max(12, (content_width - 3) // 2)
    right_width = max(1, content_width - left_width - 3)
    name_width = max(1, right_width - 25)
    right_lines = [f"{'JEOPARDY CHALLENGE':<{name_width}}" + "".join(f"{header:^5}" for header in team_headers), paint("─" * right_width, GRAY)]
    for challenge_id, name in visible_challenges:
        cells = "".join(comparison_status_cell(challenge_id in own_solved, challenge_id in solved) for solved in solved_by_opponent)
        own_cell = f"{'✓' if challenge_id in own_solved else '':^5}"
        right_lines.append(f"{pad(truncate(name, name_width), name_width)}{cells}{own_cell}")
    lines: list[str] = []
    for index in range(max(len(left_lines), len(right_lines))):
        left = left_lines[index] if index < len(left_lines) else ""
        right = right_lines[index] if index < len(right_lines) else ""
        lines.append(pad(truncate(left, left_width), left_width) + divider + pad(truncate(right, right_width), right_width))
    return boxed(f"TEAM COMPARISON · TOP 4 OPPONENTS · OUR ACTUAL #{own_rank}", lines, width, BLUE)


def competition_countdown(view: dict[str, object]) -> tuple[str, str]:
    value = str(view.get("contest_end") or "")
    if not value:
        return "WAITING", YELLOW
    try:
        end = datetime.fromisoformat(value.replace("Z", "+00:00"))
        remaining = max(0, math.ceil((end - datetime.now(timezone.utc)).total_seconds()))
    except ValueError:
        return "UNAVAILABLE", RED
    if remaining <= 0:
        return "ENDED", RED
    days, remainder = divmod(remaining, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return (f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}" if days else f"{hours:02d}:{minutes:02d}:{seconds:02d}"), GREEN


def transfer_line(job: TransferJob, width: int) -> str:
    if width < 80:
        content_width = width - 4
        bar_width = 8
        action = "EXTRACT" if job.action == "EXTRACT" else "DOWNLOAD"
        tail = "ERROR" if job.state == "ERROR" else "DONE" if job.state == "DONE" else f"{job.percent:3d}%"
        path_width = max(8, content_width - 1 - 8 - 1 - bar_width - 1 - 5)
        filled = int(bar_width * max(0, min(100, job.percent)) / 100)
        action_color = YELLOW if job.action == "EXTRACT" else CYAN
        bar_color = RED if job.state == "ERROR" else GREEN if job.state == "DONE" else action_color
        bar = paint("█" * filled, bar_color) + paint("░" * (bar_width - filled), GRAY)
        path = pad(truncate(f"{job.challenge} / {job.filename}", path_width), path_width)
        tail_color = RED if job.state == "ERROR" else GREEN if job.state == "DONE" else WHITE
        return f"{path} {paint(action.ljust(8), action_color, bold=True)} {bar} {paint(tail.rjust(5), tail_color, bold=job.state != 'ACTIVE')}"
    path_width = max(24, min(42, width - 55))
    bar_width = max(8, min(18, width - path_width - 47))
    filled = int(bar_width * max(0, min(100, job.percent)) / 100)
    action_color = YELLOW if job.action == "EXTRACT" else CYAN
    bar_color = GREEN if job.state == "DONE" else action_color
    bar = paint("█" * filled, bar_color) + paint("░" * (bar_width - filled), GRAY)
    path = pad(truncate(f"{job.challenge} / {job.filename}", path_width), path_width)
    if job.state == "DONE" and job.done_at is not None:
        remaining = max(1, int(math.ceil(DONE_TTL - (time.monotonic() - job.done_at))))
        state = paint(f"DONE {remaining}s", GREEN, bold=True)
    elif job.state == "ERROR":
        state = paint("ERROR", RED, bold=True)
    else:
        state = job.progress
    return f"{path} {paint(job.action.ljust(8), action_color, bold=True)} {bar} {job.percent:3d}%  {state}"


def render_transfers(view: dict[str, object], width: int) -> list[str]:
    jobs = sorted(view["jobs"], key=lambda job: (job.challenge.casefold(), job.filename.casefold(), 0 if job.action == "DOWNLOAD" else 1, job.created_at))
    if jobs:
        active = sum(job.state == "ACTIVE" for job in jobs)
        title = f"DOWNLOAD / EXTRACT · {len(jobs)} JOBS · {active} ACTIVE"
        lines = [transfer_line(job, width) for job in jobs]
    elif view["status"] == "PRE-START":
        title, lines = "DOWNLOAD / EXTRACT", [paint("WAITING", YELLOW)]
    else:
        return []
    return boxed(title, lines, width, BLUE)


def render_events(view: dict[str, object], width: int, *, limit: int = 4) -> list[str]:
    color_map = {"NEW": CYAN, "UPDATED": YELLOW, "SOLVED": GREEN, "DELETED": RED, "ERROR": RED}
    lines: list[str] = []
    for event in reversed(view["events"][-max(0, limit):] if limit else []):
        try:
            moment = datetime.fromisoformat(str(event["time"])).strftime("%H:%M:%S")
        except ValueError:
            moment = "--:--:--"
        kind = str(event.get("kind") or "INFO")
        lines.append(f"{moment}  {paint(f'[{kind}]', color_map.get(kind, WHITE), bold=True)} {event.get('message', '')}")
    return boxed("RECENT EVENTS", lines, width, YELLOW)


def resource_series(resources: dict[str, object], value_index: int, width: int) -> list[float | None]:
    buckets: list[list[float]] = [[] for _ in range(width)]
    now = float(resources.get("now") or time.monotonic())
    bucket_seconds = RESOURCE_HISTORY_SECONDS / width
    graph_end = math.floor(now / bucket_seconds) * bucket_seconds
    start = graph_end - RESOURCE_HISTORY_SECONDS
    for sample in resources.get("samples", []):
        if not isinstance(sample, (tuple, list)) or len(sample) <= value_index:
            continue
        moment = float(sample[0])
        # Only render completed buckets. Samples in the active bucket used to
        # be clamped into the last cell, making that cell move every second.
        if moment < start or moment >= graph_end:
            continue
        index = int((moment - start) / bucket_seconds)
        if not 0 <= index < width:
            continue
        buckets[index].append(float(sample[value_index]))
    return [sum(bucket) / len(bucket) if bucket else None for bucket in buckets]


def resource_chart(title: str, current: float, peak: float, values: list[float | None], width: int, color: str, detail: str = "") -> list[str]:
    height = 5
    plot_width = max(8, width - 6)
    values = values[-plot_width:]
    if len(values) < plot_width:
        values = [None] * (plot_width - len(values)) + values
    suffix = f"   {detail}" if detail else ""
    lines = [f"{title:<8}{current:>5.1f}%   Peak {peak:>5.1f}%{suffix}"]
    for row in range(height):
        row_base = (height - row - 1) * 8
        cells: list[str] = []
        for value in values:
            if value is None:
                cells.append(" ")
                continue
            units = round(max(0.0, min(100.0, value)) * height * 8 / 100)
            cells.append(PARTIAL_BLOCKS[max(0, min(8, units - row_base))])
        threshold = 100 - row * 20
        lines.append(f"{threshold:>3}% ┤" + paint("".join(cells), color))
    lines.append("  0% ┼" + "─" * plot_width)
    left_label, right_label = "2m ago", "now"
    lines.append("      " + left_label + " " * max(1, plot_width - len(left_label) - len(right_label)) + right_label)
    return [pad(truncate(line, width), width) for line in lines]


def codex_usage_line(usage: dict[str, object], width: int) -> str:
    if usage.get("status") not in {"LIVE", "ERROR"} or not isinstance(usage.get("remaining_percent"), (int, float)):
        return f"CODEX WEEKLY  {paint('WAITING', YELLOW, bold=True)}"
    remaining = max(0.0, min(100.0, float(usage["remaining_percent"])))
    remaining_text = f"{remaining:.0f}%"
    show_credits = remaining_text == "0%"
    credits_text = ""
    if show_credits:
        if usage.get("credits_unlimited"):
            credits = "UNLIMITED"
        else:
            try:
                current_credits = f"{float(str(usage.get('credits_balance') or '0')):,.2f}"
            except ValueError:
                current_credits = "--"
            try:
                start_credits = f"{float(str(usage.get('competition_start_credits') or '0')):,.2f}"
            except ValueError:
                start_credits = "--"
            credits = f"{start_credits} → {current_credits}"
        credits_text = f"  CREDITS {credits}"
    suffix = "  STALE" if usage.get("status") == "ERROR" else ""
    fixed = f"CODEX WEEKLY  {remaining_text} REMAINING{credits_text}{suffix}"
    bar_width = max(10, min(30, width - display_width(fixed) - 5))
    filled = round(bar_width * remaining / 100)
    bar = paint("█" * filled, GREEN) + paint("░" * (bar_width - filled), GRAY)
    return f"CODEX WEEKLY  {remaining_text} REMAINING  {bar}{credits_text}{paint(suffix, RED, bold=True) if suffix else ''}"


def render_resources(resources: dict[str, object], width: int, codex_usage: dict[str, object] | None = None) -> list[str]:
    gap = 2
    body_width = width - 4
    left_width = (body_width - gap) // 2
    right_width = body_width - gap - left_width
    plot_width_left = max(8, left_width - 6)
    plot_width_right = max(8, right_width - 6)
    samples = resources.get("samples", [])
    cpu_values = [float(sample[1]) for sample in samples if isinstance(sample, (tuple, list)) and len(sample) > 2]
    memory_values = [float(sample[2]) for sample in samples if isinstance(sample, (tuple, list)) and len(sample) > 2]
    cpu = float(resources.get("cpu") or 0.0)
    memory = float(resources.get("memory") or 0.0)
    used_gib = float(resources.get("used_gib") or 0.0)
    total_gib = float(resources.get("total_gib") or 0.0)
    cpu_cores = int(resources.get("cpu_cores") or 1)
    left = resource_chart("CPU", cpu, max([cpu, *cpu_values]), resource_series(resources, 1, plot_width_left), left_width, YELLOW, f"{cpu_cores} CORES")
    right = resource_chart("MEMORY", memory, max([memory, *memory_values]), resource_series(resources, 2, plot_width_right), right_width, CYAN, f"{used_gib:.2f} / {total_gib:.2f} GiB")
    chart_lines = [left[index] + " " * gap + right[index] for index in range(len(left))]
    return boxed("SYSTEM RESOURCES", [codex_usage_line(codex_usage or {}, width - 4), "", *chart_lines], width, YELLOW)


def render_resources_compact(resources: dict[str, object], width: int, codex_usage: dict[str, object] | None = None) -> list[str]:
    cpu = float(resources.get("cpu") or 0.0)
    memory = float(resources.get("memory") or 0.0)
    used_gib = float(resources.get("used_gib") or 0.0)
    total_gib = float(resources.get("total_gib") or 0.0)
    cpu_cores = int(resources.get("cpu_cores") or 1)
    summary = f"CPU {cpu:.1f}% · {cpu_cores} CORES    MEMORY {memory:.1f}% · {used_gib:.2f}/{total_gib:.2f} GiB"
    return boxed("SYSTEM RESOURCES · COMPACT", [codex_usage_line(codex_usage or {}, width - 4), summary], width, YELLOW)


def render_koth_compact(view: dict[str, object], width: int) -> list[str]:
    entries = [entry for entry in view.get("koth", {}).values() if isinstance(entry, dict)]
    total = sum(float(entry["points"]) for entry in entries if isinstance(entry.get("points"), (int, float)))
    maximum = len(entries) * KOTH_MAX_POINTS
    return boxed(f"KOTH · {len(entries)} ARENAS · PROJECTED {total:.2f} / {maximum:.0f} pt · COMPACT", [""], width, CYAN)


def render_screen(view: dict[str, object], resources: dict[str, object] | None = None) -> str:
    terminal = shutil.get_terminal_size((120, 40))
    width = max(32, min(terminal.columns, 220))
    height = max(8, terminal.lines)
    left_width = (width - 2) // 2
    right_width = width - 2 - left_width
    status_color = YELLOW if view["status"] == "PRE-START" else RED if view["status"] == "ENDED" else GREEN
    challenges = {key: challenge for key, challenge in view["challenges"].items() if not KOTH_ENABLED or not is_koth_challenge(challenge)}
    solved = sum(bool(challenge.get("solved")) for challenge in challenges.values())
    try:
        score_text = f"{float(view['score']):.2f}"
    except (TypeError, ValueError):
        score_text = str(view.get("score") or "-")
    remaining, remaining_color = competition_countdown(view)
    header = boxed(TITLE, [f"{paint('●', status_color, bold=True)} {paint(str(view['status']), status_color, bold=True)}    TIME REMAINING  {paint(remaining, remaining_color, bold=True)}", f"Team  {view['team_name']}    Challenges  {solved}/{len(challenges)}    Score  {score_text} pt    Rank  {view['rank']}"], width, CYAN)
    resources = resources or {"now": time.monotonic(), "cpu": 0.0, "memory": 0.0, "cpu_cores": os.cpu_count() or 1, "used_gib": 0.0, "total_gib": 0.0, "samples": []}
    transfers = render_transfers(view, width)
    comparison = render_team_comparison(view, width)

    def assemble(*, compact_resources: bool = False, compact_challenges: bool = False, event_limit: int = 4, include_events: bool = True, include_resources: bool = True, compact_koth: bool = False) -> list[str]:
        resource_lines = (render_resources_compact(resources, width, view.get("codex_usage")) if compact_resources else render_resources(resources, width, view.get("codex_usage"))) if include_resources else []
        event_lines = render_events(view, width, limit=event_limit) if include_events else []
        koth_lines = (render_koth_compact(view, width) if compact_koth else render_koth(view, width)) if KOTH_ENABLED else []
        return header + resource_lines + render_challenges(view, left_width, right_width, compact=compact_challenges) + koth_lines + transfers + event_lines + comparison

    lines = assemble()
    if len(lines) > height:
        lines = assemble(compact_resources=True)
    if len(lines) > height:
        lines = assemble(compact_resources=True, compact_challenges=True, event_limit=1)
    if len(lines) > height:
        lines = assemble(compact_resources=True, compact_challenges=True, include_events=False)
    if len(lines) > height:
        lines = assemble(compact_challenges=True, include_events=False, include_resources=False)
    if len(lines) > height:
        lines = assemble(compact_challenges=True, include_events=False, include_resources=False, compact_koth=True)
    if len(lines) > height:
        lines = lines[:height]
    return "\n".join(lines)


def solid_warning_box(message: str, terminal_columns: int) -> list[str]:
    box_width = min(len(message) + 4, max(4, terminal_columns))
    inner_width = max(0, box_width - 4)
    text = message[:inner_width]
    plain = [
        "┌" + "─" * max(0, box_width - 2) + "┐",
        "│ " + text.ljust(inner_width) + " │",
        "└" + "─" * max(0, box_width - 2) + "┘",
    ]
    return [f"{BOLD}{RED_BG}{WHITE}{line}{RESET}" for line in plain]


def terminal_size_warning_overlays(columns: int, rows: int) -> str:
    overlays: list[str] = []

    def place(box: list[str], row: int, column: int) -> None:
        for index, line in enumerate(box):
            overlays.append(f"\033[{row + index};{column}H{line}")

    if rows < MIN_TERMINAL_ROWS and rows >= 3:
        box = solid_warning_box("HEIGHT TOO SMALL", columns)
        box_width = display_width(box[0])
        place(box, rows - len(box) + 1, max(1, (columns - box_width) // 2 + 1))
    if columns < MIN_TERMINAL_COLUMNS and rows >= 3:
        box = solid_warning_box("WIDTH TOO SMALL", columns)
        box_width = display_width(box[0])
        place(box, max(1, (rows - len(box)) // 2 + 1), max(1, columns - box_width + 1))
    return "".join(overlays)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    instance_lock = InstanceLock(LOCK_FILE)
    if not instance_lock.acquire():
        print("CTFd monitor is already running.", file=sys.stderr)
        return 1
    try:
        state = SharedState()
        resources = ResourceSampler()
        stop = threading.Event()
        monitor = Monitor(state, stop)
        worker = threading.Thread(target=monitor.run, name="ctfd-monitor")
        koth_worker = threading.Thread(target=monitor.run_koth, name="ctfd-koth")
        codex_usage_worker = threading.Thread(target=monitor.run_codex_usage, name="codex-usage")
        worker.start()
        koth_worker.start()
        codex_usage_worker.start()
        deadline = time.monotonic() + float(os.environ.get("CTFD_MONITOR_TEST_DURATION", "0")) if TEST_MODE and os.environ.get("CTFD_MONITOR_TEST_DURATION") else None
        sys.stdout.write("\033[?25l")
        previous_frame: list[str] = []
        previous_terminal_size: tuple[int, int] | None = None
        resize_event = threading.Event()
        previous_sigwinch_handler = signal.getsignal(signal.SIGWINCH)
        signal.signal(signal.SIGWINCH, lambda _signum, _frame: resize_event.set())
        try:
            while not stop.is_set():
                resize_event.clear()
                terminal_size = shutil.get_terminal_size((120, 40))
                terminal_key = (terminal_size.columns, terminal_size.lines)
                current_frame = render_screen(state.view(), resources.sample()).splitlines()
                warning_overlays = terminal_size_warning_overlays(terminal_size.columns, terminal_size.lines)
                if previous_terminal_size != terminal_key:
                    sys.stdout.write("\033[H\033[2J" + "\n".join(current_frame) + warning_overlays)
                    sys.stdout.flush()
                else:
                    updates: list[str] = []
                    render_width = display_width(current_frame[0]) if current_frame else 0
                    width_changed = bool(previous_frame and current_frame and display_width(previous_frame[0]) != render_width)
                    for row in range(max(len(previous_frame), len(current_frame))):
                        old_line = previous_frame[row] if row < len(previous_frame) else None
                        new_line = current_frame[row] if row < len(current_frame) else None
                        if old_line == new_line:
                            continue
                        updates.append(f"\033[{row + 1};1H")
                        if width_changed or new_line is None:
                            updates.append("\033[2K")
                        if new_line is not None:
                            updates.append(new_line)
                            if render_width < terminal_size.columns:
                                updates.append("\033[K")
                    if len(current_frame) != len(previous_frame) and len(current_frame) < terminal_size.lines:
                        updates.append(f"\033[{len(current_frame) + 1};1H\033[J")
                    if warning_overlays:
                        updates.append(warning_overlays)
                    if updates:
                        sys.stdout.write("".join(updates))
                        sys.stdout.flush()
                previous_frame = current_frame
                previous_terminal_size = terminal_key
                if deadline is not None and time.monotonic() >= deadline:
                    break
                resize_event.wait(UI_REFRESH_INTERVAL)
        except KeyboardInterrupt:
            pass
        finally:
            signal.signal(signal.SIGWINCH, previous_sigwinch_handler)
            stop.set()
            worker.join()
            koth_worker.join()
            codex_usage_worker.join()
            sys.stdout.write("\033[?25h\n")
            sys.stdout.flush()
    finally:
        instance_lock.release()
    return 0


def headless_main() -> int:
    lock = InstanceLock(LOCK_FILE)
    if not lock.acquire():
        raise RuntimeError("CTFd monitor is already running for this state directory")
    stop = threading.Event()
    old_handlers = {sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGINT, signal.SIGTERM)}
    workers = []
    try:
        state = SharedState()
        monitor = Monitor(state, stop)
        for target in (monitor.run, monitor.run_koth, monitor.run_codex_usage):
            worker = threading.Thread(target=target)
            worker.start()
            workers.append(worker)
        while not stop.wait(POLL_INTERVAL):
            view = state.view()
            print(json.dumps({key: view[key] for key in ('status', 'team_name', 'score', 'rank')}, ensure_ascii=False), flush=True)
    finally:
        stop.set()
        for worker in workers:
            worker.join()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        lock.release()
    return 0


def configure(path: Path | None) -> None:
    global BASE_URL, USERNAME, PASSWORD, TOKEN, TITLE, BASE_DIR, STATE_DIR
    global KOTH_ENABLED, CODEX_ENABLED, HELPER_FILES, AGENTS_TEMPLATE, POLL_INTERVAL, MAX_WORKERS
    global AUTO_EXTRACT, MAX_DOWNLOAD_BYTES, CONTEST_END
    config = tomllib.loads(path.read_text()) if path else {}
    allowed = {'name', 'url', 'root', 'state', 'poll_interval', 'max_workers', 'koth', 'codex_usage', 'helpers', 'agents_template', 'username_env', 'password_env', 'token_env', 'auto_extract', 'max_download_bytes', 'contest_end'}
    unknown = set(config) - allowed
    if unknown:
        raise ValueError(f"Unknown configuration keys: {', '.join(sorted(unknown))}")
    anchor = path.resolve().parent if path else Path.cwd()
    def local(value):
        p = Path(value).expanduser()
        return (anchor / p).resolve()
    BASE_URL = os.environ.get('CTFD_MONITOR_URL', config.get('url', BASE_URL)).rstrip('/')
    parsed = urllib.parse.urlsplit(BASE_URL)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
        raise ValueError('Set a valid http(s) URL in the profile or CTFD_MONITOR_URL')
    TITLE = config.get('name', 'CTFd Monitor')
    USERNAME = os.environ.get(config.get('username_env', 'CTFD_MONITOR_USER'), '')
    PASSWORD = os.environ.get(config.get('password_env', 'CTFD_MONITOR_PASSWORD'), '')
    TOKEN = os.environ.get(config.get('token_env', 'CTFD_MONITOR_TOKEN'), '')
    BASE_DIR = local(os.environ.get('CTFD_MONITOR_ROOT', config.get('root', 'workspace')))
    identity = hashlib.sha256(BASE_URL.encode()).hexdigest()[:12]
    STATE_DIR = local(os.environ.get('CTFD_MONITOR_STATE', config.get('state', str(BASE_DIR / '.ctfd-monitor' / identity))))
    POLL_INTERVAL = float(config.get('poll_interval', POLL_INTERVAL))
    MAX_WORKERS = int(config.get('max_workers', MAX_WORKERS))
    if not math.isfinite(POLL_INTERVAL) or POLL_INTERVAL <= 0 or MAX_WORKERS < 1:
        raise ValueError('poll_interval and max_workers must be positive')
    for key in ('koth', 'codex_usage'):
        if key in config and not isinstance(config[key], bool):
            raise ValueError(f'{key} must be boolean')
    AUTO_EXTRACT = config.get('auto_extract', False)
    if not isinstance(AUTO_EXTRACT, bool):
        raise ValueError('auto_extract must be boolean')
    MAX_DOWNLOAD_BYTES = int(config.get('max_download_bytes', 2 * 1024**3))
    if MAX_DOWNLOAD_BYTES < 1:
        raise ValueError('max_download_bytes must be positive')
    CONTEST_END = config.get('contest_end', '')
    if CONTEST_END:
        parsed_end = datetime.fromisoformat(CONTEST_END.replace('Z', '+00:00'))
        if parsed_end.tzinfo is None:
            raise ValueError('contest_end requires a timezone')
    KOTH_ENABLED = config.get('koth', False)
    CODEX_ENABLED = config.get('codex_usage', False)
    helpers = config.get('helpers', [])
    if not isinstance(helpers, list) or any(not isinstance(x, str) or Path(x).name != x for x in helpers):
        raise ValueError('helpers must be a list of file names')
    HELPER_FILES = tuple(helpers)
    AGENTS_TEMPLATE = local(config['agents_template']) if config.get('agents_template') else None
    if AGENTS_TEMPLATE and not AGENTS_TEMPLATE.is_file():
        raise ValueError('agents_template does not exist')
    names = {'CURRENT_FILE': 'current.json', 'EVENT_FILE': 'events.jsonl', 'SNAPSHOT_DIR': 'snapshots', 'ARCHIVE_DIR': 'archive', 'MANIFEST_FILE': 'manifest.json', 'KOTH_FILE': 'koth.json', 'CODEX_USAGE_FILE': 'codex-usage.json', 'LOCK_FILE': 'monitor.lock', 'STAGING_DIR': 'staging'}
    for name, relative in names.items():
        globals()[name] = STATE_DIR / relative


def diagnose(network: bool) -> int:
    report = {'url': BASE_URL, 'root': str(BASE_DIR), 'state': str(STATE_DIR), 'checks': {}}
    checks = report['checks']
    checks['credentials'] = 'ok' if TOKEN or (USERNAME and PASSWORD) else 'missing'
    try:
        Monitor.find_helpers()
        checks['helpers'] = 'ok'
    except OSError as error:
        checks['helpers'] = str(error)
    failed = any(v != 'ok' for v in checks.values())
    if network and not failed:
        client = CTFdClient(BASE_URL, USERNAME, PASSWORD)
        try:
            client.login()
            checks['login'] = 'ok'
        except Exception as error:
            checks['login'] = f'failed ({type(error).__name__})'
            failed = True
        if not failed:
            for label, routes in {'challenges': ('/api/v1/challenges', '/api/v2/challenges'), 'account': ('/api/v1/users/me',), 'team': ('/api/v1/teams/me',), 'scoreboard': ('/api/v1/scoreboard', '/api/v2/scoreboard/full')}.items():
                try:
                    result = client.request_json_routes(routes)
                    checks[label] = 'ok' if result.get('data') is not None else 'empty'
                except ApiError as error:
                    checks[label] = f'unverified (HTTP {error.status})'
                except Exception as error:
                    checks[label] = f'unverified ({type(error).__name__})'
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failed else 0


def cli() -> int:
    global HEADLESS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--headless', action='store_true', help='Print JSON status lines without terminal control')
    parser.add_argument('--version', action='version', version='ctfd-monitor 0.1.0')
    parser.add_argument('--config', type=Path, help='Competition TOML profile')
    parser.add_argument('command', choices=('run', 'doctor', 'probe'), nargs='?', default='run')
    args = parser.parse_args()
    HEADLESS = args.headless or not sys.stdout.isatty()
    configure(args.config)
    if args.command != 'run':
        return diagnose(args.command == 'probe')
    if not TOKEN and not (USERNAME and PASSWORD):
        raise ValueError('Set token or username/password environment variables')
    return headless_main() if HEADLESS else main()


def entrypoint() -> int:
    try:
        return cli()
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(entrypoint())
