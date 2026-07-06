"""Docker image behaviour (FRG-DEP-001) — linuxserver.io conventions.

Exercises the SHIPPED image, end to end, against a real docker daemon:

- **PUID/PGID drop-privilege**: files the app writes under ``/config`` are owned
  by the caller-supplied ``PUID:PGID``, and the process runs as that user (not
  root).
- **Single ``/config`` volume persistence**: destroy + recreate the container
  against the same ``/config`` volume and all state (the SQLite DB, the generated
  ``config.yaml``) is preserved.
- **HEALTHCHECK**: the container reaches docker health status ``healthy`` by
  probing the unauthenticated ``/health`` endpoint.

Gated OFF by default (like the SAB container tests): needs a docker daemon AND
``FORAGERR_DEP_DOCKER=1``, so the ordinary ``pytest -q`` run stays green with
neither. The image is built once per session via ``tools/build-image.sh`` (which
also runs the secret scan), so this doubles as a build-script smoke.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "tools" / "build-image.sh"
IMAGE_TAG = "foragerr:pytest"

# A non-root uid/gid to remap onto; the host worktree is owned by this in CI/dev.
TEST_PUID = 1000
TEST_PGID = 1000


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return (
            subprocess.run(
                ["docker", "version"], capture_output=True, timeout=15
            ).returncode
            == 0
        )
    except Exception:  # noqa: BLE001 — any failure means "not available"
        return False


docker_gate = pytest.mark.skipif(
    os.environ.get("FORAGERR_DEP_DOCKER") != "1" or not _docker_available(),
    reason="deploy container tests gated on FORAGERR_DEP_DOCKER=1 + a docker daemon",
)


@pytest.fixture(scope="session")
def foragerr_image() -> str:
    """Build the image once (via the real build script) and return its tag."""
    subprocess.run(
        ["bash", str(BUILD_SCRIPT), "--tag", IMAGE_TAG],
        cwd=str(REPO_ROOT),
        check=True,
        timeout=600,
    )
    return IMAGE_TAG


class _Container:
    """A started foragerr container, cleaned up on exit."""

    def __init__(self, image: str, config_dir: Path, *, puid: int, pgid: int):
        self.name = f"frg-pytest-{uuid.uuid4().hex[:8]}"
        self.config_dir = config_dir
        subprocess.run(
            [
                "docker", "run", "-d", "--name", self.name,
                "-e", f"PUID={puid}", "-e", f"PGID={pgid}", "-e", "TZ=Etc/UTC",
                "-v", f"{config_dir}:/config",
                image,
            ],
            check=True, capture_output=True, timeout=60,
        )

    def health(self) -> str:
        out = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", self.name],
            capture_output=True, text=True, timeout=15,
        )
        return out.stdout.strip()

    def wait_healthy(self, timeout: float = 90.0) -> str:
        deadline = time.monotonic() + timeout
        status = "starting"
        while time.monotonic() < deadline:
            status = self.health()
            if status in ("healthy", "unhealthy"):
                return status
            time.sleep(2)
        return status

    def exec_user(self) -> str:
        """uid:gid the main process (pid 1's app) runs as, via the abc user."""
        out = subprocess.run(
            ["docker", "exec", self.name, "id", "-u", "abc"],
            capture_output=True, text=True, timeout=15,
        )
        return out.stdout.strip()

    def remove(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, timeout=30)


@pytest.mark.req("FRG-DEP-001")
def test_dockerignore_excludes_nested_env_files():
    """A bare ``.env`` pattern only matches at the context root, so a nested
    secret like ``frontend/.env`` (whose VITE_* values are inlined into the
    served bundle) would be COPY'd into the image. The recursive ``**/`` forms
    must be present. (Ungated: static check, no docker daemon needed.)"""
    text = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "**/.env" in text
    assert "**/.env.*" in text
    assert "!.env.example" in text  # the template is still allowed through


@docker_gate
@pytest.mark.docker
@pytest.mark.req("FRG-DEP-001")
def test_healthcheck_reports_healthy(foragerr_image, tmp_path):
    """The container's Docker HEALTHCHECK (probing /health) reaches 'healthy'."""
    c = _Container(foragerr_image, tmp_path / "cfg", puid=TEST_PUID, pgid=TEST_PGID)
    try:
        assert c.wait_healthy() == "healthy"
    finally:
        c.remove()


@docker_gate
@pytest.mark.docker
@pytest.mark.req("FRG-DEP-001")
def test_puid_pgid_owns_config_and_drops_root(foragerr_image, tmp_path):
    """Files written under /config are owned by PUID:PGID and the app is not root."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    c = _Container(foragerr_image, cfg, puid=TEST_PUID, pgid=TEST_PGID)
    try:
        assert c.wait_healthy() == "healthy"
        # The runtime user was remapped to the requested ids (privilege drop).
        assert c.exec_user() == str(TEST_PUID)
        # The app generates config.yaml + the DB on first run; they must be owned
        # by PUID:PGID on the host bind mount, not root.
        written = list(cfg.iterdir())
        assert any(p.name == "config.yaml" for p in written), written
        for p in written:
            st = p.stat()
            assert st.st_uid == TEST_PUID, f"{p.name} uid={st.st_uid}"
            assert st.st_gid == TEST_PGID, f"{p.name} gid={st.st_gid}"
    finally:
        c.remove()


@docker_gate
@pytest.mark.docker
@pytest.mark.req("FRG-DEP-001")
def test_config_persists_across_container_recreate(foragerr_image, tmp_path):
    """Destroy + recreate against the same /config volume preserves all state."""
    cfg = tmp_path / "cfg"
    cfg.mkdir()

    first = _Container(foragerr_image, cfg, puid=TEST_PUID, pgid=TEST_PGID)
    try:
        assert first.wait_healthy() == "healthy"
        db = cfg / "foragerr.db"
        conf = cfg / "config.yaml"
        assert db.is_file() and conf.is_file()
        db_before = db.stat().st_size
        conf_bytes = conf.read_bytes()
    finally:
        first.remove()

    # New container object == destroyed + recreated; container fs is disposable,
    # only /config carries over.
    second = _Container(foragerr_image, cfg, puid=TEST_PUID, pgid=TEST_PGID)
    try:
        assert second.wait_healthy() == "healthy"
        assert db.is_file(), "database not preserved across recreate"
        # Same DB file (not re-initialised) and identical config content.
        assert db.stat().st_size >= db_before
        assert conf.read_bytes() == conf_bytes, "config.yaml regenerated, not preserved"
    finally:
        second.remove()
