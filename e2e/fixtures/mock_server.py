"""mockhub — the hermetic fixture services for the foragerr e2e harness.

One process, two listeners, impersonating the three real upstreams the M1
journey talks to (FRG-PROC-010):

* **ComicVine** metadata API over **http** on :8080 (``/api/*``) — the add /
  refresh flow's series + issue source. The real base is hardcoded https; the
  harness points the app here via ``FORAGERR_COMICVINE_BASE_URL``.
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
ISSUES = [
    {"id": 340001, "number": "1", "cover_date": "2012-03-14"},
    {"id": 340002, "number": "2", "cover_date": "2012-04-11"},
]

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


# A 1x1 JPEG-ish blob for covers (content is irrelevant; the fetch just needs
# bytes with an image content-type from an allowlisted host).
_COVER = b"\xff\xd8\xff\xe0" + b"\x00" * 1024


# --- ComicVine ---------------------------------------------------------------

def _image_obj(name: str) -> dict:
    url = f"http://mockhub:8080/img/{name}"
    return {"original_url": url, "super_url": url, "medium_url": url, "small_url": url}


def _volume_object(*, with_issue_stubs: bool) -> dict:
    obj = {
        "id": CV_VOLUME_ID,
        "name": CV_VOLUME_NAME,
        "publisher": {"id": 1, "name": CV_PUBLISHER},
        "imprint": None,
        "start_year": CV_START_YEAR,
        "count_of_issues": len(ISSUES),
        "aliases": None,
        "description": "<p>A fixture volume for the foragerr e2e harness.</p>",
        "site_detail_url": "http://mockhub:8080/volume/4050-18166/",
        "first_issue": {"id": ISSUES[0]["id"], "name": None, "issue_number": "1"},
        "image": _image_obj("cover.jpg"),
    }
    if with_issue_stubs:
        obj["issues"] = [{"id": issue["id"]} for issue in ISSUES]
    return obj


def _issue_object(issue: dict) -> dict:
    return {
        "id": issue["id"],
        "name": None,
        "issue_number": issue["number"],
        "cover_date": issue["cover_date"],
        "store_date": issue["cover_date"],
        "image": _image_obj(f"issue-{issue['number']}.jpg"),
        "volume": {"id": CV_VOLUME_ID, "name": CV_VOLUME_NAME},
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
    return f"""<!doctype html><html><head><title>GetComics</title></head>
<body><div id="content"><main class="site-content" id="primary">
  <article class="post type-post">
    <a class="post-thumbnail" href="https://getcomics.org/comic/saga-1-2012/"></a>
    <h1 class="post-title entry-title">
      <a href="https://getcomics.org/comic/saga-1-2012/">Saga #1 (2012)</a>
    </h1>
    <p class="post-info">Year : 2012 | Size : 45 MB | Format : CBZ</p>
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
    item = (
        "<item>"
        "<title>Saga 001 (2012) (Digital) (old-usenet-post)</title>"
        "<guid>saga-001-usenet-old</guid>"
        '<enclosure url="http://mockhub:8080/newznab/nzb/1" length="52428800" type="application/x-nzb"/>'
        f"<pubDate>{old}</pubDate>"
        '<newznab:attr name="category" value="7030"/>'
        '<newznab:attr name="size" value="52428800"/>'
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
        return JSONResponse(_list_envelope([_volume_object(with_issue_stubs=False)]))

    @app.get("/api/volume/4050-{volume_id}/")
    async def cv_volume(volume_id: int) -> JSONResponse:
        return JSONResponse(_single_envelope(_volume_object(with_issue_stubs=True)))

    @app.get("/api/issues/")
    async def cv_issues(request: Request) -> JSONResponse:
        return JSONResponse(_list_envelope([_issue_object(i) for i in ISSUES]))

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
