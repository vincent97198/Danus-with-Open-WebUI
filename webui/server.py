"""Local model chat and Danus project controls."""

import json
import os
import re
import fcntl
import asyncio
import time
import uuid
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictBool
from typing import Literal
from danus.integrations import search_settings

app = FastAPI(title="Local LLM + Danus")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
from research_api import research_app
app.mount("/research", research_app)
MODEL_BASE_URL = os.environ.get("MODEL_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
MODEL_NAME = os.environ.get("MODEL_NAME", "Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf")
DANUS_ROOT = Path(os.environ.get("DANUS_ROOT", "/opt/danus"))
DANUS_STATUS_API = os.environ.get("DANUS_STATUS_API", "").rstrip("/")
PROJECT_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,49}$")


class NewProject(BaseModel):
    name: str = Field(default="", max_length=50)
    title: str = Field(default="", max_length=100)
    problem: str = Field(min_length=1, max_length=20000)
    start: bool = False
    search_mode: Literal["inherit", "on", "off"] = "inherit"


class SearchPreferences(BaseModel):
    enabled: StrictBool
    web_engines: list[str] = Field(max_length=10)
    paper_sources: list[str] = Field(max_length=10)


class ProjectSearchPreferences(SearchPreferences):
    inherit: bool = False


class Assignment(BaseModel):
    task: str = Field(min_length=1, max_length=20000)


class StopProject(BaseModel):
    mode: str = "immediate"


class PurgeTrash(BaseModel):
    confirm: bool = False


class ProjectUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=100)


def project_name(name):
    if not PROJECT_NAME.fullmatch(name):
        raise HTTPException(400, "專案名稱須以小寫英文字母開頭，僅使用小寫英數字、- 或 _。")
    return name


def read_json_file(path: Path):
    try:
        if path.is_symlink() or path.stat().st_size > 65536:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json_file(path: Path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex[:8] + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def danus():
    try:
        from danus.orchestration import cli
        from danus.execution import layout
        return cli, layout
    except ImportError as exc:
        raise HTTPException(503, "Danus 尚未就緒，請確認 Docker 服務已啟動。") from exc


def run_danus(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except SystemExit as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, f"Danus 執行失敗：{exc}") from exc


@app.get("/", response_class=HTMLResponse)
async def root():
    return (Path(__file__).parent / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{MODEL_BASE_URL}/health")
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=503)


@app.get("/api/models")
async def models():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{MODEL_BASE_URL}/v1/models")
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, f"無法取得模型：{exc}") from exc


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
        raise HTTPException(400, "messages 格式不正確")
    body["model"] = MODEL_NAME
    return await forward_chat(body)


@app.get("/v1/models")
async def compatible_models():
    return await models()


@app.head("/v1")
async def compatible_head():
    return JSONResponse({"status": "ok"})


@app.post("/v1/chat/completions")
async def compatible_chat(request: Request):
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
        raise HTTPException(400, "messages 格式不正確")
    # The Qwen Jinja template requires one system message at the beginning.
    system_text = []
    other_messages = []
    for message in body["messages"]:
        if message.get("role") == "system":
            system_text.append(str(message.get("content") or ""))
        else:
            other_messages.append(message)
    body["messages"] = ([{"role": "system", "content": "\n\n".join(system_text)}]
                        if system_text else []) + other_messages
    if "max_completion_tokens" in body:
        body["max_tokens"] = body.pop("max_completion_tokens")
    body.pop("reasoning_effort", None)
    body["model"] = MODEL_NAME
    return await forward_chat(body)


async def forward_chat(body):
    if not body.get("stream", True):
        try:
            async with httpx.AsyncClient(timeout=900) as client:
                response = await client.post(f"{MODEL_BASE_URL}/v1/chat/completions", json=body)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, f"模型呼叫失敗：{exc}") from exc

    async def events():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(900, connect=10)) as client:
                async with client.stream("POST", f"{MODEL_BASE_URL}/v1/chat/completions", json=body) as response:
                    if response.is_error:
                        detail = (await response.aread()).decode("utf-8", errors="replace")[:1000]
                        yield f"data: {json.dumps({'error': f'模型回傳 HTTP {response.status_code}: {detail}'}, ensure_ascii=False)}\n\n"
                        return
                    async for chunk in response.aiter_bytes():
                        yield chunk
        except httpx.HTTPError as exc:
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/danus/health")
async def danus_health():
    installed = (DANUS_ROOT / "runtime" / "venv" / "bin" / "python").exists()
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get("http://127.0.0.1:8091/health")
            verifier = response.status_code == 200
    except httpx.HTTPError:
        verifier = False
    return {"installed": installed, "verifier": verifier}


@app.get("/api/danus/projects")
async def projects():
    cli, layout = danus()
    rows = run_danus(cli.do_list)
    for row in rows:
        directory = layout.project_dir(row["project"])
        metadata = read_json_file(directory / "portal.json")
        statuses = run_danus(cli.do_status, row["project"])
        row["title"] = metadata.get("title") or row["project"]
        row["fact_count"] = len(list((directory / "fact_graph" / "facts").glob("*.md")))
        row["workers_detail"] = [
            {**status, "stop_requested": bool(status.get("alive") and
             (layout.worker_dir(row["project"], status["worker"]) / ".stop").exists())}
            for status in statuses]
    return rows


@app.post("/api/danus/projects")
async def new_project(payload: NewProject):
    cli, layout = danus()
    title = payload.title.strip() or payload.name.strip() or "新的數學專案"
    name = payload.name.strip()
    if not name:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        if not slug or not slug[0].isalpha():
            slug = "math"
        name = slug[:32] + "-" + uuid.uuid4().hex[:6]
    name = project_name(name)
    problem = payload.problem.strip()
    if not problem:
        raise HTTPException(400, "請輸入數學問題。")
    created = run_danus(cli.do_new, name, roles="high:1")
    (layout.project_dir(name) / "PROBLEM.md").write_text(problem + "\n", encoding="utf-8")
    write_json_file(layout.project_dir(name) / "portal.json",
                    {"title": title, "created_at": time.time()})
    if payload.search_mode != "inherit":
        preferences = search_settings.effective("danus")
        search_settings.write_project(layout.project_dir(name), {**preferences, "enabled": payload.search_mode == "on"})
    worker = created["workers"][0]
    run_danus(cli.do_assign, f"{name}/{worker}", problem)
    if payload.start:
        run_danus(cli.do_start, name)
    return {"name": name, "title": title, "workers": created["workers"], "started": payload.start}


@app.get("/api/danus/projects/{name}")
async def project(name: str):
    cli, layout = danus()
    name = project_name(name)
    directory = layout.project_dir(name)
    if not directory.is_dir():
        raise HTTPException(404, "找不到專案")
    problem_file = directory / "PROBLEM.md"
    return {"name": name, "title": read_json_file(directory / "portal.json").get("title") or name,
            "problem": problem_file.read_text(encoding="utf-8") if problem_file.exists() else "",
            "workers": run_danus(cli.do_status, name),
            "search": search_settings.effective("danus", directory)}


def recent_file_lines(path: Path, max_bytes: int = 65536, max_lines: int = 80):
    """Read a bounded tail of a worker-owned file, including a live round log."""
    if path.is_symlink() or not path.is_file():
        return []
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - max_bytes))
            data = stream.read(max_bytes)
        if size > max_bytes:
            data = data.partition(b"\n")[2]
        return data.decode("utf-8", errors="replace").splitlines()[-max_lines:]
    except OSError:
        return []


def worker_log_path(worker_dir: Path, round_number: int):
    logs = worker_dir / "logs"
    if logs.is_symlink() or not logs.is_dir():
        return None
    selected = logs / f"round_{round_number}.log"
    if selected.is_file() and not selected.is_symlink():
        return selected
    candidates = [
        (int(match.group(1)), path)
        for path in logs.glob("round_*.log")
        if path.is_file() and not path.is_symlink()
        and (match := re.fullmatch(r"round_(\d+)\.log", path.name))
    ]
    return max(candidates, default=(0, None))[1]


def progress_log_lines(lines):
    """Remove repeated launch metadata and assignment text from a log excerpt."""
    header_prefixes = (
        "Reading additional input", "OpenAI Codex", "workdir:", "model:",
        "provider:", "approval:", "sandbox:", "reasoning effort:",
        "reasoning summaries:", "session id:", "You are worker '",
        "1. Read TASK.md", "2. Follow AGENTS.md", "3. Resume from state:",
        "4. Keep going:", "5. Persist as you go:", "tokens used",
    )
    return [redact_log_line(line[:500]) for line in lines
            if line.strip() and line not in ("--------", "user")
            and not line.startswith(header_prefixes)]


def redact_log_line(line: str) -> str:
    line = re.sub(r"(?i)(bearer\s+)[a-z0-9._~-]{8,}", r"\1[隱藏]", line)
    line = re.sub(r"(?i)\bsk-[a-z0-9_-]{8,}", "[隱藏金鑰]", line)
    line = re.sub(r"(?i)((?:api[_-]?key|access[_-]?token|password)\s*[:=]\s*['\"]?)[^\s,'\"]+",
                  r"\1[隱藏]", line)
    return line


def activity_events(lines, worker, round_number):
    """Show model updates and explicit errors; keep command output in the log."""
    messages = []
    current = []
    in_update = False

    def flush():
        if current:
            messages.append({"time": None, "kind": "模型更新",
                             "text": redact_log_line("\n".join(current))[:700]})
            current.clear()

    for line in lines:
        if line.strip() in ("codex", "assistant"):
            flush()
            in_update = True
            continue
        if line.strip() in ("exec", "thinking", "user", "tokens used") or line.startswith("tool "):
            flush()
            in_update = False
            continue
        match = re.match(r"^(\d{4}-\d\d-\d\dT\S+) (ERROR|WARN)\s+(.*)", line)
        if match:
            flush()
            messages.append({"time": match.group(1), "kind": "錯誤" if match.group(2) == "ERROR" else "警告",
                             "text": redact_log_line(match.group(3))[:700]})
            continue
        if in_update and line.strip():
            current.append(line[:700])
    flush()
    seen = set()
    events = []
    for message in reversed(messages):
        if message["text"] in seen:
            continue
        seen.add(message["text"])
        events.append({**message, "worker": worker, "round": round_number})
    return events[:20]


async def authoritative_workers(name: str):
    if not DANUS_STATUS_API:
        cli, _ = danus()
        return run_danus(cli.do_status, name)
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(f"{DANUS_STATUS_API}/api/danus/projects/{name}")
            response.raise_for_status()
            return response.json()["workers"]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(503, "無法確認 worker 狀態，請稍後重試。") from exc


@app.get("/api/danus/projects/{name}/progress")
async def project_progress(name: str):
    _, layout = danus()
    name = project_name(name)
    directory = layout.project_dir(name)
    if not directory.is_dir() or directory.is_symlink():
        raise HTTPException(404, "找不到專案")

    workers = []
    events = []
    for status in await authoritative_workers(name):
        worker_name = status.get("worker", "")
        if worker_name not in layout.list_workers(name):
            continue
        home = layout.worker_dir(name, worker_name)
        if home.is_symlink():
            continue
        round_number = max(0, min(int(status.get("round") or 0), 1000000))
        log_path = worker_log_path(home, round_number)
        raw_lines = recent_file_lines(log_path, max_lines=240) if log_path else []
        lines = progress_log_lines(raw_lines)
        excerpt = "\n".join(lines[-35:])[-8000:]
        last_log_at = None
        if log_path:
            try:
                last_log_at = datetime.fromtimestamp(log_path.stat().st_mtime,
                                                     timezone.utc).isoformat()
            except OSError:
                pass
        details = read_json_file(home / ".status.json")
        round_start = details.get("round_started_at")
        elapsed = max(0, time.time() - round_start) if isinstance(round_start, (int, float)) else None
        workers.append({**status, "log_tail": excerpt, "last_log_at": last_log_at,
                        "elapsed_s": elapsed if status.get("alive") else None,
                        "stop_requested": bool(status.get("alive") and (home / ".stop").exists()),
                        "last_rc": details.get("last_rc"), "error": details.get("error")})

        events.extend(activity_events(raw_lines, worker_name, round_number))

    return {"project": name, "workers": workers, "recent_events": events[:20],
            "updated_at": datetime.now(timezone.utc).isoformat()}


def existing_project(name: str) -> Path:
    _, layout = danus()
    name = project_name(name)
    root = layout.agents_root().resolve()
    directory = layout.project_dir(name)
    if (directory.is_symlink() or not directory.is_dir()
            or directory.resolve().parent != root):
        raise HTTPException(404, "找不到專案")
    return directory


@app.get("/api/search/settings")
def get_search_preferences():
    try:
        return {**search_settings.read_global(), "providers": {
            "web": search_settings.WEB_PROVIDERS, "papers": search_settings.PAPER_PROVIDERS}}
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise HTTPException(500, "搜尋設定無法讀取：" + str(exc)) from exc


@app.put("/api/search/settings/{scope}")
async def set_search_preferences(scope: str, payload: SearchPreferences):
    try:
        saved = search_settings.write_global(scope, payload.model_dump())
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc
    warning = None
    if scope == "chat":
        try:
            from configure_research import sync_chat_preferences
            await asyncio.to_thread(sync_chat_preferences)
        except (httpx.HTTPError, ValueError, KeyError):
            warning = "設定已保存。聊天工具已套用；Open WebUI 內建工具選單尚未同步，請稍後再按儲存。"
    return {"saved": saved, "warning": warning}


@app.get("/api/danus/projects/{name}/search-settings")
def get_project_search(name: str):
    return search_settings.effective("danus", existing_project(name))


@app.put("/api/danus/projects/{name}/search-settings")
def set_project_search(name: str, payload: ProjectSearchPreferences):
    directory = existing_project(name)
    try:
        search_settings.write_project(directory, None if payload.inherit else payload.model_dump())
    except (OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return search_settings.effective("danus", directory)


@app.get("/api/search/web")
def chat_search_proxy(q: str, format: str = "json"):
    """SearXNG-compatible surface, used by Open WebUI's native web tool."""
    from danus.integrations import literature
    with search_settings.scope("chat"):
        result = literature.search_web(q, 5)
    return {**result, "number_of_results": result.get("count", 0),
            "results": [{**r, "content": r.get("abstract", "")} for r in result.get("results", [])],
            "unresponsive_engines": list(result.get("errors", {}).items())}


@app.post("/api/search/test")
async def test_search_sources(payload: SearchPreferences):
    from danus.integrations import literature
    try:
        profile = search_settings.validate(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not profile["enabled"]:
        return {"results": [], "message": "搜尋已關閉，沒有送出測試查詢。"}
    async def probe(engine):
        try:
            rows = await asyncio.to_thread(literature._web_provider, engine, "cryptography", 2)
            return {"id": engine, "ok": True, "count": len(rows)}
        except Exception as exc:
            return {"id": engine, "ok": False, "error": str(exc)[:200]}
    return {"results": await asyncio.gather(*(probe(engine) for engine in profile["web_engines"]))}


@app.get("/api/danus/projects/{name}/literature")
def project_literature(name: str):
    from danus.integrations.literature_log import read_events
    return {"project": name, "events": read_events(existing_project(name))}


@contextmanager
def project_locks(name: str):
    _, layout = danus()
    worker_names = layout.list_workers(name)
    locks = []
    try:
        for worker in worker_names:
            home = layout.worker_dir(name, worker)
            lock_path = home / ".pid.lock"
            if home.is_symlink() or lock_path.is_symlink():
                raise HTTPException(409, "專案包含不安全的工作目錄，無法刪除。")
            lock = lock_path.open("a+")
            locks.append(lock)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise HTTPException(409, "Worker 正在啟動，請稍後重試。") from exc
        yield worker_names
    finally:
        for lock in locks:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()


def trash_root():
    _, layout = danus()
    return layout.agents_root().resolve().parent / "portal-trash"


def existing_trash_entry(item_id: str):
    if not re.fullmatch(r"[0-9a-f]{32}", item_id):
        raise HTTPException(404, "找不到已刪除的專案")
    root = trash_root()
    entry = root / item_id
    source = entry / "project"
    if (root.is_symlink() or entry.is_symlink() or source.is_symlink()
            or not source.is_dir() or entry.resolve().parent != root.resolve()
            or source.resolve().parent != entry.resolve()):
        raise HTTPException(404, "找不到已刪除的專案")
    metadata = read_json_file(entry / "metadata.json")
    if (metadata.get("id") != item_id
            or not isinstance(metadata.get("name"), str)
            or not PROJECT_NAME.fullmatch(metadata["name"])):
        raise HTTPException(404, "回收筒資料不完整，無法處理此專案")
    return entry, metadata


@contextmanager
def trash_operation(item_id: str):
    existing_trash_entry(item_id)
    # Restore and permanent deletion must not operate on the same data at once.
    lock_path = trash_root() / ".operations.lock"
    if lock_path.is_symlink():
        raise HTTPException(409, "回收筒無法使用，請檢查儲存空間。")
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HTTPException(409, "回收筒正在處理另一個操作，請稍後再試。") from exc
        try:
            yield existing_trash_entry(item_id)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@app.delete("/api/danus/admin/projects/{name}")
async def delete_project(name: str):
    """Remove a stopped project from the workspace while keeping it recoverable."""
    directory = existing_project(name)
    _, layout = danus()
    with project_locks(name) as worker_names:
        if any(worker.get("alive") for worker in await authoritative_workers(name)):
            raise HTTPException(409, "專案還在執行，請先按「立即停止」再刪除。")
        if layout.list_workers(name) != worker_names:
            raise HTTPException(409, "專案已變動，請重新整理後再試。")
        item_id = uuid.uuid4().hex
        entry = trash_root() / item_id
        entry.mkdir(parents=True)
        title = read_json_file(directory / "portal.json").get("title") or name
        write_json_file(entry / "metadata.json",
                        {"id": item_id, "name": name, "title": title, "deleted_at": time.time()})
        try:
            directory.rename(entry / "project")
        except OSError as exc:
            (entry / "metadata.json").unlink(missing_ok=True)
            entry.rmdir()
            raise HTTPException(500, "無法移到回收筒，專案資料仍保留。") from exc
    return {"name": name, "title": title, "deleted": True, "recoverable": True, "trash_id": item_id}


@app.get("/api/danus/trash")
async def list_trash():
    root = trash_root()
    if root.is_symlink() or not root.is_dir():
        return []
    items = []
    for entry in root.iterdir():
        if entry.is_symlink() or not re.fullmatch(r"[0-9a-f]{32}", entry.name):
            continue
        try:
            _, metadata = existing_trash_entry(entry.name)
            items.append(metadata)
        except HTTPException:
            continue
    return sorted(items, key=lambda item: item.get("deleted_at", 0), reverse=True)


@app.post("/api/danus/trash/{item_id}/restore")
async def restore_project(item_id: str):
    with trash_operation(item_id) as (entry, metadata):
        _, layout = danus()
        name = metadata["name"]
        destination = layout.project_dir(name)
        if destination.exists() or destination.is_symlink():
            raise HTTPException(409, "同名專案已存在，無法覆蓋。")
        (entry / "project").rename(destination)
        (entry / "metadata.json").unlink()
        entry.rmdir()
    return {"name": name, "restored": True}


def purge_trash_entry(item_id: str):
    with trash_operation(item_id) as (entry, metadata):
        # The validated target is exactly one UUID directory inside portal-trash.
        # rmtree removes nested symlinks without following them outside the entry.
        try:
            shutil.rmtree(entry)
        except OSError as exc:
            raise HTTPException(500, "永久刪除未完成，請重新整理後再試。") from exc
    return {"id": item_id, "name": metadata["name"], "deleted": True, "recoverable": False}


@app.delete("/api/danus/trash/{item_id}")
async def purge_project(item_id: str, payload: PurgeTrash | None = None):
    if not payload or not payload.confirm:
        raise HTTPException(400, "請使用回收筒中的「永久刪除」操作。")
    # Keep the lock in the deletion thread even if the HTTP client disconnects.
    return await asyncio.to_thread(purge_trash_entry, item_id)


@app.patch("/api/danus/projects/{name}")
async def update_project(name: str, payload: ProjectUpdate):
    directory = existing_project(name)
    title = payload.title.strip()
    if not title:
        raise HTTPException(400, "請填寫專案名稱。")
    metadata = read_json_file(directory / "portal.json")
    write_json_file(directory / "portal.json", {**metadata, "title": title})
    return {"name": name, "title": title, "updated": True}


def dashboard_project(name: str) -> Path:
    return existing_project(name)


@app.get("/dashboard/static/style.css")
async def dashboard_style():
    return FileResponse(DANUS_ROOT / "danus" / "observability" / "static" / "style.css",
                        media_type="text/css")


@app.get("/dashboard/static/app.js")
async def dashboard_script():
    source = (DANUS_ROOT / "danus" / "observability" / "static" / "app.js").read_text(
        encoding="utf-8")
    source = source.replace("fetch(path)", "fetch(window.DANUS_DASHBOARD_BASE + path)", 1)
    source = source.replace("symbolSize: 6 + Math.min(16, dp * 2.5)",
                            "symbolSize: (d.nodes.length <= 40 ? 30 : 12) + Math.min(18, dp * 2.5)")
    source = source.replace("label: { show: false }, emphasis:",
                            "label: { show: d.nodes.length <= 40, position: 'bottom', color: '#6d639b' }, emphasis:", 1)
    source = source.replace("graphChart.resize();", """graphChart.resize();
    if (d.nodes.length === 1) showFact(d.nodes[0].id);""", 1)
    source = source.replace("addSec('Statement'", "addSec('命題'")
    source = source.replace("addSec('Proof'", "addSec('證明'")
    source = source.replace("addSec('Intuition'", "addSec('直觀說明'")
    source += "\nwindow.addEventListener('resize', () => { if (graphChart) graphChart.resize(); });\n"
    return Response(source, media_type="application/javascript")


@app.get("/dashboard/{name}/", response_class=HTMLResponse)
async def dashboard_index(name: str, embed: str = ""):
    dashboard_project(name)
    source = (DANUS_ROOT / "danus" / "observability" / "static" / "index.html").read_text(
        encoding="utf-8")
    source = source.replace('href="/static/style.css"', 'href="/dashboard/static/style.css"')
    source = source.replace('<script defer src="/static/app.js"></script>',
        f'<script>window.DANUS_DASHBOARD_BASE = {json.dumps("/dashboard/" + name)};</script>'
        '<script defer src="/dashboard/static/app.js"></script>')
    if embed == "graph":
        source = source.replace("Click a node to inspect its statement, proof, and predecessors.",
                                "點選節點，查看命題、證明與依賴的事實。")
        source = source.replace(">axiom<", ">基礎命題<").replace(">deep result<", ">深層成果<")
        source = source.replace("</head>", """<style>
            .header{display:none!important}.main{padding:16px!important}
            .graph-wrap{height:calc(100vh - 32px)!important;min-height:460px}
            .graph-toolbar{flex-wrap:wrap;gap:10px!important}
            .graph-toolbar .muted:first-child{font-size:0}
            .graph-toolbar .muted:first-child:after{content:"拖曳節點或縮放圖表，點選節點查看證明";font-size:12px}
            @media(max-width:700px){.graph-wrap{grid-template-columns:1fr!important;grid-template-rows:auto 300px minmax(250px,1fr)!important;height:auto!important}.fact-detail{border-left:0!important;border-top:1px solid #e6e9f0;max-height:400px}}
            </style></head>""")
        source = source.replace("</body>", """<script>
            window.addEventListener('DOMContentLoaded',()=>{switchTab('graph');});
            </script></body>""")
    return HTMLResponse(source)


@app.get("/dashboard/{name}/api/overview")
async def dashboard_overview(name: str):
    from danus.observability.app import build_overview
    return build_overview(dashboard_project(name))


@app.get("/dashboard/{name}/api/factgraph")
async def dashboard_factgraph(name: str):
    from danus.observability.app import build_factgraph
    return build_factgraph(dashboard_project(name))


@app.get("/dashboard/{name}/api/channels")
async def dashboard_channels(name: str):
    from danus.observability.app import build_channels
    return build_channels(dashboard_project(name))


@app.get("/dashboard/{name}/api/channel/{kind}")
async def dashboard_channel(name: str, kind: str):
    from danus.observability.app import build_channel
    try:
        return build_channel(kind, dashboard_project(name))
    except KeyError as exc:
        raise HTTPException(404, "找不到記憶頻道") from exc


@app.get("/api/danus/projects/{name}/results")
async def project_results(name: str, limit: int = 50):
    _, layout = danus()
    name = project_name(name)
    directory = layout.project_dir(name)
    if not directory.is_dir():
        raise HTTPException(404, "找不到專案")

    from danus.core import GlobalMemory
    from danus.core.factgraph import statement_of

    facts_dir = directory / "fact_graph" / "facts"
    fact_files = sorted(
        (p for p in facts_dir.glob("*.md") if p.is_file() and not p.is_symlink()
         and re.fullmatch(r"[0-9a-f]{16}", p.stem)),
        key=lambda p: p.stat().st_mtime, reverse=True,
    ) if facts_dir.is_dir() else []
    facts = []
    for path in fact_files[:max(1, min(limit, 5000))]:
        raw = path.read_text(encoding="utf-8")
        facts.append({
            "fact_id": path.stem,
            "statement": statement_of(raw),
            "proof": raw.partition("\n## proof\n")[2].strip(),
        })

    all_traces = GlobalMemory(directory).read("verification")
    traces = list(reversed(all_traces[-20:]))
    return {"name": name, "fact_count": len(fact_files), "facts": facts,
            "verification_count": len(all_traces),
            "verifications": [
                {"timestamp_utc": rec.get("timestamp_utc"),
                 "claim": rec.get("claim"), "verdict": rec.get("verdict"),
                 "fact_id": rec.get("fact_id"), "evidence": rec.get("evidence")}
                for rec in traces]}


@app.post("/api/danus/projects/{name}/start")
async def start_project(name: str):
    existing_project(name)
    cli, _ = danus()
    result = run_danus(cli.do_start, project_name(name))
    if any(worker.get("result") == "locked" for worker in result):
        raise HTTPException(409, "專案正在處理另一個操作，請稍後重試。")
    return result


@app.post("/api/danus/projects/{name}/stop")
async def stop_project(name: str, payload: StopProject | None = None):
    existing_project(name)
    mode = payload.mode if payload else "immediate"
    if mode not in ("immediate", "after_round"):
        raise HTTPException(400, "停止方式不正確。")
    cli, layout = danus()
    with project_locks(name):
        before = run_danus(cli.do_status, name)
        result = await asyncio.to_thread(run_danus, cli.do_stop, name, force=mode == "immediate")
        workers = run_danus(cli.do_status, name)
        if mode == "immediate":
            # do_stop removes .pid; check captured process IDs before reporting success.
            for _ in range(20):
                remaining = [worker for worker in before
                             if worker.get("alive") and cli._alive(worker.get("pid"))]
                if not remaining:
                    break
                await asyncio.sleep(0.05)
            if remaining:
                for worker in remaining:
                    (layout.worker_dir(name, worker["worker"]) / ".pid").write_text(str(worker["pid"]))
                raise HTTPException(409, "程序尚未結束，請稍後再按「立即停止」。")
            for worker in workers:
                home = layout.worker_dir(name, worker["worker"])
                details = read_json_file(home / ".status.json")
                write_json_file(home / ".status.json",
                                {**details, "state": "stopped", "stop_reason": "user",
                                 "updated_at": time.time()})
                (home / ".stop").unlink(missing_ok=True)
            workers = run_danus(cli.do_status, name)
    return {"name": name, "mode": mode, "result": result, "workers": workers,
            "status": "stopping" if any(worker.get("alive") for worker in workers) else "stopped"}


@app.get("/api/danus/projects/{name}/export")
async def export_project(name: str):
    info = await project(name)
    results = await project_results(name, limit=5000)
    sections = [f"# {info['title']}", "## 問題", info["problem"],
                f"## 通過 Danus 驗證的成果（{results['fact_count']}）",
                "驗證由模型執行；以下內容仍可供人工核對。"]
    for fact in results["facts"]:
        sections.extend([f"### {fact['statement']}", f"事實 ID：{fact['fact_id']}", fact["proof"]])
    if not results["facts"]:
        sections.append("目前尚無通過驗證的成果。")
    return Response("\n\n".join(sections), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.md"'})


@app.post("/api/danus/projects/{name}/assign")
async def assign_project(name: str, payload: Assignment):
    cli, layout = danus()
    name = project_name(name)
    workers = layout.list_workers(name)
    if len(workers) != 1 or not payload.task.strip():
        raise HTTPException(400, "請提供單一 worker 的任務。")
    return run_danus(cli.do_assign, f"{name}/{workers[0]}", payload.task.strip())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=7860)
