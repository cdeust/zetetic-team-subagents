"""se_dump_reader.py — stream Stack Exchange `Posts.xml` (one site's dump file).

Format: SE data dump `Posts.xml`, one `<row .../>` element per post, attributes
include `Id`, `PostTypeId` ("1" = Question), `Score`, `Tags` (e.g.
"<architecture><team>"), `Body` (HTML). Reference: SE data dump documentation,
schema unchanged since the 2018 CC BY-SA 4.0 ToS update (EXTERNAL-TESTBASE.md §1).

Streams with `iterparse` and clears each element after reading it, rather than
loading the whole tree: a site's Posts.xml can run into hundreds of MB even for
one niche site, and this reader must not hold an unbounded number of full post
bodies in memory (task constraint: corpus paths are CLI arguments, the dump is
never bulk-downloaded or bulk-loaded by this tool).

`tag_allowlist`, when given, is applied WHILE streaming (not after collecting
everything) — the same filter stratified_sampler.py would apply next, but
duplicated here as a memory bound, not a shape decision: passing no allowlist
(tests, small fixtures) still returns every question.

precondition: `path` is a Posts.xml file (or a small format-compatible fixture in
    tests) already present on disk; the caller supplies the site name and license
    (this reader has no way to derive them from the XML itself).
postcondition: returns every Question-type row (PostTypeId == "1") that matches
    `tag_allowlist` (or every question, if no allowlist given); every other row
    is counted under a named drop reason, never silently discarded uncounted.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from tools.goa.raw_record import NormalizedRecord

QUESTION_POST_TYPE = "1"
_TAG_RE = re.compile(r"<([^<>]+)>")


def parse_tags(tags_attr: str | None) -> tuple[str, ...]:
    """SE stores tags as '<tag1><tag2>' in the Tags attribute; split them out."""
    if not tags_attr:
        return ()
    return tuple(_TAG_RE.findall(tags_attr))


def _record_from_row(elem: ET.Element, site: str, license_str: str) -> NormalizedRecord | None:
    post_id = elem.get("Id")
    body = elem.get("Body")
    if not post_id or not body:
        return None
    score_attr = elem.get("Score")
    return NormalizedRecord(
        corpus="stackexchange",
        source_id=post_id,
        text=body,
        site_or_dataset=site,
        license=license_str,
        tags=parse_tags(elem.get("Tags")),
        score=int(score_attr) if score_attr is not None else None,
    )


def read_posts(
    path: Path,
    site: str,
    license_str: str,
    tag_allowlist: tuple[str, ...] = (),
) -> tuple[list[NormalizedRecord], Counter]:
    """Parse `path`, returning (matching records, drop-reason tally)."""
    drops: Counter = Counter()
    records: list[NormalizedRecord] = []
    for _, elem in ET.iterparse(str(path), events=("end",)):
        if elem.tag != "row":
            continue
        if elem.get("PostTypeId") != QUESTION_POST_TYPE:
            drops["not-a-question"] += 1
            elem.clear()
            continue
        record = _record_from_row(elem, site, license_str)
        elem.clear()
        if record is None:
            drops["missing-id-or-body"] += 1
            continue
        if tag_allowlist and not (set(record.tags) & set(tag_allowlist)):
            drops["tag-not-in-allowlist"] += 1
            continue
        records.append(record)
    return records, drops
