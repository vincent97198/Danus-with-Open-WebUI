"""Bounded, public retrieval history; contains sources, never agent scratchpads."""
import fcntl
import json
import time
from pathlib import Path


def record_event(project: Path, tool: str, query: str, result: dict, author: str):
    folder = project / "literature"
    if folder.is_symlink():
        return
    folder.mkdir(exist_ok=True)
    path = folder / "events.jsonl"
    lock_path = folder / ".lock"
    if path.is_symlink() or lock_path.is_symlink():
        return
    rows = []
    for row in result.get("results", [])[:30]:
        rows.append({k: row[k] for k in ("title", "authors", "year", "url", "doi", "arxiv_id", "eprint_id", "source", "content_level", "index_updated_at") if k in row})
        rows[-1]["abstract"] = str(row.get("abstract", row.get("theorem", "")))[:2000]
        if row.get("arxiv_id") and not rows[-1].get("url"):
            rows[-1]["url"] = "https://arxiv.org/abs/" + row["arxiv_id"]
            rows[-1]["source"] = "Matlas"
    event = {"at": time.time(), "tool": tool, "query": query[:1200], "author": author,
             "results": rows, "count": result.get("count", len(rows))}
    for key in ("error", "errors", "arxiv_id", "url", "source_format", "content_level", "offset", "next_offset", "total_chars"):
        if key in result:
            event[key] = result[key]
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists() and path.stat().st_size > 4_000_000:
            with path.open("rb") as stream:
                stream.seek(-2_000_000, 2)
                stream.readline()
                tail = stream.read()
            path.write_bytes(tail)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_events(project: Path, limit: int = 100) -> list[dict]:
    folder = project / "literature"
    path = folder / "events.jsonl"
    if folder.is_symlink() or path.is_symlink() or not path.is_file():
        return []
    with path.open("rb") as stream:
        if path.stat().st_size > 2_000_000:
            stream.seek(-2_000_000, 2)
            stream.readline()
        lines = stream.read(2_100_000).splitlines()[-limit:]
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except ValueError:
            continue
    return rows[::-1]
