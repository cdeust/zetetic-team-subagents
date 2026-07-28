"""Contract tests for tools/web_extract.py.

Pure HTML to markdown: no I/O, no network, so every branch is reachable from a
string literal. It was at 0% coverage (issue #71) despite being the larger half
of the web-ingest pair and the one with all the parsing judgement in it.

What these tests pin:

1. **Forgiveness of the tree builder.** Real HTML is malformed. Unclosed tags,
   misnested tags, stray close tags and void elements each have a documented
   behaviour, and the builder must not raise or lose the document on any of
   them.
2. **The main-content heuristic.** `_score` combines text volume, link density
   and a class/id name signal, and `main_content` prefers a substantial
   semantic tag over a scored candidate. Those interactions decide what a
   reader actually gets, so each input to the score is varied independently.
3. **Serialization, per block type.** One case per markdown construct, plus the
   inline-run flushing in `_render_children` that decides where paragraph
   breaks land.
4. **Link extraction.** Relative resolution, scheme filtering, deduplication
   and fragment stripping are four separate rules applied in one pass.

`web_extract.py` is importable under a dotted path, so it is imported the way
tests/conftest.py sets up (`tools.web_extract`) rather than loaded by file
path: that is the import form mutmut matches trampoline hits against
(rules/coding-standards.md §12).
"""
from __future__ import annotations

import pytest

from tools import web_extract as wx


def _n(tag, **attrs):
    return wx.Node(tag, attrs or None)


def _text(s):
    node = wx.Node("#text")
    node.text = s
    return node


LONG = "word " * 60  # 300 chars, comfortably over MIN_CONTENT_CHARS


# ── Node ─────────────────────────────────────────────────────────────────────

def test_node_add_sets_the_parent_backlink():
    parent, child = _n("div"), _n("p")
    parent.add(child)
    assert parent.children == [child]
    assert child.parent is parent


def test_node_defaults_to_empty_attrs_and_no_text():
    node = wx.Node("div")
    assert node.attrs == {} and node.text == "" and node.parent is None


# ── _TreeBuilder: forgiveness ────────────────────────────────────────────────

def test_parse_builds_a_nested_tree():
    root = wx.parse_html("<div><p>hello</p></div>")
    div = root.children[0]
    assert div.tag == "div"
    assert div.children[0].tag == "p"
    assert div.children[0].children[0].text == "hello"


def test_parse_tolerates_unclosed_tags():
    root = wx.parse_html("<div><p>one<p>two")
    assert wx._text_of(root).strip().replace("\n", "") != ""


def test_parse_tolerates_a_stray_end_tag():
    """An end tag with no matching open must be ignored, not pop the stack."""
    root = wx.parse_html("</span><p>kept</p>")
    assert "kept" in wx._text_of(root)


def test_parse_closes_the_nearest_matching_open_tag_when_misnested():
    root = wx.parse_html("<div><b><i>x</b></i></div>")
    assert "x" in wx._text_of(root)


def test_void_tags_never_receive_children():
    root = wx.parse_html("<p>before<br>after</p>")
    para = root.children[0]
    br = [c for c in para.children if c.tag == "br"][0]
    assert br.children == []
    assert "after" in wx._text_of(para)


def test_end_tag_for_a_void_element_is_ignored():
    root = wx.parse_html("<p>a<br></br>b</p>")
    assert "b" in wx._text_of(root)


def test_self_closing_tag_is_added_without_opening_a_scope():
    root = wx.parse_html("<div><img src='x.png'/><p>after</p></div>")
    div = root.children[0]
    assert [c.tag for c in div.children] == ["img", "p"]


def test_whitespace_only_text_is_dropped():
    """Whitespace between tags is not content and must not become a leaf."""
    root = wx.parse_html("<div>   \n\t  <p>x</p></div>")
    assert [c.tag for c in root.children[0].children] == ["p"]


def test_character_references_are_converted():
    root = wx.parse_html("<p>a &amp; b</p>")
    assert "a & b" in wx._text_of(root)


# ── measurement helpers ──────────────────────────────────────────────────────

def test_text_len_sums_descendant_text_stripped():
    root = wx.parse_html("<div><p>  abc  </p><p>de</p></div>")
    assert wx._text_len(root) == 5


def test_link_text_len_counts_only_anchor_text():
    root = wx.parse_html("<div>plain<a href='/x'>link</a></div>")
    assert wx._link_text_len(root) == 4


def test_link_text_len_of_a_document_with_no_anchors_is_zero():
    assert wx._link_text_len(wx.parse_html("<p>none</p>")) == 0


def test_strip_boilerplate_removes_every_boilerplate_tag():
    html = "<body><nav>n</nav><script>s</script><p>keep</p><footer>f</footer></body>"
    root = wx.parse_html(html)
    wx._strip_boilerplate(root)
    text = wx._text_of(root)
    assert "keep" in text
    for gone in ("n", "s", "f"):
        assert gone not in text


def test_strip_boilerplate_recurses_into_survivors():
    root = wx.parse_html("<div><section><nav>gone</nav><p>keep</p></section></div>")
    wx._strip_boilerplate(root)
    assert "gone" not in wx._text_of(root)


def test_candidates_collects_container_tags_only():
    root = wx.parse_html("<body><div><p>x</p><article>y</article></div></body>")
    out = []
    wx._candidates(root, out)
    assert {n.tag for n in out} == {"body", "div", "article"}


# ── the scoring heuristic ────────────────────────────────────────────────────

def test_name_weight_penalises_negative_class_names():
    assert wx._name_weight(_n("div", **{"class": "sidebar"})) == 0.2


def test_name_weight_boosts_positive_class_names():
    assert wx._name_weight(_n("div", **{"class": "article-body"})) == 1.5


def test_name_weight_is_neutral_for_an_unnamed_node():
    assert wx._name_weight(_n("div")) == 1.0


def test_name_weight_checks_the_id_as_well_as_the_class():
    assert wx._name_weight(_n("div", id="footer")) == 0.2


def test_name_weight_lets_a_negative_name_win_over_a_positive_one():
    """Order matters: chrome named 'content-sidebar' is still chrome."""
    assert wx._name_weight(_n("div", **{"class": "content sidebar"})) == 0.2


def test_score_rejects_a_block_below_the_minimum_length():
    root = wx.parse_html("<div>tiny</div>")
    assert wx._score(root.children[0]) == -1.0


def test_score_grows_with_text_volume():
    small = wx.parse_html(f"<div>{'a ' * 150}</div>").children[0]
    large = wx.parse_html(f"<div>{'a ' * 400}</div>").children[0]
    assert wx._score(large) > wx._score(small)


def test_score_penalises_high_link_density():
    prose = wx.parse_html(f"<div>{LONG}</div>").children[0]
    linky = wx.parse_html(f"<div><a href='/x'>{LONG}</a></div>").children[0]
    assert wx._score(linky) < wx._score(prose)


# ── main_content ─────────────────────────────────────────────────────────────

def test_main_content_prefers_a_substantial_semantic_tag():
    html = f"<body><div class='promo'>{LONG}</div><article>{LONG}</article></body>"
    assert wx.main_content(wx.parse_html(html)).tag == "article"


def test_main_content_ignores_a_semantic_tag_that_is_too_short():
    """A one-line <main> is a wrapper, not the article; scoring takes over."""
    html = f"<body><main>hi</main><div class='post'>{LONG}</div></body>"
    picked = wx.main_content(wx.parse_html(html))
    assert picked.attrs.get("class") == "post"


def test_main_content_falls_back_to_root_when_nothing_scores():
    root = wx.parse_html("<body><div>too short</div></body>")
    assert wx.main_content(root) is root


def test_main_content_strips_boilerplate_before_choosing():
    html = f"<body><nav>{LONG}</nav><div class='post'>{LONG}</div></body>"
    picked = wx.main_content(wx.parse_html(html))
    assert "nav" not in [c.tag for c in picked.children]


# ── inline rendering ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "html,expected",
    [
        ("<a href='/x'>text</a>", "[text](/x)"),
        ("<strong>s</strong>", "**s**"),
        ("<b>s</b>", "**s**"),
        ("<em>e</em>", "*e*"),
        ("<i>e</i>", "*e*"),
        ("<code>c</code>", "`c`"),
        ("<img src='i.png' alt='alt text'>", "![alt text](i.png)"),
        ("<span>plain</span>", "plain"),
    ],
)
def test_render_inline_constructs(html, expected):
    node = wx.parse_html(html).children[0]
    assert wx._render_inline(node) == expected


def test_render_inline_br_becomes_a_hard_line_break():
    assert wx._render_inline(_n("br")) == "  \n"


def test_render_inline_flattens_newlines_in_text():
    assert wx._render_inline(_text("a\nb")) == "a b"


def test_anchor_without_href_renders_as_plain_text():
    node = wx.parse_html("<a>bare</a>").children[0]
    assert wx._render_inline(node) == "bare"


def test_img_without_attributes_renders_empty_alt_and_src():
    assert wx._render_inline(_n("img")) == "![]()"


# ── block rendering ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("level", [1, 2, 3, 4, 5, 6])
def test_headings_render_at_the_right_depth(level):
    node = wx.parse_html(f"<h{level}>T</h{level}>").children[0]
    assert wx._render_block(node) == "#" * level + " T\n\n"


def test_paragraph_renders_with_a_blank_line_after():
    node = wx.parse_html("<p>para</p>").children[0]
    assert wx._render_block(node) == "para\n\n"


def test_unordered_list_uses_dashes():
    node = wx.parse_html("<ul><li>a</li><li>b</li></ul>").children[0]
    assert wx._render_block(node) == "- a\n- b\n\n"


def test_ordered_list_numbers_from_one():
    node = wx.parse_html("<ol><li>a</li><li>b</li></ol>").children[0]
    assert wx._render_block(node) == "1. a\n2. b\n\n"


def test_list_ignores_non_li_children():
    node = wx.parse_html("<ul><li>a</li><div>x</div></ul>").children[0]
    assert wx._render_block(node) == "- a\n\n"


def test_blockquote_prefixes_every_line():
    node = wx.parse_html("<blockquote><p>a</p><p>b</p></blockquote>").children[0]
    assert wx._render_block(node).startswith("> a")
    assert "\n> " in wx._render_block(node)


def test_pre_renders_a_fenced_block_preserving_inner_text():
    node = wx.parse_html("<pre>line1\nline2</pre>").children[0]
    assert wx._render_block(node) == "```\nline1\nline2\n```\n\n"


def test_hr_renders_a_rule():
    assert wx._render_block(_n("hr")) == "---\n\n"


def test_unknown_block_renders_its_children():
    node = wx.parse_html("<figure><p>caption</p></figure>").children[0]
    assert wx._render_block(node) == "caption\n\n"


def test_render_children_flushes_an_inline_run_before_a_block():
    """The rule that decides where a paragraph break lands."""
    node = wx.parse_html("<div>lead text<p>para</p></div>").children[0]
    assert wx._render_children(node) == "lead text\n\npara\n\n"


def test_render_children_flushes_a_trailing_inline_run():
    node = wx.parse_html("<div><p>para</p>trailing</div>").children[0]
    assert wx._render_children(node).endswith("trailing\n\n")


def test_text_of_concatenates_without_stripping():
    node = wx.parse_html("<p>a <b>b</b></p>").children[0]
    assert wx._text_of(node) == "a b"


# ── title extraction ─────────────────────────────────────────────────────────

def test_extract_title_prefers_the_title_element():
    root = wx.parse_html("<html><head><title>Doc</title></head><h1>Other</h1></html>")
    assert wx.extract_title(root) == "Doc"


def test_extract_title_falls_back_to_the_first_h1():
    assert wx.extract_title(wx.parse_html("<body><h1>Head</h1></body>")) == "Head"


def test_extract_title_returns_empty_when_there_is_neither():
    assert wx.extract_title(wx.parse_html("<p>x</p>")) == ""


def test_extract_title_renders_inline_markup_in_an_h1_fallback():
    assert wx.extract_title(wx.parse_html("<h1>a <em>b</em></h1>")) == "a *b*"


# ── link extraction ──────────────────────────────────────────────────────────

def test_extract_links_resolves_relative_urls_against_the_base():
    root = wx.parse_html("<a href='/sub/page'>x</a>")
    assert wx.extract_links(root, "https://ex.test/dir/") == ["https://ex.test/sub/page"]


def test_extract_links_drops_non_http_schemes():
    """mailto:, javascript: and data: are not pages to follow."""
    html = "<a href='mailto:a@b.test'>m</a><a href='javascript:void(0)'>j</a>"
    assert wx.extract_links(wx.parse_html(html), "https://ex.test/") == []


def test_extract_links_deduplicates():
    html = "<a href='/a'>1</a><a href='/a'>2</a>"
    assert wx.extract_links(wx.parse_html(html), "https://ex.test/") == [
        "https://ex.test/a"
    ]


def test_extract_links_strips_fragments():
    root = wx.parse_html("<a href='/a#section'>x</a>")
    assert wx.extract_links(root, "https://ex.test/") == ["https://ex.test/a"]


def test_extract_links_ignores_anchors_without_href():
    assert wx.extract_links(wx.parse_html("<a>x</a>"), "https://ex.test/") == []


def test_extract_links_trims_surrounding_whitespace_in_href():
    root = wx.parse_html("<a href='  /a  '>x</a>")
    assert wx.extract_links(root, "https://ex.test/") == ["https://ex.test/a"]


# ── whitespace collapsing ────────────────────────────────────────────────────

def test_collapse_blanks_reduces_runs_to_a_single_blank_line():
    assert wx._collapse_blanks("a\n\n\n\nb") == "a\n\nb\n"


def test_collapse_blanks_strips_trailing_whitespace_per_line():
    assert wx._collapse_blanks("a   \nb") == "a\nb\n"


def test_collapse_blanks_always_ends_with_exactly_one_newline():
    assert wx._collapse_blanks("\n\na\n\n\n") == "a\n"


# ── extract: the public entry point ──────────────────────────────────────────

def test_extract_returns_title_markdown_and_links():
    html = f"""
    <html><head><title>T</title></head>
      <body><nav><a href='/nav'>skip</a></nav>
        <article><h1>Head</h1><p>{LONG}</p><a href='/link'>l</a></article>
      </body></html>
    """
    out = wx.extract(html, base_url="https://ex.test/")
    assert out["title"] == "T"
    assert "# Head" in out["markdown"]
    assert "https://ex.test/link" in out["links"]


def test_extract_collects_links_from_the_whole_document_not_just_main():
    """Links are extracted before main-content selection, so nav links appear."""
    html = f"<body><nav><a href='/nav'>n</a></nav><article>{LONG}</article></body>"
    assert "https://ex.test/nav" in wx.extract(html, "https://ex.test/")["links"]


def test_extract_returns_no_links_without_a_base_url():
    """Negative assertion: link resolution is opt-in via base_url."""
    assert wx.extract("<a href='/a'>x</a>")["links"] == []


def test_extract_main_only_false_keeps_the_whole_document():
    html = f"<body><div class='promo'>PROMO TEXT</div><article>{LONG}</article></body>"
    whole = wx.extract(html, main_only=False)["markdown"]
    assert "PROMO TEXT" in whole


def test_extract_main_only_true_drops_chrome():
    html = f"<body><nav>NAVTEXT</nav><article>{LONG}</article></body>"
    assert "NAVTEXT" not in wx.extract(html, main_only=True)["markdown"]


def test_extract_of_an_empty_document_does_not_raise():
    out = wx.extract("")
    assert out["title"] == "" and out["links"] == []
