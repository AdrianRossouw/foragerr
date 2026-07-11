"""mockhub — the hermetic fixture services for the foragerr e2e harness.

One process, two listeners, impersonating the three real upstreams the M1
journey talks to (FRG-PROC-010):

* **ComicVine** metadata API over **http** on :8080 (``/api/*``) — the add /
  refresh flow's series + issue source. The real base is hardcoded https; the
  harness points the app here via ``FORAGERR_COMICVINE_BASE_URL``. Serves TWO
  volumes: Saga (the spine's download journey) and Fables (the library-import
  scenario's in-place import of pre-existing files, FRG-UI-015/FRG-IMP-023).
* **Newznab** indexer over **http** on :8080 (``/newznab/api``) — supplies a
  deliberately *rejected* release so the interactive-search overlay has a
  verbatim rejection reason to render. Never grabbed.
* **GetComics** DDL site over **https** on :443 (host ``getcomics.org``) — the
  approved release. Grab drives the built-in DDL client fully in-process:
  search page -> post page -> file download -> verify -> import. TLS is
  mandatory (the DDL client refuses non-https), so mockhub serves a cert whose
  CA the app container trusts (appended to certifi at container start).

No third-party deps: everything here is stdlib + FastAPI/uvicorn already present
in the foragerr image this container is built FROM.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

# --- fixture identities ------------------------------------------------------

CV_VOLUME_ID = 18166
CV_VOLUME_NAME = "Saga"
CV_START_YEAR = "2012"
CV_PUBLISHER = "Image Comics"
# Two issues; #1 is the one the journey wants, searches for, grabs and reads.
# ``credits`` mirror the real API shape: they are served ONLY on the per-issue
# DETAIL endpoint (``issue/4050-{id}/``), never on the list rows below
# (FRG-CRTR-001) — the list endpoint returns null credits.
ISSUES = [
    {
        "id": 340001,
        "number": "1",
        "cover_date": "2012-03-14",
        "credits": [
            {"id": 900001, "name": "Brian K. Vaughan", "role": "writer"},
            {"id": 900002, "name": "Fiona Staples", "role": "artist, cover"},
        ],
    },
    {
        "id": 340002,
        "number": "2",
        "cover_date": "2012-04-11",
        "credits": [
            {"id": 900001, "name": "Brian K. Vaughan", "role": "writer"},
        ],
    },
]

# A SECOND volume for the library-import scenario (y-library-import.spec.ts):
# pre-existing "Fables" folders seeded on disk are scanned, matched to THIS
# volume and imported in place. It must be distinct from Saga — the spine has
# already added 18166, and the library-import execute creates a NEW series.
LI_VOLUME_ID = 4977
LI_VOLUME_NAME = "Fables"
LI_START_YEAR = "2002"
LI_PUBLISHER = "Vertigo"
LI_ISSUES = [
    {
        "id": 350001,
        "number": "1",
        "cover_date": "2002-07-10",
        "credits": [
            {"id": 900010, "name": "Bill Willingham", "role": "writer"},
        ],
    },
    {"id": 350002, "number": "2", "cover_date": "2002-08-14"},
]

#: Every volume the fixture ComicVine knows, keyed by cv volume id. A search
#: term matches a volume when the volume's name appears in the parsed term
#: (case-insensitive); any other term returns an EMPTY result set, which is
#: what stages the library-import no-match group.
VOLUMES: dict[int, dict] = {
    CV_VOLUME_ID: {
        "name": CV_VOLUME_NAME,
        "start_year": CV_START_YEAR,
        "publisher": CV_PUBLISHER,
        "issues": ISSUES,
    },
    LI_VOLUME_ID: {
        "name": LI_VOLUME_NAME,
        "start_year": LI_START_YEAR,
        "publisher": LI_PUBLISHER,
        "issues": LI_ISSUES,
    },
}

# The mock is handed the exact cbz bytes at start (mounted at /data) so the
# harness on the host and the app in the container share one source of truth for
# the byte-identity assertion. Fallback keeps the module importable in isolation.
CBZ_PATH = os.environ.get("MOCKHUB_CBZ", "/data/saga-001.cbz")


def _cbz_bytes() -> bytes:
    try:
        with open(CBZ_PATH, "rb") as handle:
            return handle.read()
    except OSError:
        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("001.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 200_000)
        return buffer.getvalue()


def _cbz_size_bytes() -> int:
    """The TRUE size of the served cbz — the single source of truth for every
    advertised size (GetComics search page, Newznab length/size). Advertising a
    fictitious 45 MB while serving a ~200 KB file is dishonest and lets the
    download-size sanity checks pass on a lie; the fixture advertises the real
    byte count instead."""
    return len(_cbz_bytes())


def _cbz_size_label() -> str:
    """Human "Size : N KB/MB" string for the GetComics search page, derived from
    the true byte count (parseable by the DDL adapter's size regex)."""
    size = _cbz_size_bytes()
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{max(1, round(size / 1024))} KB"


# A 1x1 JPEG-ish blob for covers (content is irrelevant; the fetch just needs
# bytes with an image content-type from an allowlisted host).
_COVER = b"\xff\xd8\xff\xe0" + b"\x00" * 1024


# --- ComicVine ---------------------------------------------------------------

def _image_obj(name: str) -> dict:
    url = f"http://mockhub:8080/img/{name}"
    return {"original_url": url, "super_url": url, "medium_url": url, "small_url": url}


def _volume_object(volume_id: int, *, with_issue_stubs: bool) -> dict:
    volume = VOLUMES[volume_id]
    obj = {
        "id": volume_id,
        "name": volume["name"],
        "publisher": {"id": 1, "name": volume["publisher"]},
        "imprint": None,
        "start_year": volume["start_year"],
        "count_of_issues": len(volume["issues"]),
        "aliases": None,
        "description": "<p>A fixture volume for the foragerr e2e harness.</p>",
        "site_detail_url": f"http://mockhub:8080/volume/4050-{volume_id}/",
        "first_issue": {
            "id": volume["issues"][0]["id"],
            "name": None,
            "issue_number": "1",
        },
        "image": _image_obj(f"cover-{volume_id}.jpg"),
    }
    if with_issue_stubs:
        obj["issues"] = [{"id": issue["id"]} for issue in volume["issues"]]
    return obj


def _issue_object(volume_id: int, issue: dict) -> dict:
    return {
        "id": issue["id"],
        "name": None,
        "issue_number": issue["number"],
        "cover_date": issue["cover_date"],
        "store_date": issue["cover_date"],
        "image": _image_obj(f"issue-{volume_id}-{issue['number']}.jpg"),
        "volume": {"id": volume_id, "name": VOLUMES[volume_id]["name"]},
    }


def _list_envelope(results: list[dict]) -> dict:
    return {
        "error": "OK",
        "limit": 100,
        "offset": 0,
        "number_of_page_results": len(results),
        "number_of_total_results": len(results),
        "status_code": 1,
        "results": results,
    }


def _single_envelope(result: dict) -> dict:
    return {
        "error": "OK",
        "limit": 1,
        "offset": 0,
        "number_of_page_results": 1,
        "number_of_total_results": 1,
        "status_code": 1,
        "results": result,
    }


# --- GetComics (DDL) HTML ----------------------------------------------------

def search_html() -> str:
    # The post's publish time drives the release age. It must be RECENT so the
    # decision engine does not retention-reject the approved release (the same
    # retention window is what rejects the deliberately-old Newznab release).
    recent = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00"
    )
    # Advertise the TRUE served file size (not a fictitious 45 MB) so the
    # download-size sanity checks are exercised against an honest expectation.
    size = _cbz_size_label()
    return f"""<!doctype html><html><head><title>GetComics</title></head>
<body><div id="content"><main class="site-content" id="primary">
  <article class="post type-post">
    <a class="post-thumbnail" href="https://getcomics.org/comic/saga-1-2012/"></a>
    <h1 class="post-title entry-title">
      <a href="https://getcomics.org/comic/saga-1-2012/">Saga #1 (2012)</a>
    </h1>
    <p class="post-info">Year : 2012 | Size : {size} | Format : CBZ</p>
    <time datetime="{recent}">recently</time>
  </article>
</main></div></body></html>"""

POST_HTML = """<!doctype html><html><head><title>Saga #1 (2012)</title></head>
<body><div id="content"><main class="site-content" id="primary">
  <article class="post">
    <h1 class="post-title entry-title">Saga #1 (2012)</h1>
    <div class="aio-pulse">
      <h3 class="quality">Saga #1 (2012) : CBZ</h3>
      <a href="https://getcomics.org/dlds/main?id=saga1" title="Download Now">Download Now</a>
      <a href="https://getcomics.org/dlds/mirror?id=saga1" title="Mirror Download">Mirror Download</a>
    </div>
  </article>
</main></div></body></html>"""


# --- Newznab XML -------------------------------------------------------------

CAPS_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<caps>"
    '<limits max="100" default="75"/>'
    "<searching>"
    '<search available="yes" supportedParams="q"/>'
    '<book-search available="yes" supportedParams="q"/>'
    "</searching>"
    "<categories>"
    '<category id="7000" name="Books"><subcat id="7030" name="Comics"/></category>'
    "</categories>"
    "</caps>"
)


def _newznab_search_xml() -> str:
    # A single result engineered to be REJECTED: its post date is far older than
    # the retention window the compose sets (FORAGERR_USENET_RETENTION_DAYS), so
    # the decision engine rejects it for retention with a verbatim reason. It is
    # never grabbed — it exists only to populate a rejected row in the overlay.
    old = dt.datetime(2015, 1, 1, tzinfo=dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    # Advertise the TRUE fixture size rather than a fictitious 50 MiB; this
    # release is rejected for retention (age), not size, so an honest size does
    # not change the outcome — it just removes the size lie.
    size = _cbz_size_bytes()
    item = (
        "<item>"
        "<title>Saga 001 (2012) (Digital) (old-usenet-post)</title>"
        "<guid>saga-001-usenet-old</guid>"
        f'<enclosure url="http://mockhub:8080/newznab/nzb/1" length="{size}" type="application/x-nzb"/>'
        f"<pubDate>{old}</pubDate>"
        '<newznab:attr name="category" value="7030"/>'
        f'<newznab:attr name="size" value="{size}"/>'
        "</item>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" '
        'xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">'
        f"<channel>{item}</channel></rss>"
    )


# --- app / routing -----------------------------------------------------------

def build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict:
        return {"status": "up"}

    # ---- ComicVine (http) ----
    @app.get("/api/volumes/")
    async def cv_search(request: Request) -> JSONResponse:
        # Exercise the REAL client query construction (foragerr.metadata.comicvine
        # ComicVineClient.search_series): it sends ``api_key`` + a
        # ``filter=name:<term>`` param (plus field_list/sort/offset/limit). A
        # keyless request is rejected 401; a volume is returned ONLY when the
        # parsed name term contains its name (case-insensitive), else an empty
        # result set — so a malformed client query fails the add-series scenario
        # instead of silently passing, and an unknown series folder stages as
        # the library-import no-match group.
        if not request.query_params.get("api_key"):
            return JSONResponse(
                {"error": "Invalid API Key", "status_code": 100, "results": []},
                status_code=401,
            )
        term = ""
        for clause in request.query_params.get("filter", "").split(","):
            field, sep, value = clause.partition(":")
            if sep and field.strip().casefold() == "name":
                term = value.strip()
                break
        matches = [
            _volume_object(volume_id, with_issue_stubs=False)
            for volume_id, volume in VOLUMES.items()
            if volume["name"].casefold() in term.casefold()
        ]
        return JSONResponse(_list_envelope(matches))

    @app.get("/api/volume/4050-{volume_id}/")
    async def cv_volume(volume_id: int) -> JSONResponse:
        # Tolerant fallback to the Saga volume for ids the fixture never minted
        # (preserves the pre-multi-volume behavior for hand-poked requests).
        known = volume_id if volume_id in VOLUMES else CV_VOLUME_ID
        return JSONResponse(
            _single_envelope(_volume_object(known, with_issue_stubs=True))
        )

    @app.get("/api/issue/4050-{issue_id}/")
    async def cv_issue_detail(issue_id: int) -> JSONResponse:
        # The per-issue credit DETAIL endpoint (FRG-CRTR-001): the ONLY place the
        # real ComicVine serves person_credits — the list endpoint (``/issues/``
        # below) returns null. The refresh fetch phase calls this per
        # credit-needing issue; an unknown id returns an empty credit list.
        credits = None
        for volume in VOLUMES.values():
            for issue in volume["issues"]:
                if issue["id"] == issue_id:
                    credits = issue.get("credits", [])
                    break
            if credits is not None:
                break
        return JSONResponse(
            _single_envelope(
                {"id": issue_id, "person_credits": credits if credits is not None else []}
            )
        )

    @app.get("/api/issues/")
    async def cv_issues(request: Request) -> JSONResponse:
        # The real client fetches per volume via ``filter=volume:<id>``
        # (foragerr.metadata.comicvine); honor it so a Fables refresh never
        # receives Saga issues. No/unknown filter keeps the Saga default.
        volume_id = CV_VOLUME_ID
        for clause in request.query_params.get("filter", "").split(","):
            field, sep, value = clause.partition(":")
            if sep and field.strip().casefold() == "volume":
                requested = value.strip()
                if requested.isdigit() and int(requested) in VOLUMES:
                    volume_id = int(requested)
                break
        return JSONResponse(
            _list_envelope(
                [_issue_object(volume_id, i) for i in VOLUMES[volume_id]["issues"]]
            )
        )

    @app.get("/img/{name}")
    async def cv_image(name: str) -> Response:
        return Response(content=_COVER, media_type="image/jpeg")

    # ---- Newznab (http) ----
    @app.get("/newznab/api")
    async def newznab(request: Request) -> Response:
        mode = request.query_params.get("t", "")
        if mode == "caps":
            return Response(content=CAPS_XML, media_type="application/xml")
        return Response(content=_newznab_search_xml(), media_type="application/xml")

    # ---- GetComics DDL (served on the https listener; host getcomics.org) ----
    @app.get("/")
    async def gc_search(request: Request) -> Response:
        return PlainTextResponse(search_html(), media_type="text/html")

    @app.get("/comic/{slug}/")
    async def gc_post(slug: str) -> Response:
        return PlainTextResponse(POST_HTML, media_type="text/html")

    @app.get("/dlds/{which}")
    async def gc_download(which: str) -> Response:
        return Response(
            content=_cbz_bytes(),
            media_type="application/zip",
            headers={"content-disposition": 'attachment; filename="Saga 001 (2012).cbz"'},
        )

    return app


async def _serve() -> None:
    app = build_app()
    http = uvicorn.Server(
        uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="warning")
    )
    https = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",
            port=443,
            log_level="warning",
            ssl_certfile=os.environ["MOCKHUB_TLS_CERT"],
            ssl_keyfile=os.environ["MOCKHUB_TLS_KEY"],
        )
    )
    await asyncio.gather(http.serve(), https.serve())


if __name__ == "__main__":
    asyncio.run(_serve())
