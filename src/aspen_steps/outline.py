"""The Outline API calls the steps make. Agents never get this key."""

import json
import mimetypes
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from pydantic import SecretStr

# Cloudflare's browser integrity check rejects Python-urllib's default agent
# (error 1010), so name ourselves.
USER_AGENT = "aspen-net-workflows (+https://github.com/quantum-aspen/aspen-net-workflows)"


class OutlineError(RuntimeError):
    pass


class Outline:
    def __init__(self, base_url: str, api_key: SecretStr):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _send(self, req: urllib.request.Request, what: str) -> dict:
        req.add_header("Authorization", f"Bearer {self.api_key.get_secret_value()}")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            raise OutlineError(f"{what}: HTTP {e.code} {e.read()[:300]!r}") from e
        except (OSError, ValueError) as e:  # network down, timeout, or a garbled reply
            raise OutlineError(f"{what}: {type(e).__name__}: {e}") from e

    def _post(self, method: str, body: dict):
        req = urllib.request.Request(
            f"{self.base_url}/api/{method}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            return self._send(req, method)["data"]
        except KeyError as e:
            raise OutlineError(f"{method}: reply has no data") from e

    def document(self, doc_id: str) -> dict:
        """Accepts a document UUID or the url id at the end of a doc link."""
        return self._post("documents.info", {"id": doc_id})

    def update(self, doc_id: str, *, text: str | None = None, title: str | None = None) -> dict:
        body = {"id": doc_id}
        if text is not None:
            body["text"] = text
        if title is not None:
            body["title"] = title
        return self._post("documents.update", body)

    def recently_updated(self, collection_id: str, limit: int = 100) -> list[dict]:
        """A page that was just flagged was just edited, so the newest edits are enough."""
        return self._post(
            "documents.list",
            {"collectionId": collection_id, "sort": "updatedAt", "direction": "DESC", "limit": limit},
        )

    def children(self, collection_id: str, parent_id: str) -> list[dict]:
        return self._post(
            "documents.list",
            {"collectionId": collection_id, "parentDocumentId": parent_id, "limit": 100},
        )

    def tree(self, collection_id: str) -> list[dict]:
        """The collection's navigation tree: [{id, title, url, children}]."""
        return self._post("collections.documents", {"id": collection_id})

    def templates(self, collection_id: str) -> list[dict]:
        return self._post("templates.list", {"collectionId": collection_id})

    def users(self) -> list[dict]:
        """Every active user: the team roster."""
        out, offset = [], 0
        while page := self._post("users.list", {"limit": 100, "offset": offset}):
            out += page
            offset += len(page)
            if len(page) < 100:
                break
        return out

    def upload(self, doc_id: str, path: Path) -> str:
        """Attaches a file to a document and returns its URL. Two steps:
        attachments.create says where to send the file, then a multipart POST sends it."""
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        a = self._post(
            "attachments.create",
            {"name": path.name, "contentType": ctype, "size": len(data), "documentId": doc_id},
        )
        boundary = uuid.uuid4().hex
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
            for k, v in (a.get("form") or {}).items()
        ]
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n".encode()
            + data
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode())
        url = a["uploadUrl"]
        if url.startswith("/"):  # local file storage answers on the wiki itself
            url = self.base_url + url
        req = urllib.request.Request(
            url, data=b"".join(parts), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )
        self._send(req, "attachment upload")
        return a["attachment"]["url"]
