"""Filesystem-backed BlobStore for simulation mode.

Receipts are synthetic (Build Brief 2.2 forbids real receipts), so storing them
on the local filesystem is sufficient. The `blob://` URL scheme keeps the rest
of the code storage-agnostic: a future Azure Blob implementation returns
`https://…` URLs behind the same interface and nothing downstream changes.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from data.interfaces import BlobStore

_SCHEME = "blob"


class LocalBlobStore(BlobStore):
    def __init__(self, root: Path):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        # Prevent path traversal; keys are treated as relative POSIX-style paths.
        safe = Path(key.replace("\\", "/"))
        if safe.is_absolute() or ".." in safe.parts:
            raise ValueError(f"unsafe blob key: {key!r}")
        return self._root / safe

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"{_SCHEME}://{key}"

    def _resolve_url(self, url: str) -> Path:
        parsed = urlparse(url)
        if parsed.scheme != _SCHEME:
            raise ValueError(f"not a {_SCHEME}:// url: {url!r}")
        key = (parsed.netloc + parsed.path).lstrip("/")
        return self._path_for(key)

    def get(self, url: str) -> bytes:
        return self._resolve_url(url).read_bytes()

    def exists(self, url: str) -> bool:
        try:
            return self._resolve_url(url).exists()
        except ValueError:
            return False

    def purge_all(self) -> int:
        files = [p for p in self._root.rglob("*") if p.is_file()]
        count = len(files)
        for p in files:
            p.unlink(missing_ok=True)
        # Remove now-empty subdirectories (deepest first) but keep the root.
        for d in sorted((p for p in self._root.rglob("*") if p.is_dir()),
                        key=lambda p: len(p.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
        return count
