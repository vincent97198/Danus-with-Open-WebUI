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
    {"id": "bing", "name": "Bing", "description": "一般網頁搜尋 · 經 SearXNG", "kind": "web"},
    {"id": "brave", "name": "Brave", "description": "一般網頁搜尋 · 經 SearXNG", "kind": "web"},
    {"id": "duckduckgo", "name": "DuckDuckGo", "description": "一般網頁搜尋 · 經 SearXNG，可能要求驗證", "kind": "web"},
    {"id": "google", "name": "Google", "description": "一般網頁搜尋 · 經 SearXNG，可能限流", "kind": "web"},
    {"id": "wikipedia", "name": "Wikipedia", "description": "官方免費 API · 百科與背景知識", "kind": "api"},
    {"id": "duckduckgo_answers", "name": "DuckDuckGo 即時答案", "description": "免費端點 · 摘要與定義，非完整網頁搜尋", "kind": "api"},
]
PAPER_PROVIDERS = [
    {"id": "arxiv", "name": "arXiv", "description": "論文、摘要與原文閱讀"},
    {"id": "crossref", "name": "Crossref", "description": "論文題名、作者、DOI 與書目資料"},
    {"id": "iacr", "name": "IACR ePrint", "description": "密碼學論文目錄與摘要"},
    {"id": "matlas", "name": "Matlas", "description": "數學定理與引理搜尋"},
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
        raise ValueError("搜尋開關格式不正確")
    clean = {"enabled": value["enabled"]}
    for field, providers in (("web_engines", WEB_PROVIDERS), ("paper_sources", PAPER_PROVIDERS)):
        choices = value.get(field)
        allowed = {p["id"] for p in providers}
        if not isinstance(choices, list) or any(not isinstance(v, str) or v not in allowed for v in choices):
            raise ValueError("含有不支援的搜尋來源")
        clean[field] = list(dict.fromkeys(choices))
    return clean


def _read(path):
    if path.is_symlink():
        raise ValueError("搜尋設定路徑不正確")
    if not path.exists():
        return None
    if path.stat().st_size > 65536:
        raise ValueError("搜尋設定過大")
    return json.loads(path.read_text(encoding="utf-8"))


def read_global():
    data = _read(settings_path())
    if data is None:
        return {"chat": copy.deepcopy(DEFAULT), "danus": copy.deepcopy(DEFAULT)}
    return {scope: validate(data[scope]) for scope in ("chat", "danus")}


def _write(path, value):
    if path.is_symlink():
        raise ValueError("搜尋設定路徑不正確")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_global(scope, value):
    if scope not in ("chat", "danus"):
        raise ValueError("不支援的搜尋設定範圍")
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
        raise ValueError("找不到專案的搜尋設定")
    value = _read(path / "search-settings.json")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("專案搜尋設定格式不正確")
    if value.get("inherit") is True:
        return None
    return validate(value)


def write_project(directory, value=None):
    # The HTTP caller validates project containment before invoking this.
    if Path(directory).is_symlink():
        raise ValueError("專案路徑不正確")
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
        return {**OFF, "scope": kind, "inherited": False, "error": "無法讀取搜尋設定，已暫停外部搜尋：" + str(exc)}


def denial(provider=None, *, policy=None):
    policy = policy or effective()
    reason = policy.get("error")
    if not policy["enabled"]:
        reason = reason or "使用者已關閉此範圍的網路搜尋與論文工具。請依現有資料回答，不要改用其他工具、curl 或網頁繞過此設定。"
    elif provider and provider not in policy["web_engines"] + policy["paper_sources"]:
        reason = "使用者未啟用此搜尋來源：" + provider + "。請使用已啟用來源，不要繞過設定。"
    return {"disabled": True, "error": reason, "results": [], "count": 0} if reason else None
