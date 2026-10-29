"""Backend selection.

The single place that knows which concrete backend is active. Everything else
depends on the ABCs in `data.interfaces`. A `DataLayer` bundles the three stores
so callers get a consistent, already-wired set (the vector index and audit store
must share the same underlying connection in sqlite_local).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.settings import Settings, StorageBackend, get_settings
from data.backends.local_blob import LocalBlobStore
from data.interfaces import AuditStore, BlobStore, ConfigStore, VectorIndex


@dataclass
class DataLayer:
    store: AuditStore
    vectors: VectorIndex
    blobs: BlobStore
    config: ConfigStore

    def migrate(self) -> None:
        self.store.migrate()
        self.config.migrate()

    def health(self) -> bool:
        return self.store.health() and self.config.health()

    def close(self) -> None:
        self.store.close()
        self.config.close()


def build_data_layer(settings: Settings | None = None) -> DataLayer:
    settings = settings or get_settings()
    blobs = LocalBlobStore(settings.blob_dir)

    if settings.storage_backend is StorageBackend.sqlite_local:
        from data.backends.sqlite_store import LocalVectorIndex, SqliteAuditStore, SqliteConfigStore

        store = SqliteAuditStore(settings.sqlite_file)
        vectors = LocalVectorIndex(store, settings.embedding_dim)
        config = SqliteConfigStore(store)
        return DataLayer(store=store, vectors=vectors, blobs=blobs, config=config)

    if settings.storage_backend is StorageBackend.postgres:
        from data.backends.postgres_store import PgVectorIndex, PostgresAuditStore, PostgresConfigStore

        store = PostgresAuditStore(settings.postgres_dsn)
        vectors = PgVectorIndex(store, settings.embedding_dim)
        config = PostgresConfigStore(store)
        return DataLayer(store=store, vectors=vectors, blobs=blobs, config=config)

    raise ValueError(f"unknown storage backend: {settings.storage_backend!r}")


def build_config_store(settings: Settings | None = None) -> ConfigStore:
    """Standalone ConfigStore accessor for callers that only need user/OE-
    override persistence, not a full DataLayer (Streamlit's app_pages via
    common/auth.py and config_admin.py's compat shims) - same underlying db
    file/dsn as build_data_layer(), just without constructing the blob store/
    vector index this caller doesn't need."""
    settings = settings or get_settings()

    if settings.storage_backend is StorageBackend.sqlite_local:
        from data.backends.sqlite_store import SqliteAuditStore, SqliteConfigStore

        store = SqliteAuditStore(settings.sqlite_file)
        return SqliteConfigStore(store)

    if settings.storage_backend is StorageBackend.postgres:
        from data.backends.postgres_store import PostgresAuditStore, PostgresConfigStore

        store = PostgresAuditStore(settings.postgres_dsn)
        return PostgresConfigStore(store)

    raise ValueError(f"unknown storage backend: {settings.storage_backend!r}")


@lru_cache
def get_default_config_store() -> ConfigStore:
    """Process-wide lazy singleton wrapping build_config_store() - used by
    common/auth.py::authenticate() and config_admin.py's user/pipeline/
    generator/thresholds compat shims (Streamlit runs in its own process, so
    this never contends with the REST API's own DataLayer.config). Migrated
    on first access so a bare `streamlit run` with no prior REST API startup
    still bootstraps app_users from config/users.yaml."""
    store = build_config_store()
    store.migrate()
    return store


def purge_all_transactional_data(data: DataLayer, settings: Settings) -> dict:
    """Delete every submission and everything derived from it - database rows,
    receipt/blob files, and the LangGraph durable-checkpoint file - but leave
    config (config/*.yaml, .env) untouched. Mirrors the SOA Layout Agent app's
    "Delete Operational Data" reset. Irreversible; the caller (System admin ->
    Danger zone) must gate this behind an explicit user confirmation."""
    table_counts = data.store.purge_all()
    blob_count = data.blobs.purge_all()

    # Best-effort: the checkpoint db is a separate sqlite file that may still
    # be held open by a cached pipeline/checkpointer resource in this same
    # process (Windows locks an open file against deletion). Callers should
    # drop cached resources (app_common.reload()) and let Python's refcounting
    # close the connection BEFORE calling this - but never let a lock here
    # abort an otherwise-successful data/blob purge.
    checkpoint_file = Path(settings.checkpoint_file)
    checkpoint_cleared = False
    checkpoint_error: str | None = None
    if checkpoint_file.exists():
        try:
            checkpoint_file.unlink()
            for suffix in ("-wal", "-shm"):
                sidecar = checkpoint_file.with_name(checkpoint_file.name + suffix)
                if sidecar.exists():
                    sidecar.unlink()
            checkpoint_cleared = True
        except OSError as exc:
            checkpoint_error = str(exc)

    return {
        "table_counts": table_counts,
        "rows_deleted": sum(table_counts.values()),
        "blobs_deleted": blob_count,
        "checkpoint_cleared": checkpoint_cleared,
        "checkpoint_error": checkpoint_error,
    }
