"""Configuration: state location, sources/precedence, first-run generation,
fail-fast validation (FRG-DEP-002, FRG-DEP-003, FRG-DEP-006, FRG-NFR-008,
FRG-NFR-009)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
import yaml
from pydantic import SecretStr

from foragerr.config import (
    CONFIG_FILENAME,
    ConfigError,
    Settings,
    load_settings,
)
from foragerr.logging import MASK, setup_logging

# --------------------------------------------------------------------------
# FRG-DEP-002 — all persistent state under the configured config dir
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-DEP-002")
def test_all_state_created_under_config_dir(config_dir):
    default_existed_before = Path("/config").exists()
    settings = load_settings()
    setup_logging(settings.config_dir, level=settings.log_level)
    logging.getLogger("foragerr.test").info("initialized")

    assert settings.config_dir == config_dir
    assert (config_dir / CONFIG_FILENAME).is_file()
    assert (config_dir / "logs" / "foragerr.log").is_file()
    # nothing appears outside the configured dir
    assert Path("/config").exists() == default_existed_before
    top_level = {p.name for p in config_dir.iterdir()}
    assert top_level == {CONFIG_FILENAME, "logs"}


@pytest.mark.req("FRG-DEP-002")
def test_alternate_config_dir_receives_all_state(tmp_path, monkeypatch):
    alternate = tmp_path / "alternate-home"
    decoy_default = tmp_path / "would-be-default"
    monkeypatch.setenv("FORAGERR_CONFIG_DIR", str(alternate))

    settings = load_settings()
    setup_logging(settings.config_dir, level=settings.log_level)
    logging.getLogger("foragerr.test").info("hello")

    assert (alternate / CONFIG_FILENAME).is_file()
    assert (alternate / "logs" / "foragerr.log").is_file()
    assert not decoy_default.exists()


@pytest.mark.req("FRG-DEP-002")
def test_state_survives_replacing_the_instance(config_dir):
    first = load_settings()
    assert first.port == 8789
    generated = (config_dir / CONFIG_FILENAME).read_text(encoding="utf-8")

    # operator persists a change, the process is discarded and replaced
    (config_dir / CONFIG_FILENAME).write_text(
        generated + "\nport: 9001\n", encoding="utf-8"
    )
    replacement = load_settings()

    assert replacement.port == 9001  # same effective persisted configuration
    persisted = (config_dir / CONFIG_FILENAME).read_text(encoding="utf-8")
    assert persisted.startswith(generated)  # no re-initialization/overwrite


# --------------------------------------------------------------------------
# FRG-DEP-003 — config file + env precedence
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-DEP-003")
def test_first_run_generates_documented_config(config_dir):
    settings = load_settings()
    text = (config_dir / CONFIG_FILENAME).read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)

    secret_names = set(settings.secret_fields())
    for name, field in Settings.model_fields.items():
        assert name in text, f"setting {name} missing from generated config"
        assert field.description.splitlines()[0] in text, (
            f"explanatory comment for {name} missing"
        )
        if name in secret_names or name == "config_dir":
            assert name not in parsed  # commented placeholder only
        else:
            assert parsed[name] == field.default  # active line with the default
    # and the application runs with those defaults
    assert settings.port == 8789
    assert settings.log_level == "INFO"


@pytest.mark.req("FRG-DEP-003")
def test_config_file_value_takes_effect(config_dir):
    (config_dir / CONFIG_FILENAME).write_text("log_level: DEBUG\n", encoding="utf-8")
    settings = load_settings()
    assert settings.log_level == "DEBUG"


@pytest.mark.req("FRG-DEP-003")
def test_env_var_overrides_config_file(config_dir, monkeypatch):
    (config_dir / CONFIG_FILENAME).write_text("log_level: DEBUG\n", encoding="utf-8")
    monkeypatch.setenv("FORAGERR_LOG_LEVEL", "warning")
    settings = load_settings()
    assert settings.log_level == "WARNING"


@pytest.mark.req("FRG-DEP-003")
@pytest.mark.req("FRG-DEP-005")
def test_secrets_have_no_baked_in_defaults(config_dir):
    settings = load_settings()
    secrets = settings.secret_fields()
    assert secrets, "expected secret-typed settings to exist"
    for name, value in secrets.items():
        assert value.get_secret_value() == "", f"{name} has a baked-in default"
        field_default = Settings.model_fields[name].default
        assert isinstance(field_default, SecretStr)
        assert field_default.get_secret_value() == ""
    # generated config carries only commented placeholders for secrets
    parsed = yaml.safe_load((config_dir / CONFIG_FILENAME).read_text(encoding="utf-8"))
    assert not set(parsed) & set(secrets)


# --------------------------------------------------------------------------
# FRG-DEP-006 — log level configurable at runtime (file/env, no rebuild)
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-DEP-006")
def test_log_level_changes_via_file_and_env_without_rebuild(
    config_dir, monkeypatch, capsys
):
    def restart_and_probe(marker: str) -> str:
        settings = load_settings()
        setup_logging(settings.config_dir, level=settings.log_level)
        logging.getLogger("foragerr.test").debug(marker)
        logging.getLogger("foragerr.test").info(marker + "-info")
        return capsys.readouterr().out

    out = restart_and_probe("m-default")  # built-in default: INFO
    assert "m-default-info" in out and "msg=m-default " not in out

    generated = (config_dir / CONFIG_FILENAME).read_text(encoding="utf-8")
    (config_dir / CONFIG_FILENAME).write_text(
        generated + "\nlog_level: DEBUG\n", encoding="utf-8"
    )
    out = restart_and_probe("m-filedbg")  # file flips to DEBUG
    assert "m-filedbg " in out or "msg=m-filedbg\n" in out

    monkeypatch.setenv("FORAGERR_LOG_LEVEL", "WARNING")
    out = restart_and_probe("m-envwarn")  # env overrides file, WARNING wins
    assert "m-envwarn" not in out


# --------------------------------------------------------------------------
# FRG-NFR-008 — secrets self-register with redaction at config-load time
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-NFR-008")
def test_config_secrets_self_register_with_redaction_filter(
    config_dir, monkeypatch, capsys
):
    sentinel = "cv-key-from-env-98765abcde"
    monkeypatch.setenv("FORAGERR_COMICVINE_API_KEY", sentinel)
    settings = load_settings()  # registration happens here, nowhere else
    setup_logging(settings.config_dir, level=settings.log_level)

    logging.getLogger("foragerr.test").error(
        "config dump failed for %s", f"https://cv.example/?k={sentinel}"
    )
    stdout = capsys.readouterr().out
    file_text = (config_dir / "logs" / "foragerr.log").read_text(encoding="utf-8")
    for output in (stdout, file_text):
        assert sentinel not in output
        assert MASK in output
    # the loaded value itself is intact for outbound use
    assert settings.comicvine_api_key.get_secret_value() == sentinel


# --------------------------------------------------------------------------
# FRG-NFR-009 — fail-fast validation, non-zero exit, interval clamping
# --------------------------------------------------------------------------


@pytest.mark.req("FRG-NFR-009")
def test_invalid_config_reports_all_fields_in_one_pass(config_dir):
    (config_dir / CONFIG_FILENAME).write_text(
        'port: "not-a-port"\nlog_level: SUPERLOUD\n', encoding="utf-8"
    )
    with pytest.raises(ConfigError) as excinfo:
        load_settings()
    message = str(excinfo.value)
    assert "2 error(s)" in message  # both errors, one pass
    assert "port" in message and "integer" in message  # field + expected form
    assert "log_level" in message and "DEBUG" in message


@pytest.mark.req("FRG-NFR-009")
@pytest.mark.parametrize("reserved", ["/", "/api", "/api/v1", "/health"])
def test_opds_base_path_rejects_reserved_mount_paths(config_dir, reserved):
    """An OPDS base that collides with a core mount (the SPA root, /api, or
    /health) must fail validation, not silently shadow that route."""
    (config_dir / CONFIG_FILENAME).write_text(
        f"opds_base_path: {reserved!r}\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError) as excinfo:
        load_settings()
    assert "opds_base_path" in str(excinfo.value)


@pytest.mark.req("FRG-NFR-009")
@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_unwritable_config_dir_is_named_in_the_failure(config_dir):
    (config_dir / CONFIG_FILENAME).write_text("log_level: INFO\n", encoding="utf-8")
    config_dir.chmod(0o555)
    try:
        with pytest.raises(ConfigError) as excinfo:
            load_settings()
    finally:
        config_dir.chmod(0o755)
    message = str(excinfo.value)
    assert "config_dir" in message and "not writable" in message


@pytest.mark.req("FRG-NFR-009")
def test_out_of_range_interval_clamped_with_warning(config_dir, caplog):
    (config_dir / CONFIG_FILENAME).write_text(
        "scheduler_tick_seconds: 1\n", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING, logger="foragerr.config"):
        settings = load_settings()
    assert settings.scheduler_tick_seconds == 5  # documented floor
    warning = next(
        rec for rec in caplog.records if "scheduler_tick_seconds" in rec.getMessage()
    )
    text = warning.getMessage()
    assert warning.levelno == logging.WARNING
    assert "1" in text and "5" in text  # names key, supplied and clamped values


@pytest.mark.req("FRG-SCHED-005")
def test_settings_worker_defaults_match_default_pool_sizes(config_dir):
    """The settings-driven pool mapping and the DEFAULT_POOL_SIZES fallback are
    single-sourced; their defaults must not drift apart (FRG-SCHED-005)."""
    from foragerr.commands.service import DEFAULT_POOL_SIZES

    settings = Settings(config_dir=config_dir)
    assert {
        cls: getattr(settings, f"workers_{cls}") for cls in DEFAULT_POOL_SIZES
    } == DEFAULT_POOL_SIZES


@pytest.mark.req("FRG-NFR-009")
def test_interval_range_descriptions_match_enforced_bounds():
    """The generated config.yaml comments (Field descriptions) are built from
    INTERVAL_RANGES, so the documented bounds can never drift from the clamp."""
    from foragerr.config import INTERVAL_RANGES

    for name, (floor, ceiling) in INTERVAL_RANGES.items():
        description = Settings.model_fields[name].description or ""
        assert f"{floor}..{ceiling}" in description
