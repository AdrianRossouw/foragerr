"""Migration 0016's role vocabulary is a FROZEN copy, not the live constant
(FRG-CRTR-002).

Historical migrations must be immutable: 0016 inlines its own
``_FROZEN_ROLE_VOCABULARY`` for the ``issue_credits`` CHECK rather than importing
``foragerr.metadata.credits.ROLE_VOCABULARY``, so a future vocabulary change can
never retroactively alter the schema an already-applied 0016 produced. This test
is the tripwire: it asserts the frozen tuple still equals the CURRENT live
vocabulary and fails the day they diverge — telling the developer to ship a NEW
migration that ALTERs the constraint, not to edit 0016 (which would make fresh
and upgraded installs disagree).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import foragerr.db.alembic as alembic_pkg
from foragerr.metadata.credits import ROLE_VOCABULARY


def _load_migration_0016():
    # ``foragerr.db.alembic`` is a namespace package (``__file__`` is None), so
    # resolve the versions dir via its package search path instead.
    path = Path(list(alembic_pkg.__path__)[0]) / "versions" / "0016_creators_credits.py"
    spec = importlib.util.spec_from_file_location("_migration_0016_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.req("FRG-CRTR-002")
def test_migration_0016_frozen_vocabulary_matches_live_today():
    module = _load_migration_0016()
    assert module._FROZEN_ROLE_VOCABULARY == ROLE_VOCABULARY, (
        "0016's frozen role vocabulary diverged from the live "
        "ROLE_VOCABULARY. Historical migrations are immutable: do NOT edit "
        "0016's _FROZEN_ROLE_VOCABULARY. Ship a NEW migration that ALTERs the "
        "issue_credits CHECK constraint to the new vocabulary instead."
    )
