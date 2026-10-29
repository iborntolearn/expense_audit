"""Service layer sitting between routes/config_admin and ConfigStore
persistence. Owns business rules (e.g. the last-global-admin guard) that
don't belong in the persistence layer - ConfigStore only knows how to
store/retrieve rows."""
