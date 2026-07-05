"""Safe filename generation + outbound TLS static guard (FRG-DDL-011/012)."""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from foragerr.ddl.download import (
    build_allowlist,
    download_link,
    partial_path_for,
    resolve_output_path,
    safe_output_name,
)
from foragerr.ddl.errors import DdlDownloadError
from ddl_support import make_cbz, make_factory

REPO_SRC = Path(__file__).resolve().parents[2] / "src"

#: A corpus of hostile remote-supplied names (redirect URLs / Content-Disposition
#: values) that must never influence the on-disk path (FRG-DDL-011).
HOSTILE_NAMES = [
    "../../../../etc/passwd",
    "..\\..\\Windows\\System32\\cmd",
    "/absolute/evil",
    "CON",
    "name\x00.cbz",
    "a/b/c",
    "....//....//x",
]


@pytest.mark.req("FRG-DDL-011")
def test_filename_generated_from_library_metadata_with_issueid_tag():
    name = safe_output_name(
        series_title="Saga",
        issue_number="12",
        issue_id=4567,
        queue_id=9,
        ext=".cbz",
    )
    assert name == "Saga 12 [__4567__].cbz"


@pytest.mark.req("FRG-DDL-011")
def test_missing_issue_id_falls_back_to_queue_id_tag():
    name = safe_output_name(
        series_title="Saga",
        issue_number="1",
        issue_id=None,
        queue_id=42,
        ext=".cbz",
    )
    assert name == "Saga 1 [__q42__].cbz"


@pytest.mark.req("FRG-DDL-011")
def test_hostile_metadata_names_stay_inside_staging(tmp_path):
    staging = tmp_path / "ddl-staging"
    staging.mkdir()
    for hostile in HOSTILE_NAMES:
        name = safe_output_name(
            series_title=hostile,
            issue_number=hostile,
            issue_id=None,
            queue_id=1,
            ext=".cbz",
        )
        resolved = resolve_output_path(staging, name)
        assert resolved.parent == staging.resolve()
        assert staging.resolve() in resolved.parents or resolved.parent == staging.resolve()


@pytest.mark.req("FRG-DDL-011")
def test_resolve_output_path_rejects_an_escaping_name(tmp_path):
    staging = tmp_path / "ddl-staging"
    staging.mkdir()
    # A name that literally contains a separator would try to escape; the
    # generator never produces one, but resolve_output_path is the backstop.
    with pytest.raises(DdlDownloadError):
        resolve_output_path(staging, "../escape.cbz")


@pytest.mark.req("FRG-DDL-011")
async def test_hostile_content_disposition_never_shapes_the_partial_path(tmp_path):
    body = make_cbz()

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-disposition": 'attachment; filename="../../etc/passwd"'
            },
            content=body,
        )

    factory, _ = make_factory(tmp_path, handler)
    staging = tmp_path / "ddl-staging"
    staging.mkdir()
    partial = partial_path_for(staging, 3)
    outcome = await download_link(
        factory=factory,
        url="https://getcomics.org/dlds/run.php?id=1",
        partial_path=partial,
        allowlist=build_allowlist("https://getcomics.org"),
    )
    # The partial path is the id-named file; the Content-Disposition value had
    # no effect whatsoever.
    assert outcome.partial_path == partial
    assert partial.parent == staging


@pytest.mark.req("FRG-DDL-012")
def test_no_verify_false_anywhere_in_backend_src():
    """TLS certificate verification is never disabled — no ``verify=False``
    (or any solver-service equivalent) exists in backend/src (FRG-DDL-012)."""
    pattern = re.compile(r"verify\s*=\s*False")
    offenders: list[str] = []
    for path in REPO_SRC.rglob("*.py"):
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if pattern.search(line):
                offenders.append(f"{path}:{lineno}: {line.strip()}")
    assert not offenders, "verify=False found:\n" + "\n".join(offenders)
