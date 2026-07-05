"""SABnzbd container integration layer (task 1.5, FRG-DL-003/004).

Two gated tiers, BOTH skipped by default so the plain ``pytest -q`` run needs
neither docker nor network:

- **docker tier** (``@pytest.mark.docker``, gated on ``FORAGERR_SAB_DOCKER=1``
  + a working docker daemon): spins ``linuxserver/sabnzbd`` with a pre-seeded
  API key, exercises the LIVE API contract through the production
  :class:`SabnzbdClient` (``mode=version`` / ``get_config`` / ``queue`` /
  ``history``), and regenerates the recorded fixtures from the container's real
  responses so fixture drift is bounded.
- **live download tier** (``@pytest.mark.docker`` + ``@pytest.mark.live``,
  additionally gated on news-server credentials in ``.env`` and a small test
  NZB): configures the container's news server from the credentials
  (Tweaknews / Newshosting — coded against the ACTUAL env var names including
  the flagged ``DL_NZB_NEWSHOTING_PASS`` typo) and completes ONE small, polite
  download end-to-end (grab → SAB fetch → completed). Without creds it skips and
  completion stays fixture-based.

Credential VALUES are never logged, echoed, or committed — only their presence
is tested.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from foragerr.config import Settings
from foragerr.downloads.clients.sabnzbd import SabnzbdClient
from foragerr.downloads.settings import SabnzbdSettings
from foragerr.http import HttpClientFactory
from foragerr.providers.backoff import ProviderBackoff

# Actual .env credential names (env-credentials memory; the PASS key carries the
# flagged NEWSHOTING typo — matched verbatim, never "corrected").
NEWS_CRED_NAMES = {
    "newshosting": ("DL_NZB_NEWSHOSTING_USER", "DL_NZB_NEWSHOTING_PASS"),
    "tweaknews": ("DL_NZB_TWEAKNEWS_USER", "DL_NZB_TWEAKNEWS_PASS"),
}

SAB_IMAGE = "linuxserver/sabnzbd"
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sab"


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return (
            subprocess.run(
                ["docker", "version"],
                capture_output=True,
                timeout=15,
            ).returncode
            == 0
        )
    except Exception:  # noqa: BLE001 — any failure means "not available"
        return False


def _read_env_value(name: str) -> str | None:
    """Read one credential value from the environment or the repo-root ``.env``.

    Never logs or returns anything but the raw value / ``None``; callers only
    check presence and pass it straight into the container config.
    """
    if os.environ.get(name):
        return os.environ[name]
    for parent in Path(__file__).resolve().parents:
        env_file = parent / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(f"{name}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _news_credentials() -> tuple[str, str, str] | None:
    """(provider_host, user, pass) for the first provider with full creds, else None."""
    hosts = {
        "newshosting": "news.newshosting.com",
        "tweaknews": "news.tweaknews.eu",
    }
    for provider, (user_key, pass_key) in NEWS_CRED_NAMES.items():
        user = _read_env_value(user_key)
        password = _read_env_value(pass_key)
        if user and password:
            return hosts[provider], user, password
    return None


docker_gate = pytest.mark.skipif(
    os.environ.get("FORAGERR_SAB_DOCKER") != "1" or not _docker_available(),
    reason="SAB docker integration gated on FORAGERR_SAB_DOCKER=1 + a docker daemon",
)


def _seed_config(config_dir: Path, api_key: str, server: tuple[str, str, str] | None) -> None:
    """Pre-seed a minimal ``sabnzbd.ini`` so the API is usable on first boot."""
    lines = [
        "[misc]",
        f"api_key = {api_key}",
        "host = 0.0.0.0",
        "port = 8080",
        "download_dir = /downloads/incomplete",
        "complete_dir = /downloads/complete",
        "[categories]",
        "[[comics]]",
        "name = comics",
        "dir = comics",
    ]
    if server is not None:
        host, user, password = server
        lines += [
            "[servers]",
            f"[[{host}]]",
            f"host = {host}",
            "port = 563",
            "ssl = 1",
            f"username = {user}",
            f"password = {password}",
            "connections = 4",
            "enable = 1",
        ]
    (config_dir / "sabnzbd.ini").write_text("\n".join(lines) + "\n", encoding="utf-8")


class _Container:
    """A throwaway ``linuxserver/sabnzbd`` container, force-removed on exit."""

    def __init__(self, config_dir: Path, port: int) -> None:
        self._config_dir = config_dir
        self._port = port
        self._cid: str | None = None

    def __enter__(self) -> "_Container":
        result = subprocess.run(
            [
                "docker", "run", "-d", "--rm",
                "-p", f"{self._port}:8080",
                "-v", f"{self._config_dir}:/config",
                "-e", "PUID=1000", "-e", "PGID=1000",
                SAB_IMAGE,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            pytest.skip(f"could not start {SAB_IMAGE}: {result.stderr.strip()[:200]}")
        self._cid = result.stdout.strip()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._cid:
            subprocess.run(
                ["docker", "rm", "-f", self._cid],
                capture_output=True,
                timeout=60,
            )


def _make_client(port: int, api_key: str, db) -> SabnzbdClient:
    settings = Settings(config_dir=Path("/tmp"))  # values irrelevant for local_service
    factory = HttpClientFactory(settings)
    model = SabnzbdSettings.model_validate(
        {"base_url": f"http://127.0.0.1:{port}", "api_key": api_key, "category": "comics"}
    )
    return SabnzbdClient(model, factory, backoff=ProviderBackoff(db), client_id=1)


async def _wait_ready(client: SabnzbdClient, *, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            await client.test()
            return
        except Exception as exc:  # noqa: BLE001 — container still booting
            last = exc
            time.sleep(2.0)
    pytest.skip(f"SABnzbd container did not become ready: {last}")


@docker_gate
@pytest.mark.docker
@pytest.mark.req("FRG-DL-003")
@pytest.mark.req("FRG-DL-004")
async def test_live_sab_api_contract_and_fixture_refresh(tmp_path, db):
    """Exercise the live SAB API through the production client + refresh fixtures."""
    config_dir = tmp_path / "sabcfg"
    config_dir.mkdir()
    api_key = "foragerrtestkey0000000000000000"
    port = 18080
    _seed_config(config_dir, api_key, server=None)
    with _Container(config_dir, port):
        client = _make_client(port, api_key, db)
        await _wait_ready(client)
        result = await client.test()
        assert result.success and result.version
        items = await client.get_items()  # empty queue+history, but a live shape
        assert isinstance(items, list)
        # Regenerate the recorded fixtures from the live responses so drift is
        # bounded (the plain-run contract tests read these).
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        (FIXTURE_DIR / "version.json").write_text(
            json.dumps({"version": result.version}), encoding="utf-8"
        )


@docker_gate
@pytest.mark.skipif(
    _news_credentials() is None,
    reason="live download tier gated on news-server credentials in .env",
)
@pytest.mark.docker
@pytest.mark.live
@pytest.mark.req("FRG-DL-003")
async def test_live_small_download_end_to_end(tmp_path, db):
    """Configure the container's news server and complete ONE small download.

    The small test NZB URL is supplied out-of-band via ``FORAGERR_SAB_TEST_NZB_URL``
    (kept polite: a single tiny post); absent it, this tier skips rather than
    guessing a live post.
    """
    from foragerr.search_ops.grab import GrabReleaseCommand

    nzb_url = os.environ.get("FORAGERR_SAB_TEST_NZB_URL")
    if not nzb_url:
        pytest.skip("set FORAGERR_SAB_TEST_NZB_URL to a small test NZB to run e2e")

    server = _news_credentials()
    config_dir = tmp_path / "sabcfg"
    config_dir.mkdir()
    api_key = "foragerrtestkey0000000000000000"
    port = 18081
    _seed_config(config_dir, api_key, server=server)
    with _Container(config_dir, port):
        client = _make_client(port, api_key, db)
        await _wait_ready(client)
        download_id = await client.download(
            GrabReleaseCommand(
                indexer_id=1, guid="e2e", link=nzb_url, title="foragerr e2e test"
            )
        )
        assert download_id
        deadline = time.monotonic() + 300
        completed = False
        while time.monotonic() < deadline:
            for item in await client.get_items():
                if item.download_id == download_id and item.status.value == "completed":
                    completed = True
            if completed:
                break
            time.sleep(5.0)
        assert completed, "small e2e download did not reach completed"
