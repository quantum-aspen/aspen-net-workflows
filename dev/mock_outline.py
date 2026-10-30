"""A stand-in for the Outline API: just the calls the steps make, kept in a JSON file.

Usage: python dev/mock_outline.py <state.json> [port]   (token: MOCK_OUTLINE_TOKEN, default "dev")

Replies have Outline's shape ({"data": …}), documents carry markdown `text`, and
attachments go through attachments.create + a multipart POST to /api/files.create,
as with Outline's local file storage. seed.py fills a fresh state file.
"""

import json
import os
import re
import secrets
import sys
import threading
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOCK = threading.Lock()


class State:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {}
        for k in ("collections", "documents", "templates", "users", "attachments"):
            self.data.setdefault(k, [])

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=1))

    def doc(self, ref: str) -> dict:
        for d in self.data["documents"]:
            if ref in (d["id"], d["urlId"]) or d["url"].endswith(ref):
                return d
        raise KeyError(ref)


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "untitled"


def now() -> str:
    return datetime.now(UTC).isoformat()


def new_doc(st: State, title: str, text: str, collection: str, parent: str | None = None) -> dict:
    url_id = secrets.token_urlsafe(8)[:10]
    d = {
        "id": str(uuid.uuid4()),
        "urlId": url_id,
        "title": title,
        "text": text,
        "collectionId": collection,
        "parentDocumentId": parent,
        "createdAt": now(),
        "updatedAt": now(),
        "url": f"/doc/{slug(title)}-{url_id}",
    }
    st.data["documents"].append(d)
    return d


def api(st: State, method: str, body: dict):
    docs = st.data["documents"]
    if method == "documents.info":
        return st.doc(body["id"])
    if method == "documents.update":
        d = st.doc(body["id"])
        if "title" in body:
            d["title"] = body["title"]
            d["url"] = f"/doc/{slug(body['title'])}-{d['urlId']}"
        if "text" in body:
            d["text"] = body["text"]
        d["updatedAt"] = now()
        return d
    if method == "documents.create":
        return new_doc(
            st,
            body.get("title", ""),
            body.get("text", ""),
            body["collectionId"],
            body.get("parentDocumentId"),
        )
    if method == "documents.list":
        out = [d for d in docs if d["collectionId"] == body.get("collectionId", d["collectionId"])]
        if "parentDocumentId" in body:
            out = [d for d in out if d["parentDocumentId"] == body["parentDocumentId"]]
        if body.get("sort") == "updatedAt":
            out.sort(key=lambda d: d["updatedAt"], reverse=body.get("direction", "DESC") == "DESC")
        off = body.get("offset", 0)
        return out[off : off + body.get("limit", 25)]
    if method == "collections.documents":

        def node(d):
            kids = [node(c) for c in docs if c["parentDocumentId"] == d["id"]]
            return {"id": d["id"], "title": d["title"], "url": d["url"], "children": kids}

        return [node(d) for d in docs if d["collectionId"] == body["id"] and not d["parentDocumentId"]]
    if method == "templates.list":
        return [
            t
            for t in st.data["templates"]
            if t["collectionId"] == body.get("collectionId", t["collectionId"])
        ]
    if method == "users.list":
        off = body.get("offset", 0)
        return st.data["users"][off : off + body.get("limit", 25)]
    if method == "attachments.create":
        a = {
            "id": str(uuid.uuid4()),
            "name": body["name"],
            "documentId": body.get("documentId"),
            "size": body["size"],
        }
        a["key"] = f"uploads/{a['id']}/{body['name']}"
        st.data["attachments"].append(a)
        return {
            "uploadUrl": "/api/files.create",
            "form": {"key": a["key"]},
            "attachment": {"id": a["id"], "url": f"/api/attachments.redirect?id={a['id']}"},
        }
    raise LookupError(method)


class Handler(BaseHTTPRequestHandler):
    st: State
    token: str
    files: Path

    def _reply(self, code: int, obj: dict):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        if self.headers.get("Authorization") != f"Bearer {self.token}":
            return self._reply(401, {"ok": False, "error": "authentication_required"})
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        method = self.path.removeprefix("/api/")
        if method == "files.create":
            key = re.search(rb'name="key"\r\n\r\n([^\r]+)', raw)
            file = re.search(
                rb'name="file"; filename="[^"]*"\r\nContent-Type: [^\r]+\r\n\r\n(.*)\r\n--', raw, re.S
            )
            if not key or not file:
                return self._reply(400, {"ok": False, "error": "bad multipart"})
            out = self.files / key.group(1).decode()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(file.group(1))
            return self._reply(200, {"ok": True})
        try:
            with LOCK:
                data = api(self.st, method, json.loads(raw or b"{}"))
                self.st.save()
        except KeyError as e:
            return self._reply(404, {"ok": False, "error": f"not_found: {e}"})
        except LookupError:
            return self._reply(404, {"ok": False, "error": f"no such method {method}"})
        return self._reply(200, {"ok": True, "data": data})

    def log_message(self, fmt, *args):
        sys.stderr.write(f"mock-outline {self.command} {self.path} {args[1] if len(args) > 1 else ''}\n")


def main():
    path = Path(sys.argv[1])
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 3999
    Handler.st = State(path)
    Handler.token = os.environ.get("MOCK_OUTLINE_TOKEN", "dev")
    Handler.files = path.parent / "files"
    print(f"mock outline on http://127.0.0.1:{port} ({path})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
