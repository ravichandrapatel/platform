#!/usr/bin/env python3
"""
FILE_NAME: trigger_app.py
DESCRIPTION: Master Clock – OpenShift trigger app for GitHub Actions workflow_dispatch.
  Millisecond-precision intervals; config /etc/config/repos.json, token /etc/github/token (ESO).
  return_run_details=true for workflow_run_id/run_url. Retries, token/config reload, health HTTP.
VERSION: 1.0.0
EXIT_CODES: 0 = success or no repos, 1 = token/config error
AUTHORS: Platform / DevOps
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional

CONFIG_PATH = "/etc/config/repos.json"
TOKEN_PATH = "/etc/github/token"
API_BASE = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
RUNS_PAGE_SIZE = 5
DEFAULT_REF = "main"
TOKEN_RELOAD_INTERVAL = 600  # 10 minutes
CONFIG_RELOAD_CHECK_INTERVAL = 60  # seconds between mtime checks
DISPATCH_RETRIES = 3
DISPATCH_BACKOFF_SEC = 5
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "8080"))

# Shared state for health endpoint and main loop
_ready = [False]  # True when token + config loaded and loop has started
_shutdown = [False]
_config_mtime: list[float] = [0.0]
_health_server: list[HTTPServer] = []


def _read_file(path: str, key: Optional[str] = None) -> str:
    """INTENT: Read file or dir (password/token); optionally extract key=value. INPUT: path, key (optional). OUTPUT: str. SIDE_EFFECTS: Disk read."""
    if os.path.isdir(path):
        for k in ("password", "token"):
            p = os.path.join(path, k)
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    return f.read().strip()
        return ""
    with open(path, "r", encoding="utf-8") as f:
        data = f.read()
    if key:
        for line in data.strip().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == key:
                    return v.strip()
            elif key in ("password", "token") and not line.strip().startswith("#"):
                return line.strip()
        return data.strip()
    return data.strip()


def _read_token() -> str:
    """INTENT: Load GitHub token from TOKEN_PATH or sibling password file. INPUT: None. OUTPUT: str. SIDE_EFFECTS: Disk read."""
    if os.path.isdir(TOKEN_PATH):
        return _read_file(TOKEN_PATH)
    if os.path.isfile(TOKEN_PATH):
        return _read_file(TOKEN_PATH)
    alt = os.path.join(os.path.dirname(TOKEN_PATH), "password")
    return _read_file(alt) if os.path.isfile(alt) else ""


def _load_config() -> Dict[str, Dict[str, Any]]:
    """INTENT: Load and validate repos.json (owner, repo, workflow_id, interval_seconds per entry). INPUT: None. OUTPUT: dict. SIDE_EFFECTS: Disk read. Raises ValueError on invalid."""
    raw = _read_file(CONFIG_PATH)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("repos.json must be a JSON object")
    for name, cfg in data.items():
        if not isinstance(cfg, dict) or not all(k in cfg for k in ("owner", "repo", "workflow_id", "interval_seconds")):
            raise ValueError(f"repos.json entry '{name}' must have owner, repo, workflow_id, interval_seconds")
    return data


def _log(level: str, message: str, **extra: Any) -> None:
    """INTENT: Emit JSON log line to stdout. INPUT: level, message, **extra. OUTPUT: None. SIDE_EFFECTS: stdout."""
    record = {"level": level, "message": message, "ts": time.time()}
    record.update(extra)
    print(json.dumps(record), flush=True)


def _request(
    token: str,
    method: str,
    path: str,
    data: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, str]] = None,
) -> tuple[int, Optional[Dict[str, Any]]]:
    """INTENT: HTTP request to GitHub API; return (status_code, json_body). INPUT: token, method, path, data, query. OUTPUT: tuple. SIDE_EFFECTS: Network."""
    from urllib.parse import urlencode
    url = f"{API_BASE}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "master-clock-trigger",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        # _log("[ERR-T-01] HTTPError in _request", code=e.code, path=path)
        raw = e.read().decode("utf-8") if e.fp else ""
        return e.code, (json.loads(raw) if raw.strip() else None)


def get_latest_run_created_at(token: str, owner: str, repo: str) -> Optional[float]:
    """INTENT: Get created_at timestamp of latest workflow run for repo. INPUT: token, owner, repo. OUTPUT: float | None. SIDE_EFFECTS: Network."""
    path = f"/repos/{owner}/{repo}/actions/runs"
    code, data = _request(token, "GET", path, query={"per_page": str(RUNS_PAGE_SIZE)})
    if code != 200 or not data or not isinstance(data.get("workflow_runs"), list):
        return None
    runs = data["workflow_runs"]
    if not runs:
        return None
    created = runs[0].get("created_at")
    if not created:
        return None
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        # _log("[ERR-T-02] get_latest_run_created_at parse failed", owner=owner, repo=repo)
        return None


def trigger_workflow(
    token: str,
    owner: str,
    repo: str,
    workflow_id: str,
    ref: str = DEFAULT_REF,
    inputs: Optional[Dict[str, str]] = None,
) -> tuple[bool, Optional[int], Optional[str], Optional[str]]:
    """INTENT: POST workflow_dispatch; return (ok, run_id, run_url, html_url). INPUT: token, owner, repo, workflow_id, ref, inputs. OUTPUT: tuple. SIDE_EFFECTS: Network."""
    path = f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches"
    query = {"return_run_details": "true"}
    body = {"ref": ref}
    if inputs:
        body["inputs"] = inputs
    code, data = _request(token, "POST", path, data=body, query=query)
    if code == 204:
        _log("warn", "workflow_dispatch returned 204; return_run_details may be unsupported", owner=owner, repo=repo, workflow_id=workflow_id)
        return True, None, None, None
    if code != 200:
        _log("error", "workflow_dispatch failed", code=code, body=data, owner=owner, repo=repo, workflow_id=workflow_id)
        return False, None, None, None
    run_id = data.get("workflow_run_id") if isinstance(data, dict) else None
    run_url = data.get("run_url") if isinstance(data, dict) else None
    html_url = data.get("html_url") if isinstance(data, dict) else None
    return True, run_id, run_url, html_url


def trigger_workflow_with_retry(
    token: str,
    owner: str,
    repo: str,
    workflow_id: str,
    ref: str,
    inputs: Optional[Dict[str, str]],
    app_name: str,
) -> tuple[bool, Optional[int], Optional[str], Optional[str]]:
    """INTENT: Call trigger_workflow with backoff retries. INPUT: token, owner, repo, workflow_id, ref, inputs, app_name. OUTPUT: same as trigger_workflow. SIDE_EFFECTS: Network, sleep."""
    for attempt in range(1, DISPATCH_RETRIES + 1):
        ok, run_id, run_url, html_url = trigger_workflow(token, owner, repo, workflow_id, ref=ref, inputs=inputs)
        if ok:
            return True, run_id, run_url, html_url
        if attempt < DISPATCH_RETRIES:
            _log("info", "retry after backoff", app_name=app_name, attempt=attempt, backoff_sec=DISPATCH_BACKOFF_SEC)
            time.sleep(DISPATCH_BACKOFF_SEC)
    return False, None, None, None


def run_once(config: Dict[str, Dict[str, Any]], token: str, last_fire: Dict[str, float]) -> None:
    """INTENT: For each repo, dispatch workflow if interval elapsed; update last_fire. INPUT: config, token, last_fire (mutated). OUTPUT: None. SIDE_EFFECTS: Network, last_fire updates."""
    now = time.time()
    default_ref = os.getenv("GITHUB_REF_NAME", DEFAULT_REF)
    for app_name, cfg in config.items():
        owner = cfg["owner"]
        repo = cfg["repo"]
        workflow_id = str(cfg["workflow_id"])
        interval = int(cfg["interval_seconds"])
        ref = cfg.get("ref") or default_ref
        last = last_fire.get(app_name, 0.0)
        if (now - last) < interval:
            continue
        ok, run_id, run_url, html_url = trigger_workflow_with_retry(
            token, owner, repo, workflow_id, ref, cfg.get("inputs"), app_name
        )
        if ok:
            last_fire[app_name] = now
            _log(
                "info",
                "triggered",
                app_name=app_name,
                owner=owner,
                repo=repo,
                workflow_id=workflow_id,
                workflow_run_id=run_id,
                run_url=run_url,
                html_url=html_url,
            )
        else:
            _log("error", "trigger failed after retries", app_name=app_name, owner=owner, repo=repo, workflow_id=workflow_id)


class HealthHandler(BaseHTTPRequestHandler):
    """ROLE: HTTP handler for /health, /ready, /live; returns 200 when _ready else 503. Suppresses log_message."""

    def do_GET(self):
        if self.path in ("/", "/health", "/ready", "/live"):
            if _ready[0]:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            else:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"not ready"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def run_health_server() -> None:
    """INTENT: Start HTTP server on HEALTH_PORT for liveness/readiness; blocks. INPUT: None. OUTPUT: None. SIDE_EFFECTS: Network bind, _health_server list."""
    server = HTTPServer(("0.0.0.0", HEALTH_PORT), HealthHandler)
    _health_server.append(server)
    server.serve_forever()


def main() -> int:
    """INTENT: Load token and config, start health server, run dispatch loop with token/config reload. INPUT: None (argv, env). OUTPUT: exit code. SIDE_EFFECTS: Disk, network, stdout."""
    # _log("[T-01] Master Clock main starting")
    def on_sigterm(_signum: int, _frame: Any) -> None:
        _log("info", "Shutting down...")
        _shutdown[0] = True

    signal.signal(signal.SIGTERM, on_sigterm)

    token = ""
    try:
        token = _read_token()
    except FileNotFoundError:
        # _log("[ERR-T-03] Token file not found")
        _log("error", "Token file not found", path=TOKEN_PATH)
        return 1
    if not token:
        _log("error", "Token is empty", path=TOKEN_PATH)
        return 1

    try:
        config = _load_config()
    except Exception as e:
        # _log("[ERR-T-04] Invalid config")
        _log("error", "Invalid config", path=CONFIG_PATH, error=str(e))
        return 1

    if not config:
        _log("warn", "No repos configured", path=CONFIG_PATH)
        return 0

    last_fire: Dict[str, float] = {}
    for app_name, cfg in config.items():
        owner = cfg["owner"]
        repo = cfg["repo"]
        ts = get_latest_run_created_at(token, owner, repo)
        if ts is not None:
            last_fire[app_name] = ts
            _log("info", "initial last_fire from latest run", app_name=app_name, last_fire_time=ts)
        else:
            last_fire[app_name] = 0.0

    if os.path.isfile(CONFIG_PATH):
        _config_mtime[0] = os.path.getmtime(CONFIG_PATH)

    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    _log("info", "Master Clock started", repos=list(config.keys()))
    _ready[0] = True

    last_token_reload = time.time()
    last_config_check = time.time()

    while not _shutdown[0]:
        try:
            now = time.time()
            if now - last_token_reload >= TOKEN_RELOAD_INTERVAL:
                try:
                    new_token = _read_token()
                    if new_token:
                        token = new_token
                        last_token_reload = now
                        _log("info", "token reloaded")
                except Exception as e:
                    _log("warn", "token reload failed", error=str(e))

            if now - last_config_check >= CONFIG_RELOAD_CHECK_INTERVAL:
                last_config_check = now
                if os.path.isfile(CONFIG_PATH):
                    mtime = os.path.getmtime(CONFIG_PATH)
                    if mtime != _config_mtime[0]:
                        try:
                            new_config = _load_config()
                            if new_config:
                                for k in new_config:
                                    if k not in last_fire:
                                        last_fire[k] = 0.0
                                config = new_config
                                _config_mtime[0] = mtime
                                _log("info", "config reloaded", repos=list(config.keys()))
                        except Exception as e:
                            _log("warn", "config reload failed", error=str(e))

            run_once(config, token, last_fire)
        except Exception as e:
            # _log("[ERR-T-05] loop error")
            _log("error", "loop error", error=str(e))
        time.sleep(1)

    if _health_server:
        _health_server[0].shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
