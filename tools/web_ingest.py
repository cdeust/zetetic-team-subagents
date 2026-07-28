#!/usr/bin/env python3
"""web_ingest.py — self-hosted web ingestion engine (scrape / map / crawl).

A dependency-free, owned replica of Firecrawl's self-hostable core. Fetches with
stdlib urllib, respects robots.txt (urllib.robotparser), extracts main-content
markdown via web_extract, and caches fetches so revisiting a topic is cheap and
incremental (conditional GET; Firecrawl's maxAge concept). NO web search (not
self-hostable) and NO LLM extraction (the agent does that on the markdown).

This tool is standalone: it writes ingested content to stdout or a directory. It
does NOT write the semantic layer — wiring the two is the caller's choice.

Exit codes: 0 success, 1 runtime/network error, 2 usage error.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import ssl
import sys
import time
import datetime
import urllib.error
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:  # imported under its package path (test suite, mutation runs)
    from tools import web_extract
except ImportError:  # run as a script with tools/ on PYTHONPATH (web-ingest.sh)
    import web_extract


def _ssl_context() -> ssl.SSLContext:
    """Verified TLS context. Use certifi's CA bundle when present (it ships with
    requests), else the system default. Never disables verification."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_SSL_CTX = _ssl_context()

# Identifies the crawler to servers; includes a contact convention per RFC 9309 §2.2.4.
USER_AGENT = "zetetic-web-ingest/1.0 (+self-hosted; respects robots.txt)"
TIMEOUT_S = 20  # operational default — long enough for slow docs hosts, bounded.
MAX_BYTES = 5_000_000  # cap response body to bound memory; operational default.
# Politeness floor between requests to one host. Source: common crawler etiquette
# (>=1s/host, e.g. wget --wait, Internet Archive guidance); overridden by robots crawl-delay.
DEFAULT_DELAY_S = 1.0
DEFAULT_DEPTH = 2  # bounded so crawl output cannot overflow agent context (Firecrawl crawl warning).
DEFAULT_LIMIT = 20
DEFAULT_MAX_AGE_S = 86_400  # serve cache without re-fetch for 1 day; operational default.
MAX_INDEX_SITEMAPS = 10  # cap child-sitemap fan-out in a sitemap index.
# Bound on chained redirects we follow manually (urllib auto-follows 301/302/303/307 but not 308).
# source: RFC 9110 §15.4 advises a limit; 10 matches urllib's own default (HTTPRedirectHandler.max_redirections).
MAX_REDIRECTS = 10


def now_epoch() -> float:
    return time.time()


def iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- HTTP fetch (infrastructure) ------------------------------------------
class FetchError(RuntimeError):
    pass


def _decode_body(raw: bytes, headers) -> str:
    if headers.get("Content-Encoding", "").lower() == "gzip":
        raw = gzip.decompress(raw)
    charset = "utf-8"
    ctype = headers.get("Content-Type", "")
    match = re.search(r"charset=([\w-]+)", ctype, re.I)
    if match:
        charset = match.group(1)
    return raw.decode(charset, errors="replace")


def fetch(url: str, etag: str | None = None, last_mod: str | None = None,
          _redirects: int = 0) -> dict:
    """Conditional GET. Returns {status, headers, body, final_url} (body='' on 304).

    urllib auto-follows 301/302/303/307; it does NOT follow 308 (RFC 7538), so we
    follow 307/308 ourselves with a bounded count and the same method (a redirected
    moved page is the canonical source — final_url records where the body came from).
    """
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    if etag:
        headers["If-None-Match"] = etag
    if last_mod:
        headers["If-Modified-Since"] = last_mod
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=_SSL_CTX) as resp:
            body = _decode_body(resp.read(MAX_BYTES), resp.headers)
            return {"status": resp.status, "headers": resp.headers, "body": body, "final_url": resp.geturl()}
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return {"status": 304, "headers": exc.headers, "body": "", "final_url": url}
        if exc.code in (307, 308) and _redirects < MAX_REDIRECTS and exc.headers.get("Location"):
            target = urljoin(url, exc.headers["Location"])
            return fetch(target, etag=etag, last_mod=last_mod, _redirects=_redirects + 1)
        raise FetchError(f"HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise FetchError(f"fetch failed for {url}: {exc}") from exc


# --- robots.txt (politeness) ----------------------------------------------
_ROBOTS: dict[str, urllib.robotparser.RobotFileParser] = {}


def _robots(host_url: str) -> urllib.robotparser.RobotFileParser:
    origin = f"{urlparse(host_url).scheme}://{urlparse(host_url).netloc}"
    if origin not in _ROBOTS:
        parser = urllib.robotparser.RobotFileParser()
        try:  # fetch via our own client so the verified SSL context is used
            parser.parse(fetch(f"{origin}/robots.txt")["body"].splitlines())
        except FetchError:  # unreachable/404 -> permissive (standard behavior)
            parser.parse([])
        _ROBOTS[origin] = parser
    return _ROBOTS[origin]


def allowed(url: str) -> bool:
    return _robots(url).can_fetch(USER_AGENT, url)


def host_delay(url: str) -> float:
    delay = _robots(url).crawl_delay(USER_AGENT)
    return max(float(delay) if delay else 0.0, DEFAULT_DELAY_S)


# --- cache (incrementality) -----------------------------------------------
def _cache_root() -> Path:
    import os
    base = os.environ.get("WEB_INGEST_CACHE")
    if base:
        return Path(base)
    return Path.cwd() / ".web-ingest-cache"


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()[:32]
    return _cache_root() / f"{digest}.json"


def _cache_load(url: str) -> dict | None:
    path = _cache_path(url)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _cache_save(key_url: str, record: dict) -> None:
    """Cache under the REQUESTED url (key_url); record['url'] may be the post-redirect final url."""
    root = _cache_root()
    root.mkdir(parents=True, exist_ok=True)
    _cache_path(key_url).write_text(json.dumps(record, indent=2))


# --- scrape (use-case) -----------------------------------------------------
def scrape(url: str, max_age_s: int = DEFAULT_MAX_AGE_S, main_only: bool = True) -> dict:
    """Fetch + extract one URL to a markdown record, using the cache."""
    if not allowed(url):
        raise FetchError(f"blocked by robots.txt: {url}")
    cached = _cache_load(url)
    if cached and (now_epoch() - cached.get("fetched_epoch", 0)) < max_age_s:
        cached["from_cache"] = True
        return cached
    etag = cached.get("etag") if cached else None
    last_mod = cached.get("last_modified") if cached else None
    result = fetch(url, etag=etag, last_mod=last_mod)
    if result["status"] == 304 and cached:
        cached["fetched_epoch"] = now_epoch()
        cached["fetched_at"] = iso_now()
        cached["from_cache"] = True
        _cache_save(url, cached)
        return cached
    final_url = result.get("final_url", url)
    extracted = web_extract.extract(result["body"], base_url=final_url, main_only=main_only)
    record = {
        "url": final_url,  # the canonical post-redirect source, for accurate manifest grounding
        "title": extracted["title"],
        "markdown": extracted["markdown"],
        "links": extracted["links"],
        "fetched_at": iso_now(),
        "fetched_epoch": now_epoch(),
        "etag": result["headers"].get("ETag"),
        "last_modified": result["headers"].get("Last-Modified"),
        "from_cache": False,
    }
    _cache_save(url, record)  # cache key = requested url; record['url'] = final url
    return record


# --- map (use-case) --------------------------------------------------------
def _same_site(url: str, seed: str, subdomains: bool) -> bool:
    a, b = urlparse(url).netloc, urlparse(seed).netloc
    if a == b:
        return True
    return subdomains and a.endswith("." + ".".join(b.split(".")[-2:]))


def _sitemap_urls(origin: str) -> list[str]:
    """Collect <loc> entries from sitemap.xml, descending one index level."""
    out: list[str] = []
    try:
        body = fetch(f"{origin}/sitemap.xml")["body"]
        root = ET.fromstring(body)
    except (FetchError, ET.ParseError):
        return out
    tag = root.tag.split("}")[-1]
    locs = [e.text.strip() for e in root.iter() if e.tag.split("}")[-1] == "loc" and e.text]
    if tag == "sitemapindex":
        for child in locs[:MAX_INDEX_SITEMAPS]:
            try:
                sub = ET.fromstring(fetch(child)["body"])
                out += [e.text.strip() for e in sub.iter()
                        if e.tag.split("}")[-1] == "loc" and e.text]
            except (FetchError, ET.ParseError):
                continue
    else:
        out += locs
    return out


def site_map(seed: str, search: str | None, limit: int, subdomains: bool) -> list[str]:
    origin = f"{urlparse(seed).scheme}://{urlparse(seed).netloc}"
    urls = _sitemap_urls(origin)
    if not urls:  # no sitemap -> fall back to on-page links
        urls = scrape(seed, main_only=False)["links"]
    needle = search.lower() if search else None
    out, seen = [], set()
    for url in urls:
        if url in seen or not _same_site(url, seed, subdomains):
            continue
        if needle and needle not in url.lower():
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= limit:
            break
    return out


# --- crawl (use-case) ------------------------------------------------------
def crawl(seed: str, depth: int, limit: int, main_only: bool, subdomains: bool) -> list[dict]:
    """BFS from seed, same-site, robots-respecting, polite. Returns records."""
    queue: list[tuple[str, int]] = [(seed.split("#")[0], 0)]
    seen, records = {seed.split("#")[0]}, []
    while queue and len(records) < limit:
        url, level = queue.pop(0)
        if not allowed(url):
            continue
        try:
            record = scrape(url, main_only=main_only)
        except FetchError as exc:
            print(f"  skip {url}: {exc}", file=sys.stderr)
            continue
        records.append({k: record[k] for k in ("url", "title", "markdown")})
        if not record.get("from_cache"):
            time.sleep(host_delay(url))  # politeness between live fetches
        if level < depth:
            for link in record["links"]:
                link = link.split("#")[0]
                if link not in seen and _same_site(link, seed, subdomains):
                    seen.add(link)
                    queue.append((link, level + 1))
    return records


# --- output / CLI ----------------------------------------------------------
def _slug(url: str) -> str:
    path = urlparse(url).path.strip("/").replace("/", "-") or "index"
    return re.sub(r"[^a-zA-Z0-9._-]", "_", path)[:80]


def _emit(records: list[dict], out_dir: str | None) -> None:
    if not out_dir:
        print(json.dumps(records if len(records) != 1 else records[0], indent=2))
        return
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    index = []
    for rec in records:
        name = f"{_slug(rec['url'])}.md"
        body = f"# {rec.get('title') or rec['url']}\n\n<{rec['url']}>\n\n{rec['markdown']}"
        (dest / name).write_text(body)
        index.append({"url": rec["url"], "title": rec.get("title", ""), "file": name})
    (dest / "index.json").write_text(json.dumps(index, indent=2))
    print(f"wrote {len(records)} page(s) to {dest}/")


def cmd_scrape(args) -> int:
    rec = scrape(args.url, max_age_s=args.max_age, main_only=not args.full)
    _emit([rec], args.out)
    return 0


def cmd_map(args) -> int:
    urls = site_map(args.url, args.search, args.limit, args.subdomains)
    print(json.dumps(urls, indent=2))
    return 0


def cmd_crawl(args) -> int:
    recs = crawl(args.url, args.depth, args.limit, not args.full, args.subdomains)
    _emit(recs, args.out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="web_ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scrape", help="one URL -> main-content markdown")
    s.add_argument("url")
    s.add_argument("--full", action="store_true", help="whole page, not just main content")
    s.add_argument("--max-age", type=int, default=DEFAULT_MAX_AGE_S, dest="max_age")
    s.add_argument("--out", help="write .md to this dir instead of stdout JSON")
    s.set_defaults(func=cmd_scrape)

    m = sub.add_parser("map", help="discover same-site URLs (sitemap + links)")
    m.add_argument("url")
    m.add_argument("--search", help="substring filter on URLs")
    m.add_argument("--limit", type=int, default=200)
    m.add_argument("--subdomains", action="store_true")
    m.set_defaults(func=cmd_map)

    c = sub.add_parser("crawl", help="BFS scrape a site, bounded by depth+limit")
    c.add_argument("url")
    c.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    c.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    c.add_argument("--full", action="store_true")
    c.add_argument("--subdomains", action="store_true")
    c.add_argument("--out", help="write .md files to this dir")
    c.set_defaults(func=cmd_crawl)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
