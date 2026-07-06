"""OPDS security-by-construction tests: the download surface exposes no path
parameter (route-table inventory), id/page parameters reject injection
payloads at the type boundary, and the OPDS module builds no SQL text from
request input (FRG-OPDS-003, FRG-OPDS-004).
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

import foragerr.opds.atom as atom_mod
import foragerr.opds.mime as mime_mod
import foragerr.opds.router as router_mod
from foragerr.app import create_app
from opds_support import opds_settings, seed, simple_series

ATOM = "{http://www.w3.org/2005/Atom}"


@pytest.fixture
def settings(tmp_path: Path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    return opds_settings(cfg)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


# --- FRG-OPDS-003: traversal unrepresentable (route-table inventory) --------


@pytest.mark.req("FRG-OPDS-003")
def test_opds_routes_declare_no_path_parameter(client):
    """Inventory every OPDS route from the OpenAPI schema: no route may declare
    a ``path``/``file``/``filename`` parameter, and every path parameter that
    exists must be an integer id — so a filesystem path is unrepresentable in
    the URL surface."""
    schema = client.app.openapi()
    opds_paths = {p: spec for p, spec in schema["paths"].items() if p.startswith("/opds")}
    assert opds_paths, "OPDS routes should be mounted"

    download_routes = []
    for path, spec in opds_paths.items():
        names = set(re.findall(r"{(\w+)}", path))
        # No path-shaped parameter anywhere in the URL template.
        assert names.isdisjoint({"path", "file", "filename", "filepath"}), path
        # Every declared path parameter is an integer id.
        for method_spec in spec.values():
            for param in method_spec.get("parameters", []):
                if param.get("in") == "path":
                    assert param["name"] in {"issue_file_id", "series_id"}, path
                    assert param["schema"]["type"] == "integer", f"{path}:{param['name']}"
        if "/file/" in path:
            download_routes.append(path)

    # The single download route is id-only.
    assert download_routes == ["/opds/file/{issue_file_id}"]


# --- FRG-OPDS-004: injection payloads inert at the type boundary ------------


@pytest.mark.req("FRG-OPDS-004")
def test_injection_payloads_in_id_and_page_params_are_inert(client, tmp_path):
    data = client.portal.call(
        seed, client.app, tmp_path / "library", [simple_series(n_issues=2)]
    )
    series_id = data["series"][0]["id"]
    payload = '" OR 1=1 --'

    # id/page params are typed int: a SQL payload never reaches a query — it
    # is rejected at the type boundary (the app maps validation errors to 400).
    assert client.get(f"/opds/file/{payload}").status_code == 400
    assert client.get(f"/opds/series/{payload}").status_code == 400
    assert client.get("/opds/series", params={"page": payload}).status_code == 400

    # The database is untouched: a normal feed still returns exactly the real
    # rows (no injected "OR 1=1" row leak, no dropped data).
    feed = ET.fromstring(client.get(f"/opds/series/{series_id}").text)
    assert len(feed.findall(f"{ATOM}entry")) == 2


# --- FRG-OPDS-004: static check — no interpolated SQL ------------------------


@pytest.mark.req("FRG-OPDS-004")
def test_opds_module_builds_no_sql_text_from_input():
    """Static scan of the OPDS sources: no ``sqlalchemy.text``, no f-string /
    %-format / .format / concatenation building SQL — every query is an ORM
    ``select`` with bound parameters."""
    sql_kw = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|WHERE|ORDER\s+BY)\b", re.I)
    interp = re.compile(
        r"""(f["'].*?)"""  # f-string ...
        r"""|(%\s*\()"""  # %-formatting
        r"""|(\.format\s*\()""",  # .format(
    )
    for module in (router_mod, atom_mod, mime_mod):
        src = Path(module.__file__).read_text(encoding="utf-8")
        # No textual SQL construct at all.
        assert "text(" not in src.replace("context(", ""), module.__name__
        # No interpolation expression that also contains SQL keywords.
        for line in src.splitlines():
            code = line.split("#", 1)[0]  # ignore comments/docstring-ish text
            if interp.search(code) and sql_kw.search(code):
                raise AssertionError(f"possible interpolated SQL in {module.__name__}: {line!r}")
    # Positive: the router uses the ORM select() construct.
    assert "select(" in Path(router_mod.__file__).read_text(encoding="utf-8")
