"""Env-gated live ComicVine smoke test (FRG-META-001).

Skipped unless ``FORAGERR_CV_LIVE=1`` is set. Uses the real API key from the
repo-root ``.env`` (or the ``COMICVINE_API_KEY`` environment variable) and hits
the real endpoint for ONE well-known volume — Image Comics' *Saga*
(volume 4050-18166). It never runs in the default ``pytest`` invocation and
never prints/logs the key. Skips cleanly (not fails) when the gate or key is
absent.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from foragerr.http import HttpClientFactory
from foragerr.metadata.comicvine import ComicVineClient
from http_support import make_settings

SAGA_VOLUME_ID = 18166


def _load_cv_key() -> str | None:
    if os.environ.get("COMICVINE_API_KEY"):
        return os.environ["COMICVINE_API_KEY"]
    for parent in Path(__file__).resolve().parents:
        env_file = parent / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("COMICVINE_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


@pytest.mark.req("FRG-META-001")
@pytest.mark.skipif(
    os.environ.get("FORAGERR_CV_LIVE") != "1",
    reason="live ComicVine smoke test disabled (set FORAGERR_CV_LIVE=1)",
)
async def test_live_lookup_volume_and_issues(tmp_path):
    key = _load_cv_key()
    if not key:
        pytest.skip("no COMICVINE_API_KEY available for the live smoke test")

    settings = make_settings(
        tmp_path, comicvine_api_key=key, comicvine_min_interval_seconds=2.0
    )
    factory = HttpClientFactory(settings)  # real DNS + real network
    async with ComicVineClient(settings, factory) as client:
        search = await client.search_series("Saga")
        assert search.candidates, "live search returned no candidates"

        volume = await client.get_volume(SAGA_VOLUME_ID)
        assert volume.cv_volume_id == SAGA_VOLUME_ID
        assert volume.name  # honoring the requested field_list

        issues = await client.get_issues(SAGA_VOLUME_ID)
        assert issues.items, "live issue fetch returned nothing"
        # issue numbers preserved verbatim as strings, never coerced
        assert all(isinstance(i.issue_number, (str, type(None))) for i in issues.items)
