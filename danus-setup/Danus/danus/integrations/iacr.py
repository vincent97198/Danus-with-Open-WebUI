"""Search IACR's official CC0 OAI-PMH metadata in a local SQLite FTS index.

Uses the machine interface advertised at https://eprint.iacr.org/rss/.
Never scrapes /search or downloads PDFs. Refresh is on demand, at most daily
after a successful harvest; failed paginated harvests can resume after backoff.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

NS = {"o": "http://www.openarchives.org/OAI/2.0/", "dc": "http://purl.org/dc/elements/1.1/"}
PAPER_ID = re.compile(r"(?:19|20)\d{2}/\d{1,6}")
DAY = 86400


def _database():
    from .literature import _cache_root
    return _cache_root() / "iacr-metadata.sqlite3"


@contextmanager
def _connect():
    connection = sqlite3.connect(_database(), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS papers (
            id TEXT PRIMARY KEY, title TEXT, authors TEXT, abstract TEXT,
            categories TEXT, published TEXT, updated TEXT, rights TEXT);
        CREATE VIRTUAL TABLE IF NOT EXISTS paper_fts USING fts5(title, authors, abstract, categories);
    """)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _state(db):
    return dict(db.execute("SELECT key,value FROM state").fetchall())


def _save_state(db, **values):
    db.executemany("INSERT INTO state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   [(k, str(v)) for k, v in values.items()])


def _parse_page(raw: bytes):
    root = ET.fromstring(raw)
    if root.tag != "{" + NS["o"] + "}OAI-PMH":
        raise ValueError("IACR did not return an OAI-PMH document")
    error = root.find("o:error", NS)
    if error is not None:
        if error.get("code") == "noRecordsMatch":
            return [], ""
        raise ValueError(f"IACR OAI {error.get('code')}: {error.text}")
    rows = []
    if root.find("o:ListRecords", NS) is None:
        raise ValueError("IACR response has no ListRecords data")
    for record in root.findall(".//o:record", NS):
        header = record.find("o:header", NS)
        identifier = header.findtext("o:identifier", "", NS).removeprefix("oai:eprint.iacr.org:")
        if not PAPER_ID.fullmatch(identifier):
            continue
        if header.get("status") == "deleted":
            rows.append({"id": identifier, "deleted": True})
            continue
        def values(key):
            return [" ".join("".join(node.itertext()).split()) for node in record.findall(".//dc:" + key, NS)]
        dates = values("date")
        rows.append({"id": identifier, "title": " ".join(values("title")),
                     "authors": json.dumps(values("creator"), ensure_ascii=False),
                     "abstract": "\n".join(values("description")),
                     "categories": " ".join(values("subject")),
                     "published": dates[0] if dates else identifier[:4],
                     "updated": header.findtext("o:datestamp", "", NS),
                     "rights": json.dumps(values("rights"))})
    return rows, (root.findtext(".//o:resumptionToken", "", NS) or "").strip()


def _apply_page(db, rows):
    for row in rows:
        old = db.execute("SELECT rowid FROM papers WHERE id=?", (row["id"],)).fetchone()
        if old:
            db.execute("DELETE FROM paper_fts WHERE rowid=?", (old[0],))
        if row.get("deleted"):
            db.execute("DELETE FROM papers WHERE id=?", (row["id"],))
            continue
        db.execute("""INSERT INTO papers VALUES (:id,:title,:authors,:abstract,:categories,:published,:updated,:rights)
            ON CONFLICT(id) DO UPDATE SET title=excluded.title,authors=excluded.authors,
            abstract=excluded.abstract,categories=excluded.categories,published=excluded.published,
            updated=excluded.updated,rights=excluded.rights""", row)
        db.execute("INSERT INTO paper_fts(rowid,title,authors,abstract,categories) SELECT rowid,title,authors,abstract,categories FROM papers WHERE id=?", (row["id"],))


def refresh():
    from .literature import _download, _cache_root
    with (_cache_root() / "iacr-sync.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "updating"}
        with _connect() as db:
            state = _state(db)
            now = time.time()
            last = float(state.get("last_success", "0"))
            if now - last < DAY:
                return {"status": "current", "updated_at": last}
            if now - float(state.get("last_attempt", "0")) < 300:
                return {"status": "backoff", "error": state.get("error", "A refresh was recently attempted")}
            _save_state(db, last_attempt=now)
            db.commit()
            token = state.get("token", "")
            since = state.get("since", "") if token else (
                (datetime.fromtimestamp(last, timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ") if last else "")
            try:
                for _ in range(200):
                    params = {"verb": "ListRecords"}
                    if token:
                        params["resumptionToken"] = token
                    else:
                        params["metadataPrefix"] = "oai_dc"
                        if since:
                            params["from"] = since
                    rows, token = _parse_page(_download("https://eprint.iacr.org/oai?" + urllib.parse.urlencode(params), 12_000_000))
                    _apply_page(db, rows)
                    _save_state(db, token=token, since=since, error="")
                    db.commit()
                    if not token:
                        _save_state(db, last_success=now, token="", since="", error="")
                        db.commit()
                        return {"status": "ready", "count": db.execute("SELECT count(*) FROM papers").fetchone()[0]}
                    if time.time() - now > 300:
                        raise TimeoutError("Harvest paused after five minutes; the next attempt resumes from its saved cursor")
                    time.sleep(1)
                raise ValueError("Harvest page limit reached; cursor retained")
            except Exception as exc:
                error = str(exc)[:500]
                if "badResumptionToken" in error:
                    _save_state(db, token="", since="")
                retry = getattr(getattr(exc, "response", None), "headers", {}).get("Retry-After", "300")
                try:
                    next_attempt = time.time() + max(300, int(retry))
                except ValueError:
                    next_attempt = time.time() + 3600
                _save_state(db, error=error, last_attempt=next_attempt - 300)
                db.commit()
                return {"status": "error", "error": error}


def _refresh_if_due(state):
    now = time.time()
    if now - float(state.get("last_success", "0")) >= DAY and now - float(state.get("last_attempt", "0")) >= 300:
        subprocess.Popen([sys.executable, "-m", "danus.integrations.iacr"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)


def _record(row, state):
    return {"title": row["title"], "authors": json.loads(row["authors"]),
            "year": row["published"][:4], "published": row["published"],
            "abstract": row["abstract"], "eprint_id": row["id"],
            "url": "https://eprint.iacr.org/" + row["id"],
            "pdf_url": "https://eprint.iacr.org/" + row["id"] + ".pdf",
            "source": "IACR ePrint", "content_level": "abstract",
            "license_urls": json.loads(row["rights"]),
            "index_updated_at": float(state.get("last_success", "0")),
            "full_text_note": "This is official metadata and abstract, not the PDF. Open the source link to obtain the paper under its license; upload a local PDF to chat to read it."}


def search(query: str, count: int = 5, sort: str = "relevance") -> list[dict]:
    parsed = urllib.parse.urlsplit(query)
    if parsed.hostname == "eprint.iacr.org":
        identifier = parsed.path.strip("/").removesuffix(".pdf")
        if PAPER_ID.fullmatch(identifier):
            query = identifier
    with _connect() as db:
        state = _state(db)
        _refresh_if_due(state)
        if not state.get("last_success"):
            raise RuntimeError("IACR metadata index is being prepared; retry shortly. " + state.get("error", ""))
        if PAPER_ID.fullmatch(query):
            rows = db.execute("SELECT * FROM papers WHERE id=?", (query,)).fetchall()
        else:
            terms = re.findall(r'"([^"\n]+)"|([\w-]+)', query, flags=re.UNICODE)
            expression = " AND ".join('"' + (phrase or word).replace('"', '""') + '"' for phrase, word in terms[:30])
            if not expression:
                return []
            order = "p.published DESC, p.id DESC" if sort == "newest" else "bm25(paper_fts, 5.0, 2.0, 1.0, 1.0), p.published DESC"
            rows = db.execute("SELECT p.* FROM paper_fts JOIN papers p ON p.rowid=paper_fts.rowid WHERE paper_fts MATCH ? ORDER BY " + order + " LIMIT ?", (expression, max(1, min(10, count)))).fetchall()
        return [_record(row, state) for row in rows]


if __name__ == "__main__":
    print(json.dumps(refresh(), ensure_ascii=False), flush=True)
