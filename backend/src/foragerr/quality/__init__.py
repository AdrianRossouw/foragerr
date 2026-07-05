"""Format profiles: named, ordered comic-container format ladders (FRG-QUAL-001).

Public surface:

- :class:`FormatProfileRow` — the ORM model.
- :data:`DEFAULT_PROFILE_NAME` — the reserved name of the seeded default
  profile (FRG-QUAL-002); downstream add-flow code looks it up by this name
  rather than a stored "is default" flag (see module docstring on
  :mod:`foragerr.quality.models` for the rationale).
- :func:`seed_default_format_profile` — idempotent seed, called from the
  Alembic migration (and safe to call again from anywhere else).
"""

from __future__ import annotations

from foragerr.quality.models import (
    DEFAULT_CUTOFF,
    DEFAULT_FORMATS,
    DEFAULT_PROFILE_NAME,
    FormatProfileRow,
    decode_formats,
    encode_formats,
    seed_default_format_profile,
)

__all__ = [
    "DEFAULT_CUTOFF",
    "DEFAULT_FORMATS",
    "DEFAULT_PROFILE_NAME",
    "FormatProfileRow",
    "decode_formats",
    "encode_formats",
    "seed_default_format_profile",
]
