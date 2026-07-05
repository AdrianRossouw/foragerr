"""Indexer settings contract + dynamic schema (FRG-IDX-001, FRG-IDX-003,
FRG-API-009)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from foragerr import logging as flog
from foragerr.indexers.registry import (
    UnknownImplementationError,
    implementations,
    validate_settings,
)
from foragerr.indexers.repo import (
    load_settings,
    public_settings,
    serialize_settings,
)
from foragerr.indexers.schema import schema_for
from foragerr.indexers.settings import NewznabSettings


@pytest.mark.req("FRG-API-009")
def test_schema_fields_carry_the_full_field_contract_union():
    specs = schema_for(NewznabSettings)
    by_name = {s.name: s for s in specs}
    # Every field carries the full union of keys.
    for spec in specs:
        d = spec.as_dict()
        assert set(d) == {
            "order", "name", "type", "label", "help", "required",
            "secret", "advanced", "selectOptions",
        }
    # Stable declared order.
    assert [s.order for s in specs] == list(range(len(specs)))
    # Typed fields: url textbox, secret password, categories select w/ options.
    assert by_name["base_url"].type == "textbox"
    assert by_name["base_url"].required
    assert by_name["api_key"].type == "password"
    assert by_name["api_key"].secret
    assert by_name["categories"].type == "select"
    assert by_name["categories"].selectOptions  # enumerated options inline
    assert by_name["additional_parameters"].advanced


@pytest.mark.req("FRG-API-009")
def test_secret_field_flagged_but_never_carries_a_value():
    # A schema template has no values — secrets are write-only by construction.
    for spec in schema_for(NewznabSettings):
        assert "value" not in spec.as_dict()
    api_key = next(s for s in schema_for(NewznabSettings) if s.name == "api_key")
    assert api_key.secret is True


@pytest.mark.req("FRG-IDX-001")
def test_invalid_settings_payload_rejected_with_field_errors():
    with pytest.raises(ValidationError) as excinfo:
        validate_settings("newznab", {"api_key": "k"})  # missing base_url
    locs = {e["loc"][0] for e in excinfo.value.errors()}
    assert "base_url" in locs


@pytest.mark.req("FRG-IDX-001")
def test_malformed_base_url_rejected():
    with pytest.raises(ValidationError):
        validate_settings("newznab", {"base_url": "ftp://x", "api_key": "k"})


@pytest.mark.req("FRG-IDX-001")
def test_valid_settings_accepted_and_default_category_is_7030():
    model = validate_settings("newznab", {"base_url": "https://idx.test", "api_key": "k"})
    assert isinstance(model, NewznabSettings)
    assert model.categories == [7030]


@pytest.mark.req("FRG-IDX-001")
def test_api_key_is_secret_write_only_and_registered_for_redaction():
    flog.clear_secrets()
    model = validate_settings(
        "newznab", {"base_url": "https://idx.test", "api_key": "super-secret-key"}
    )
    # Serialized (server-side storage) reveals the value so the row can auth...
    assert "super-secret-key" in serialize_settings(model)
    # ...but the public view (a GET response) drops it entirely (write-only).
    assert "api_key" not in public_settings(model)
    # Loading a row re-registers the secret for log redaction.
    load_settings("newznab", serialize_settings(model))
    assert flog.redact("key=super-secret-key here") != "key=super-secret-key here"
    flog.clear_secrets()


@pytest.mark.req("FRG-IDX-003")
def test_registry_lists_newznab_and_rejects_unknown():
    names = {impl.name for impl in implementations()}
    assert "newznab" in names
    with pytest.raises(UnknownImplementationError):
        validate_settings("torznab", {})
