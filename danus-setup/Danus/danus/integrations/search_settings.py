"""User-owned search preferences, shared by HTTP, MCP and CLI tool calls.

Controls retrieval tools, not an OS network firewall. Read on every call so
workers and their verifiers observe project changes without restarting.
"""
from __future__ import annotations

import contextvars
import copy
import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path

WEB_PROVIDERS = [
    {"id": "bing", "name": "Bing", "description": "Web search via SearXNG", "kind": "web"},
    {"id": "brave", "name": "Brave", "description": "Web search via SearXNG", "kind": "web"},
    {"id": "duckduckgo", "name": "DuckDuckGo", "description": "Web search via SearXNG; may require a CAPTCHA", "kind": "web"},
    {"id": "google", "name": "Google", "description": "Web search via SearXNG; may be rate limited", "kind": "web"},
    {"id": "wikipedia", "name": "Wikipedia", "description": "Free official API for encyclopedia articles and background", "kind": "api"},
    {"id": "duckduckgo_answers", "name": "DuckDuckGo Instant Answers", "description": "Free summaries and definitions, with limited web coverage", "kind": "api"},
]
PAPER_PROVIDERS = [
    {"id": "arxiv", "name": "arXiv", "description": "Papers, abstracts, and full-text reading"},
    {"id": "crossref", "name": "Crossref", "description": "Paper titles, authors, DOIs, and bibliographic metadata"},
    {"id": "iacr", "name": "IACR ePrint", "description": "Cryptography paper metadata and abstracts"},
    {"id": "matlas", "name": "Matlas", "description": "Mathematical theorem and lemma search"},
]
DEFAULT = {"enabled": True, "web_engines": ["bing", "wikipedia"],
           "paper_sources": ["arxiv", "crossref", "iacr", "matlas"]}
OFF = {"enabled": False, "web_engines": [], "paper_sources": []}
_scope = contextvars.ContextVar("search_scope", default=None)


def settings_path():
    from .literature import _cache_root
    return Path(os.environ.get("DANUS_SEARCH_SETTINGS_FILE", str(_cache_root().parent / "search-settings.json")))


def validate(value):
    if not isinstance(value, dict) or type(value.get("enabled")) is not bool:
        raise ValueError("Invalid search toggle format")
    clean = {"enabled": value["enabled"]}
    for field, providers in (("web_engines", WEB_PROVIDERS), ("paper_sources", PAPER_PROVIDERS)):
        choices = value.get(field)
        allowed = {p["id"] for p in providers}
        if not isinstance(choices, list) or any(not isinstance(v, str) or v not in allowed for v in choices):
            raise ValueError("Unsupported search source")
        clean[field] = list(dict.fromkeys(choices))
    return clean


def _read(path):
    if path.is_symlink():
        raise ValueError("Invalid search preferences path")
    if not path.exists():
        return None
    if path.stat().st_size > 65536:
        raise ValueError("Search preferences file is too large")
    return json.loads(path.read_text(encoding="utf-8"))


def read_global():
    data = _read(settings_path())
    if data is None:
        return {"chat": copy.deepcopy(DEFAULT), "danus": copy.deepcopy(DEFAULT)}
    return {scope: validate(data[scope]) for scope in ("chat", "danus")}


def _write(path, value):
    if path.is_symlink():
        raise ValueError("Invalid search preferences path")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_global(scope, value):
    if scope not in ("chat", "danus"):
        raise ValueError("Unsupported search scope")
    clean = validate(value)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = read_global()
        data[scope] = clean
        _write(path, data)
    return clean


def project_settings(directory):
    if not directory:
        return None
    path = Path(directory)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Project search preferences not found")
    value = _read(path / "search-settings.json")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Invalid project search preferences format")
    if value.get("inherit") is True:
        return None
    return validate(value)


def write_project(directory, value=None):
    # The HTTP caller validates project containment before invoking this.
    if Path(directory).is_symlink():
        raise ValueError("Invalid project path")
    _write(Path(directory) / "search-settings.json",
           {"inherit": True} if value is None else {"inherit": False, **validate(value)})


@contextmanager
def scope(kind, directory=None):
    token = _scope.set((kind, str(directory) if directory else None))
    try:
        yield
    finally:
        _scope.reset(token)


def effective(kind=None, directory=None):
    if kind is None:
        current = _scope.get()
        if current:
            kind, directory = current
        else:
            kind = "danus"
            directory = os.environ.get("DANUS_SEARCH_PROJECT_DIR") or os.environ.get("DANUS_PROJECT_DIR")
    try:
        defaults = read_global()[kind]
        custom = project_settings(directory) if kind == "danus" and directory else None
        return {**(custom or defaults), "scope": kind, "inherited": custom is None}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {**OFF, "scope": kind, "inherited": False, "error": "Cannot read search preferences. Online search is paused: " + str(exc)}


def denial(provider=None, *, policy=None):
    policy = policy or effective()
    reason = policy.get("error")
    if not policy["enabled"]:
        reason = reason or "The user has disabled web search and paper tools in this scope. Answer using existing information. Do not bypass this preference with other tools, curl, or websites."
    elif provider and provider not in policy["web_engines"] + policy["paper_sources"]:
        reason = "The user has not enabled this search source: " + provider + ". Use enabled sources and do not bypass the preferences."
    return {"disabled": True, "error": reason, "results": [], "count": 0} if reason else None
