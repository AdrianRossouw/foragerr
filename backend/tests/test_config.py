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
        if name == "secret_key":
            # Environment-only AND secret: never emitted as a settable/placeholder
            # line so the passphrase can't be captured into the file (m6-keystore).
            assert "secret_key" not in parsed
            assert "FORAGERR_SECRET_KEY" in text  # documented as env-only
            continue
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
        field_default = Settings.model_fields[name].default
        assert isinstance(field_default, SecretStr)
        assert field_default.get_secret_value() == "", f"{name} has a baked-in default"
        # secret_key is the mandatory env-supplied passphrase (FRG-AUTH-011): its
        # DEFAULT is empty like the rest, but load_settings requires it non-empty,
        # so the loaded value is populated from the environment (not baked in).
        if name != "secret_key":
            assert value.get_secret_value() == "", f"{name} has a baked-in default"
    # generated config carries only commented placeholders for secrets
    parsed = yaml.safe_load((config_dir / CONFIG_FILENAME).read_text(encoding="utf-8"))
    assert not set(parsed) & set(secrets)


@pytest.mark.req("FRG-DEP-003")
def test_documented_config_omits_the_removed_credential_fields(config_dir):
    """The documented surface advertises no global credential no component
    consumes (m2-first-run-defaults): the three vestigial DogNZB/NZB.su/SAB
    global key placeholders are gone; the only global secret placeholder left is
    comicvine_api_key."""
    from foragerr.config import render_documented_config

    text = render_documented_config()
    for removed in ("dognzb_api_key", "nzbsu_api_key", "sabnzbd_api_key"):
        assert removed not in text, f"{removed} must not appear in the documented config"
        assert removed not in Settings.model_fields
    # The one legitimately-global secret placeholder remains.
    assert 'comicvine_api_key: ""' in text
    assert "comicvine_api_key" in Settings.model_fields


@pytest.mark.req("FRG-DEP-003")
def test_stale_removed_credential_keys_keep_an_existing_config_loading(
    config_dir, caplog
):
    """An existing config.yaml still carrying the removed global credential keys
    loads cleanly: the unknown keys are ignored with a logged warning (not a
    startup failure) and no removed field is reintroduced as an effective
    setting."""
    (config_dir / CONFIG_FILENAME).write_text(
        "log_level: DEBUG\n"
        'dognzb_api_key: "stale-dog"\n'
        'nzbsu_api_key: "stale-nzbsu"\n'
        'sabnzbd_api_key: "stale-sab"\n',
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING):
        settings = load_settings()

    # Startup succeeded and the real setting still took effect.
    assert settings.log_level == "DEBUG"
    # The unknown keys were logged as ignored...
    warning = "\n".join(r.getMessage() for r in caplog.records)
    assert "ignoring unknown key" in warning
    for stale in ("dognzb_api_key", "nzbsu_api_key", "sabnzbd_api_key"):
        assert stale in warning
        # ...and no removed field is reintroduced as an effective setting.
        assert not hasattr(settings, stale)


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


@pytest.mark.req("FRG-PP-009")
@pytest.mark.parametrize(
    "template",
    [
        "{Series Title} ({Year})",  # no issue token at all → issues 7 and 8 collide
        "{Series Title} {Issue Number:000} ({Year})",  # no id tag → same-number collision
    ],
)
def test_file_template_without_issue_identity_is_rejected(config_dir, template):
    """A naming template that renders the SAME name for distinct issues would
    silently overwrite one library file with another on rename, so config rejects
    it (injectivity guard, FRG-PP-009 data-loss corollary)."""
    (config_dir / CONFIG_FILENAME).write_text(
        f"file_naming_template: {template!r}\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError) as excinfo:
        load_settings()
    assert "file_naming_template" in str(excinfo.value)


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
@pytest.mark.req("FRG-META-001")
def test_comicvine_base_url_requires_https(config_dir):
    """The API key rides every CV request; a plaintext base would exfiltrate
    it (change-8 gate finding). https passes, http is refused at startup,
    and the e2e fixture opts in explicitly."""
    from foragerr.config import Settings

    Settings(config_dir=config_dir, comicvine_base_url="https://cv.example/api")
    with pytest.raises(Exception, match="plain http"):
        Settings(config_dir=config_dir, comicvine_base_url="http://cv.example/api")
    Settings(
        config_dir=config_dir,
        comicvine_base_url="http://mockhub:8080/api",
        comicvine_insecure_base=True,
    )
    with pytest.raises(Exception, match="absolute http"):
        Settings(config_dir=config_dir, comicvine_base_url="not-a-url")


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


@pytest.mark.req("FRG-CRTR-001")
def test_credits_fetch_per_refresh_clamped_with_warning(config_dir, caplog):
    """The detail-fetch bound clamps to 1..200 with a warning (design D3,
    m5-credits-live-fetch) — never rejected, never unbounded."""
    (config_dir / CONFIG_FILENAME).write_text(
        "credits_fetch_per_refresh: 0\n", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING, logger="foragerr.config"):
        settings = load_settings()
    assert settings.credits_fetch_per_refresh == 1  # documented floor

    (config_dir / CONFIG_FILENAME).write_text(
        "credits_fetch_per_refresh: 1000\n", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING, logger="foragerr.config"):
        settings = load_settings()
    assert settings.credits_fetch_per_refresh == 200  # documented ceiling
    assert any(
        "credits_fetch_per_refresh" in rec.getMessage() for rec in caplog.records
    )


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
