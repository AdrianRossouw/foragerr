"""Shared partial-update helper for the provider repos (FRG-IDX-002 / FRG-DL-002).

``indexers.repo.update_indexer`` and ``downloads.repo.update_download_client``
were near-identical partial-PUT appliers: a sentinel distinguishing "field
omitted (keep the stored value)" from an explicit ``None``, a run of
``if x is not _UNSET: row.x = x`` lines, and the special ``settings`` field
(register its secrets, then serialize it onto ``row.settings`` — write-only
secret survival, FRG-API-009). Both now share this one implementation rather
than forking it.
"""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel

#: "field omitted — keep the stored value" vs. an explicit ``None`` on a partial
#: PUT. One shared sentinel for both provider repos; callers pass only the keys
#: they actually carry (via ``**updates``), so the single identity is safe.
UNSET: object = object()


def apply_partial_update(
    row: Any, fields: Mapping[str, Any], *, settings: Any = UNSET
) -> None:
    """Apply a partial update onto ``row`` in place.

    ``fields`` maps scalar column names to their new value or :data:`UNSET`
    (left untouched). When ``settings`` is supplied it must be an
    already-validated settings model: its secrets are re-registered for
    redaction and it is serialized onto ``row.settings`` (the caller is
    responsible for merging any omitted write-only secret onto the stored value
    before validating, so it survives an edit that does not resupply it —
    FRG-API-009).
    """
    for name, value in fields.items():
        if value is not UNSET:
            setattr(row, name, value)
    if settings is not UNSET:
        # Deferred import breaks the providers -> indexers.repo cycle (the repo
        # imports this module at load time). These two helpers are the canonical
        # settings (de)serializers both repos already reuse.
        from foragerr.indexers.repo import register_row_secrets, serialize_settings

        assert isinstance(settings, BaseModel)
        register_row_secrets(settings)
        row.settings = serialize_settings(settings)


__all__ = ["UNSET", "apply_partial_update"]
