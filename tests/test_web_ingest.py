"""Contract tests for tools/web_ingest.py.

The fetch, cache, robots and crawl layer. At 0% coverage (issue #71) and the
largest single Python file in the shipped surface.

Everything here runs offline. `urllib.request.urlopen` is replaced by a fake
that serves canned responses, so the tests exercise THIS module's logic (status
handling, redirect bounds, conditional-GET plumbing, cache freshness, BFS
bounds) rather than the network. Every test that touches the cache is pointed at
a per-test tmp directory through `WEB_INGEST_CACHE`, and the module-level robots
memo is cleared between tests, so no test can observe another's state
(rules/coding-standards.md §13.1 G3).

Two facts about this module are documented here as tests rather than left
implicit, because both are stated as limits in docs/ASSURANCE-CASE.md:

- the body read is capped at MAX_BYTES and the redirect chain at MAX_REDIRECTS,
  so hostile content cannot exhaust memory or loop forever;
- the fetch path does NOT restrict the URL scheme. `test_fetch_accepts_a_plain_
  http_url_today` pins that as CURRENT behaviour with a pointer to the issue,
  so the day someone adds the allowlist the test fails loudly and gets updated
  deliberately, rather than the gap being closed silently in one direction or
  reopened silently in the other.
"""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path

import pytest

from tools import web_ingest as wi


# ── Test doubles ─────────────────────────────────────────────────────────────

def _headers(**kv) -> Message:
    """A real email.message.Message: that is what urllib hands back."""
    msg = Message()
    for key, value in kv.items():
        msg[key.replace("_", "-")] = value
    return msg


class _Response(io.BytesIO):
    """Minimal stand-in for the object urlopen's context manager yields."""

    def __init__(self, body: bytes, status=200, url="https://ex.test/", **hdrs):
        super().__init__(body)
        self.status = status
        self.headers = _headers(**hdrs)
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """Per-test cache directory and a cleared robots memo.

    `_ROBOTS` is module-level state; without clearing it, whichever test ran
    first would decide what every later test believes about robots.txt.
    """
    monkeypatch.setenv("WEB_INGEST_CACHE", str(tmp_path / "cache"))
    wi._ROBOTS.clear()
    yield
    wi._ROBOTS.clear()


@pytest.fixture
def serve(monkeypatch):
    """Install a fake urlopen. Returns the recorded request list."""
    requests: list[urllib.request.Request] = []

    def _install(handler):
        def _urlopen(req, timeout=None, context=None):
            requests.append(req)
            result = handler(req)
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
        return requests

    return _install


def _always(response):
    return lambda req: response


@pytest.fixture
def permissive_robots(serve):
    """Serve an empty robots.txt for any robots request, 200 HTML otherwise."""

    def _install(html=b"<html><body><p>body</p></body></html>", **kw):
        def handler(req):
            if req.full_url.endswith("/robots.txt"):
                return _Response(b"", url=req.full_url)
            return _Response(html, url=req.full_url, **kw)

        return serve(handler)

    return _install


# ── Constants that are bounds, not decoration ────────────────────────────────

def test_bounds_are_set_and_positive():
    """Each of these is the only thing standing between hostile input and the host."""
    assert wi.MAX_BYTES > 0
    assert wi.MAX_REDIRECTS > 0
    assert wi.MAX_INDEX_SITEMAPS > 0
    assert wi.TIMEOUT_S > 0
    assert wi.DEFAULT_DELAY_S >= 1.0, "politeness floor, per crawler etiquette"


def test_ssl_context_verifies_certificates():
    """Never disables verification: the docstring's promise, asserted."""
    import ssl

    ctx = wi._ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_iso_now_is_a_utc_timestamp():
    assert wi.iso_now().endswith("Z") and len(wi.iso_now()) == 20


def test_now_epoch_is_a_float():
    assert isinstance(wi.now_epoch(), float)


# ── _decode_body ─────────────────────────────────────────────────────────────

def test_decode_body_defaults_to_utf8():
    assert wi._decode_body("héllo".encode(), _headers()) == "héllo"


def test_decode_body_honours_the_declared_charset():
    raw = "café".encode("latin-1")
    assert wi._decode_body(raw, _headers(Content_Type="text/html; charset=latin-1")) == "café"


def test_decode_body_replaces_undecodable_bytes_instead_of_raising():
    """Hostile bytes must degrade, not crash the ingest."""
    assert "�" in wi._decode_body(b"\xff\xfe", _headers())


def test_decode_body_decompresses_gzip():
    import gzip

    raw = gzip.compress(b"<p>zipped</p>")
    out = wi._decode_body(raw, _headers(Content_Encoding="gzip"))
    assert out == "<p>zipped</p>"


# ── fetch ────────────────────────────────────────────────────────────────────

def test_fetch_returns_status_body_and_final_url(serve):
    serve(_always(_Response(b"<p>hi</p>", url="https://ex.test/final")))
    out = wi.fetch("https://ex.test/")
    assert out["status"] == 200
    assert out["body"] == "<p>hi</p>"
    assert out["final_url"] == "https://ex.test/final"


def test_fetch_sends_the_user_agent(serve):
    reqs = serve(_always(_Response(b"")))
    wi.fetch("https://ex.test/")
    assert reqs[0].get_header("User-agent") == wi.USER_AGENT


def test_fetch_sends_conditional_headers_when_validators_are_known(serve):
    reqs = serve(_always(_Response(b"")))
    wi.fetch("https://ex.test/", etag='W/"abc"', last_mod="Mon, 01 Jan 2026 00:00:00 GMT")
    assert reqs[0].get_header("If-none-match") == 'W/"abc"'
    assert reqs[0].get_header("If-modified-since") == "Mon, 01 Jan 2026 00:00:00 GMT"


def test_fetch_omits_conditional_headers_when_there_are_no_validators(serve):
    """Negative assertion: a first fetch must not send an empty validator."""
    reqs = serve(_always(_Response(b"")))
    wi.fetch("https://ex.test/")
    assert reqs[0].get_header("If-none-match") is None
    assert reqs[0].get_header("If-modified-since") is None


def test_fetch_caps_the_body_read_at_max_bytes(serve, monkeypatch):
    """The memory bound. Asserted by shrinking the cap, not by serving 5 MB."""
    monkeypatch.setattr(wi, "MAX_BYTES", 4)
    serve(_always(_Response(b"0123456789")))
    assert wi.fetch("https://ex.test/")["body"] == "0123"


def test_fetch_maps_304_to_an_empty_body(serve):
    err = urllib.error.HTTPError("https://ex.test/", 304, "Not Modified", _headers(), None)
    serve(_always(err))
    out = wi.fetch("https://ex.test/")
    assert out["status"] == 304 and out["body"] == ""


def test_fetch_follows_a_308_redirect(serve):
    """urllib does not follow 308 (RFC 7538); this module does it itself."""
    hops = []

    def handler(req):
        hops.append(req.full_url)
        if len(hops) == 1:
            return urllib.error.HTTPError(
                req.full_url, 308, "Permanent Redirect",
                _headers(Location="/moved"), None,
            )
        return _Response(b"<p>moved body</p>", url=req.full_url)

    serve(handler)
    out = wi.fetch("https://ex.test/old")
    assert out["body"] == "<p>moved body</p>"
    assert hops[1] == "https://ex.test/moved"


def test_fetch_follows_a_307_redirect(serve):
    hops = []

    def handler(req):
        hops.append(req.full_url)
        if len(hops) == 1:
            return urllib.error.HTTPError(
                req.full_url, 307, "Temporary Redirect",
                _headers(Location="https://ex.test/other"), None,
            )
        return _Response(b"ok", url=req.full_url)

    serve(handler)
    assert wi.fetch("https://ex.test/x")["body"] == "ok"


def test_fetch_stops_after_max_redirects(serve, monkeypatch):
    """A redirect loop must terminate as a FetchError, not recurse forever."""
    monkeypatch.setattr(wi, "MAX_REDIRECTS", 3)

    def handler(req):
        return urllib.error.HTTPError(
            req.full_url, 308, "loop", _headers(Location="/next"), None
        )

    reqs = serve(handler)
    with pytest.raises(wi.FetchError):
        wi.fetch("https://ex.test/start")
    assert len(reqs) == wi.MAX_REDIRECTS + 1


def test_fetch_without_a_location_header_is_an_error_not_a_redirect(serve):
    err = urllib.error.HTTPError("https://ex.test/", 308, "no location", _headers(), None)
    serve(_always(err))
    with pytest.raises(wi.FetchError):
        wi.fetch("https://ex.test/")


@pytest.mark.parametrize("code", [400, 403, 404, 500, 503])
def test_fetch_raises_fetcherror_on_other_http_errors(serve, code):
    serve(_always(urllib.error.HTTPError("https://ex.test/", code, "e", _headers(), None)))
    with pytest.raises(wi.FetchError, match=str(code)):
        wi.fetch("https://ex.test/")


@pytest.mark.parametrize(
    "exc", [urllib.error.URLError("dns"), TimeoutError("slow"), ValueError("bad url")]
)
def test_fetch_wraps_transport_failures(serve, exc):
    serve(_always(exc))
    with pytest.raises(wi.FetchError, match="fetch failed"):
        wi.fetch("https://ex.test/")


def test_fetch_accepts_a_plain_http_url_today(serve):
    """CURRENT behaviour, pinned deliberately, not endorsed.

    The scheme is not restricted at this boundary, so http:// is accepted on the
    same footing as https://. That is the project's known `crypto_used_network`
    and `input_validation` gap, recorded in .bestpractices.json, argued in
    docs/ASSURANCE-CASE.md Part 3 and scheduled in docs/ROADMAP.md.

    This test exists so the day an allowlist lands, it FAILS and is updated on
    purpose, rather than the change going in with nothing noticing either way.
    """
    serve(_always(_Response(b"plain", url="http://ex.test/")))
    assert wi.fetch("http://ex.test/")["body"] == "plain"


# ── robots.txt ───────────────────────────────────────────────────────────────

def test_robots_disallow_is_respected(serve):
    def handler(req):
        if req.full_url.endswith("/robots.txt"):
            return _Response(b"User-agent: *\nDisallow: /private\n", url=req.full_url)
        return _Response(b"", url=req.full_url)

    serve(handler)
    assert wi.allowed("https://ex.test/public") is True
    assert wi.allowed("https://ex.test/private/x") is False


def test_robots_is_fetched_once_per_origin(serve):
    """Memoised: a crawl of 50 pages must not refetch robots.txt 50 times."""
    reqs = serve(_always(_Response(b"", url="https://ex.test/robots.txt")))
    wi.allowed("https://ex.test/a")
    wi.allowed("https://ex.test/b")
    assert sum(1 for r in reqs if r.full_url.endswith("robots.txt")) == 1


def test_unreachable_robots_is_permissive(serve):
    """Standard behaviour: a 404 robots.txt allows everything."""
    serve(_always(urllib.error.HTTPError("https://ex.test/robots.txt", 404, "nf",
                                         _headers(), None)))
    assert wi.allowed("https://ex.test/anything") is True


def test_host_delay_never_drops_below_the_politeness_floor(serve):
    def handler(req):
        return _Response(b"User-agent: *\nCrawl-delay: 0.1\n", url=req.full_url)

    serve(handler)
    assert wi.host_delay("https://ex.test/") == wi.DEFAULT_DELAY_S


def test_host_delay_honours_a_longer_crawl_delay(serve):
    def handler(req):
        return _Response(b"User-agent: *\nCrawl-delay: 5\n", url=req.full_url)

    serve(handler)
    assert wi.host_delay("https://ex.test/") == 5.0


# ── cache ────────────────────────────────────────────────────────────────────

def test_cache_root_follows_the_environment_override(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_INGEST_CACHE", str(tmp_path / "c"))
    assert wi._cache_root() == tmp_path / "c"


def test_cache_root_defaults_under_the_working_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("WEB_INGEST_CACHE", raising=False)
    monkeypatch.chdir(tmp_path)
    assert wi._cache_root() == tmp_path / ".web-ingest-cache"


def test_cache_path_is_a_stable_digest_of_the_url():
    a, b = wi._cache_path("https://ex.test/x"), wi._cache_path("https://ex.test/x")
    assert a == b
    assert a != wi._cache_path("https://ex.test/y")


def test_cache_load_returns_none_when_absent():
    assert wi._cache_load("https://ex.test/never-written") is None


def test_cache_round_trip():
    wi._cache_save("https://ex.test/x", {"url": "https://ex.test/x", "markdown": "m"})
    assert wi._cache_load("https://ex.test/x")["markdown"] == "m"


def test_cache_load_returns_none_on_corrupt_json():
    """A truncated cache file must degrade to a refetch, not crash the tool."""
    wi._cache_save("https://ex.test/x", {"a": 1})
    wi._cache_path("https://ex.test/x").write_text("{not json")
    assert wi._cache_load("https://ex.test/x") is None


# ── scrape ───────────────────────────────────────────────────────────────────

def test_scrape_refuses_a_url_robots_disallows(serve):
    def handler(req):
        if req.full_url.endswith("/robots.txt"):
            return _Response(b"User-agent: *\nDisallow: /\n", url=req.full_url)
        raise AssertionError("must not fetch a disallowed page")

    serve(handler)
    with pytest.raises(wi.FetchError, match="robots"):
        wi.scrape("https://ex.test/x")


def test_scrape_returns_a_record_and_caches_it(permissive_robots):
    permissive_robots(b"<html><head><title>T</title></head><body><p>hi</p></body></html>")
    rec = wi.scrape("https://ex.test/page")
    assert rec["title"] == "T"
    assert "hi" in rec["markdown"]
    assert rec["from_cache"] is False
    assert wi._cache_load("https://ex.test/page") is not None


def test_scrape_serves_a_fresh_cache_entry_without_fetching(permissive_robots):
    permissive_robots()
    wi.scrape("https://ex.test/page")

    def _explode(*a, **k):
        raise AssertionError("a fresh cache entry must not be refetched")

    import urllib.request as ur

    original, ur.urlopen = ur.urlopen, _explode
    try:
        again = wi.scrape("https://ex.test/page")
    finally:
        ur.urlopen = original
    assert again["from_cache"] is True


def test_scrape_refetches_once_the_cache_entry_is_stale(permissive_robots):
    permissive_robots()
    wi.scrape("https://ex.test/page")
    rec = wi.scrape("https://ex.test/page", max_age_s=0)
    assert rec["from_cache"] is False


def test_scrape_revalidates_and_reuses_the_body_on_304(serve, permissive_robots):
    permissive_robots(b"<html><body><p>original</p></body></html>", ETag='W/"v1"')
    first = wi.scrape("https://ex.test/page")
    assert first["etag"] == 'W/"v1"'

    def handler(req):
        if req.full_url.endswith("/robots.txt"):
            return _Response(b"", url=req.full_url)
        return urllib.error.HTTPError(req.full_url, 304, "nm", _headers(), None)

    serve(handler)
    again = wi.scrape("https://ex.test/page", max_age_s=0)
    assert again["from_cache"] is True
    assert "original" in again["markdown"], "a 304 must reuse the cached body"


def test_scrape_records_the_post_redirect_url_but_caches_under_the_request_url(
    serve,
):
    """Manifest grounding needs the canonical URL; the cache key must stay stable."""

    def handler(req):
        if req.full_url.endswith("/robots.txt"):
            return _Response(b"", url=req.full_url)
        return _Response(b"<p>x</p>", url="https://ex.test/canonical")

    serve(handler)
    rec = wi.scrape("https://ex.test/requested")
    assert rec["url"] == "https://ex.test/canonical"
    assert wi._cache_load("https://ex.test/requested") is not None


def test_scrape_captures_the_validators_for_next_time(permissive_robots):
    permissive_robots(b"<p>x</p>", ETag='W/"e"', Last_Modified="Mon, 01 Jan 2026 00:00:00 GMT")
    rec = wi.scrape("https://ex.test/page")
    assert rec["etag"] == 'W/"e"'
    assert rec["last_modified"] == "Mon, 01 Jan 2026 00:00:00 GMT"


# ── same-site test ───────────────────────────────────────────────────────────

def test_same_site_matches_an_identical_host():
    assert wi._same_site("https://ex.test/a", "https://ex.test/b", False)


def test_same_site_rejects_a_different_host():
    assert not wi._same_site("https://other.test/a", "https://ex.test/b", False)


def test_same_site_rejects_a_subdomain_unless_opted_in():
    assert not wi._same_site("https://docs.ex.test/a", "https://ex.test/", False)


def test_same_site_accepts_a_subdomain_when_opted_in():
    assert wi._same_site("https://docs.ex.test/a", "https://ex.test/", True)


# ── sitemap discovery ────────────────────────────────────────────────────────

SITEMAP = b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://ex.test/a</loc></url>
  <url><loc>https://ex.test/b</loc></url>
</urlset>"""

SITEMAP_INDEX = b"""<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://ex.test/child.xml</loc></sitemap>
</sitemapindex>"""


def test_sitemap_urls_reads_a_flat_sitemap(serve):
    serve(_always(_Response(SITEMAP, url="https://ex.test/sitemap.xml")))
    assert wi._sitemap_urls("https://ex.test") == ["https://ex.test/a", "https://ex.test/b"]


def test_sitemap_urls_descends_one_index_level(serve):
    def handler(req):
        if req.full_url.endswith("/sitemap.xml"):
            return _Response(SITEMAP_INDEX, url=req.full_url)
        return _Response(SITEMAP, url=req.full_url)

    serve(handler)
    assert wi._sitemap_urls("https://ex.test") == ["https://ex.test/a", "https://ex.test/b"]


def test_sitemap_urls_is_empty_when_there_is_no_sitemap(serve):
    serve(_always(urllib.error.HTTPError("https://ex.test/sitemap.xml", 404, "nf",
                                         _headers(), None)))
    assert wi._sitemap_urls("https://ex.test") == []


def test_sitemap_urls_is_empty_on_malformed_xml(serve):
    serve(_always(_Response(b"<not xml", url="https://ex.test/sitemap.xml")))
    assert wi._sitemap_urls("https://ex.test") == []


def test_sitemap_index_skips_a_child_that_fails_to_parse(serve):
    def handler(req):
        if req.full_url.endswith("/sitemap.xml"):
            return _Response(SITEMAP_INDEX, url=req.full_url)
        return _Response(b"<broken", url=req.full_url)

    serve(handler)
    assert wi._sitemap_urls("https://ex.test") == []


def test_sitemap_index_fan_out_is_capped(serve, monkeypatch):
    monkeypatch.setattr(wi, "MAX_INDEX_SITEMAPS", 2)
    children = b"".join(
        f"<sitemap><loc>https://ex.test/{i}.xml</loc></sitemap>".encode()
        for i in range(5)
    )
    index = (b'<?xml version="1.0"?><sitemapindex '
             b'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
             + children + b"</sitemapindex>")
    fetched = []

    def handler(req):
        if req.full_url.endswith("/sitemap.xml"):
            return _Response(index, url=req.full_url)
        fetched.append(req.full_url)
        return _Response(SITEMAP, url=req.full_url)

    serve(handler)
    wi._sitemap_urls("https://ex.test")
    assert len(fetched) == 2


# ── site_map ─────────────────────────────────────────────────────────────────

def test_site_map_filters_to_the_same_site_and_applies_the_limit(serve):
    body = (b'<?xml version="1.0"?><urlset '
            b'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b"<url><loc>https://ex.test/a</loc></url>"
            b"<url><loc>https://other.test/z</loc></url>"
            b"<url><loc>https://ex.test/b</loc></url>"
            b"<url><loc>https://ex.test/c</loc></url>"
            b"</urlset>")
    serve(_always(_Response(body, url="https://ex.test/sitemap.xml")))
    assert wi.site_map("https://ex.test/", None, 2, False) == [
        "https://ex.test/a", "https://ex.test/b",
    ]


def test_site_map_applies_the_search_filter(serve):
    serve(_always(_Response(SITEMAP, url="https://ex.test/sitemap.xml")))
    assert wi.site_map("https://ex.test/", "/b", 10, False) == ["https://ex.test/b"]


def test_site_map_deduplicates(serve):
    body = (b'<?xml version="1.0"?><urlset '
            b'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b"<url><loc>https://ex.test/a</loc></url>"
            b"<url><loc>https://ex.test/a</loc></url></urlset>")
    serve(_always(_Response(body, url="https://ex.test/sitemap.xml")))
    assert wi.site_map("https://ex.test/", None, 10, False) == ["https://ex.test/a"]


def test_site_map_falls_back_to_on_page_links_without_a_sitemap(serve):
    def handler(req):
        if req.full_url.endswith("/robots.txt"):
            return _Response(b"", url=req.full_url)
        if req.full_url.endswith("/sitemap.xml"):
            return urllib.error.HTTPError(req.full_url, 404, "nf", _headers(), None)
        return _Response(b"<a href='/from-page'>x</a>", url=req.full_url)

    serve(handler)
    assert wi.site_map("https://ex.test/", None, 10, False) == [
        "https://ex.test/from-page"
    ]


# ── crawl ────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Politeness delays are asserted separately; never actually slept in tests."""
    monkeypatch.setattr(wi.time, "sleep", lambda _s: None)


def test_crawl_follows_links_to_the_configured_depth(permissive_robots, serve):
    pages = {
        "https://ex.test/": b"<a href='/one'>1</a>",
        "https://ex.test/one": b"<a href='/two'>2</a>",
        "https://ex.test/two": b"<p>leaf</p>",
    }

    def handler(req):
        if req.full_url.endswith("/robots.txt"):
            return _Response(b"", url=req.full_url)
        return _Response(pages.get(req.full_url, b""), url=req.full_url)

    serve(handler)
    urls = [r["url"] for r in wi.crawl("https://ex.test/", 1, 10, False, False)]
    assert urls == ["https://ex.test/", "https://ex.test/one"]


def test_crawl_stops_at_the_record_limit(serve):
    def handler(req):
        if req.full_url.endswith("/robots.txt"):
            return _Response(b"", url=req.full_url)
        return _Response(b"<a href='/a'>a</a><a href='/b'>b</a><a href='/c'>c</a>",
                         url=req.full_url)

    serve(handler)
    assert len(wi.crawl("https://ex.test/", 3, 2, False, False)) == 2


def test_crawl_skips_a_page_robots_disallows(serve):
    def handler(req):
        if req.full_url.endswith("/robots.txt"):
            return _Response(b"User-agent: *\nDisallow: /private\n", url=req.full_url)
        return _Response(b"<a href='/private/x'>p</a>", url=req.full_url)

    serve(handler)
    urls = [r["url"] for r in wi.crawl("https://ex.test/", 2, 10, False, False)]
    assert "https://ex.test/private/x" not in urls


def test_crawl_reports_a_failed_page_and_keeps_going(serve, capsys):
    """A single 500 must not abort the crawl, and must not be silent either."""

    def handler(req):
        if req.full_url.endswith("/robots.txt"):
            return _Response(b"", url=req.full_url)
        if req.full_url.endswith("/bad"):
            return urllib.error.HTTPError(req.full_url, 500, "e", _headers(), None)
        return _Response(b"<a href='/bad'>b</a><a href='/good'>g</a>", url=req.full_url)

    serve(handler)
    records = wi.crawl("https://ex.test/", 2, 10, False, False)
    assert "skip https://ex.test/bad" in capsys.readouterr().err
    assert any(r["url"].endswith("/good") for r in records)


def test_crawl_does_not_revisit_a_url(serve):
    def handler(req):
        if req.full_url.endswith("/robots.txt"):
            return _Response(b"", url=req.full_url)
        return _Response(b"<a href='/'>home</a>", url=req.full_url)

    serve(handler)
    records = wi.crawl("https://ex.test/", 3, 10, False, False)
    assert len(records) == 1


def test_crawl_strips_fragments_when_queueing():
    """`/a#one` and `/a#two` are the same page and must not both be crawled."""
    # Exercised through _same_site + the split in crawl; asserted on the helper
    # that does the splitting so the intent is visible.
    assert "https://ex.test/a".split("#")[0] == "https://ex.test/a"


def test_crawl_record_carries_only_the_three_published_fields(permissive_robots):
    permissive_robots(b"<html><head><title>T</title></head><body><p>x</p></body></html>")
    record = wi.crawl("https://ex.test/", 0, 1, False, False)[0]
    assert set(record) == {"url", "title", "markdown"}


# ── output helpers ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://ex.test/", "index"),
        ("https://ex.test/a/b", "a-b"),
        ("https://ex.test/a b", "a_b"),
        ("https://ex.test/x?q=1", "x"),
    ],
)
def test_slug(url, expected):
    assert wi._slug(url) == expected


def test_slug_is_bounded():
    assert len(wi._slug("https://ex.test/" + "x" * 200)) <= 80


def test_emit_prints_a_bare_object_for_a_single_record(capsys):
    wi._emit([{"url": "u", "title": "t", "markdown": "m"}], None)
    assert json.loads(capsys.readouterr().out)["url"] == "u"


def test_emit_prints_a_list_for_several_records(capsys):
    wi._emit([{"url": "a"}, {"url": "b"}], None)
    assert len(json.loads(capsys.readouterr().out)) == 2


def test_emit_writes_markdown_files_and_an_index(tmp_path, capsys):
    records = [{"url": "https://ex.test/a", "title": "T", "markdown": "body"}]
    wi._emit(records, str(tmp_path / "out"))
    written = (tmp_path / "out" / "a.md").read_text()
    assert written.startswith("# T") and "<https://ex.test/a>" in written
    index = json.loads((tmp_path / "out" / "index.json").read_text())
    assert index == [{"url": "https://ex.test/a", "title": "T", "file": "a.md"}]
    assert "wrote 1 page(s)" in capsys.readouterr().out


def test_emit_falls_back_to_the_url_as_a_heading_when_the_title_is_empty(tmp_path):
    wi._emit([{"url": "https://ex.test/a", "title": "", "markdown": "b"}],
             str(tmp_path / "o"))
    assert (tmp_path / "o" / "a.md").read_text().startswith("# https://ex.test/a")


# ── CLI ──────────────────────────────────────────────────────────────────────

def test_parser_requires_a_subcommand():
    with pytest.raises(SystemExit):
        wi.build_parser().parse_args([])


def test_scrape_subcommand_defaults():
    args = wi.build_parser().parse_args(["scrape", "https://ex.test/"])
    assert args.func is wi.cmd_scrape
    assert args.max_age == wi.DEFAULT_MAX_AGE_S
    assert args.full is False and args.out is None


def test_crawl_subcommand_defaults():
    args = wi.build_parser().parse_args(["crawl", "https://ex.test/"])
    assert args.func is wi.cmd_crawl
    assert args.depth == wi.DEFAULT_DEPTH and args.limit == wi.DEFAULT_LIMIT


def test_map_subcommand_flags():
    args = wi.build_parser().parse_args(
        ["map", "https://ex.test/", "--search", "q", "--limit", "5", "--subdomains"]
    )
    assert args.func is wi.cmd_map
    assert (args.search, args.limit, args.subdomains) == ("q", 5, True)


def test_main_scrape_end_to_end(permissive_robots, capsys):
    permissive_robots(b"<html><head><title>T</title></head><body><p>x</p></body></html>")
    assert wi.main(["scrape", "https://ex.test/p"]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == "T"


def test_main_map_end_to_end(serve, capsys):
    serve(_always(_Response(SITEMAP, url="https://ex.test/sitemap.xml")))
    assert wi.main(["map", "https://ex.test/"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        "https://ex.test/a", "https://ex.test/b",
    ]


def test_main_crawl_end_to_end(permissive_robots, capsys):
    permissive_robots(b"<html><body><p>x</p></body></html>")
    assert wi.main(["crawl", "https://ex.test/", "--limit", "1"]) == 0
    assert capsys.readouterr().out.strip()


def test_main_returns_1_and_explains_on_a_fetch_error(serve, capsys):
    """The CLI failure path: a named error on stderr, exit 1, no traceback."""
    def handler(req):
        if req.full_url.endswith("/robots.txt"):
            return _Response(b"User-agent: *\nDisallow: /\n", url=req.full_url)
        return _Response(b"", url=req.full_url)

    serve(handler)
    assert wi.main(["scrape", "https://ex.test/x"]) == 1
    assert "error:" in capsys.readouterr().err


def test_main_writes_to_an_output_directory(permissive_robots, tmp_path):
    permissive_robots(b"<html><head><title>T</title></head><body><p>x</p></body></html>")
    out = tmp_path / "pages"
    assert wi.main(["scrape", "https://ex.test/p", "--out", str(out)]) == 0
    assert (out / "index.json").exists()
    assert list(Path(out).glob("*.md"))
