"""Security and preservation contracts for the public remote-content cleaners."""

from urllib.parse import urlparse
from xml.etree.ElementTree import canonicalize, tostring

import html5lib
import pytest

from indieweb.sanitizers import sanitize_remote_webmention_url, sanitize_webmention_html

ADVERSARIAL_HTML = [
    '<a href="JaVaScRiPt:alert(1)" onclick="alert(2)">mixed case</a>',
    '<a href="jav&#x61;script&#58;alert(1)">entity scheme</a>',
    '<a href="java&#9;script:alert(1)">tab</a><a href="java&#10;script:alert(1)">newline</a>',
    '<a href="data:text/html,evil">data</a><a href="vbscript:evil">vb</a>',
    '<a href="https://safe.example/" title="broken" onmouseover="evil">quotes</a>',
    '<svg><a xlink:href="javascript:evil">foreign</a></svg><p>after</p>',
    "<math><mtext><table><mglyph><style><!--</style><img src=x onerror=evil>math",
    "<!--><img src=x onerror=evil><!-- comment --><p>text</p>",
    '<script>alert(1)</script><style>body{display:none}</style><iframe srcdoc="evil"></iframe>',
    '<template><a href="javascript:evil">hidden</a></template><form><input autofocus onfocus=evil></form>',
    '<blockquote cite="//evil.example/path"><q cite="/admin">relative</q></blockquote>',
    '<a href="https://trusted.example@evil.example/">userinfo</a>',
    '<a href="https://[broken/private">bad IPv6</a><a href="https://safe.example:bad/">port</a>',
    '<a href="/admin">local</a><a href="//evil.example/">authority</a><a href="#fragment">fragment</a>',
]

ALLOWED_TAGS = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "cite",
    "code",
    "del",
    "em",
    "i",
    "li",
    "ol",
    "p",
    "pre",
    "q",
    "s",
    "span",
    "strong",
    "ul",
}
ALLOWED_ATTRIBUTES = {"a": {"href", "title", "rel"}, "abbr": {"title"}, "blockquote": {"cite"}, "q": {"cite"}}


def fragment(html):
    # HTML5 fragment interpretation catches malformed/foreign-content reparsing.
    return html5lib.parseFragment(html, container="div", namespaceHTMLElements=False)


def semantics(tree):
    return canonicalize(tostring(tree, encoding="unicode"), with_comments=True)


def assert_safe(html):
    root = fragment(html)
    for tag in root.iter():
        if tag is root:
            continue
        # Comment nodes have a non-string tag, and fail the allowlist too.
        assert tag.tag in ALLOWED_TAGS
        assert set(tag.attrib) <= ALLOWED_ATTRIBUTES.get(tag.tag, set())
        for attribute in ("href", "cite"):
            if attribute in tag.attrib:
                url = tag.attrib[attribute]
                parsed = urlparse(url)
                assert parsed.scheme.lower() in {"http", "https"}
                assert parsed.netloc and parsed.username is None and parsed.password is None
                assert sanitize_remote_webmention_url(url) == url
        if tag.tag == "a":
            assert set(tag.attrib["rel"].split()) == {"nofollow", "noopener", "ugc"}


@pytest.mark.parametrize("html", ADVERSARIAL_HTML)
def test_adversarial_html_remains_safe_after_repeated_cleaning(html):
    cleaned = sanitize_webmention_html(html)
    assert_safe(cleaned)
    twice = sanitize_webmention_html(cleaned)
    assert_safe(twice)
    assert semantics(fragment(twice)) == semantics(fragment(cleaned))


SAFE_HTML = """<p>Grüße &amp; café 雪 <abbr title="World Wide Web">WWW</abbr><br>
<strong>bold <em>emphasis</em></strong> <b>B</b><i>I</i><s>S</s><del>D</del><span>span</span></p>
<ul><li>one<ol><li>nested</li></ol></li><li>two</li></ul>
<blockquote cite="https://citation.example/source"><p>quote <cite>citation</cite></p>
<q cite="http://citation.example/other">inline</q></blockquote>
<pre>  α &lt; β\n    <code>x &amp; y</code>\n</pre>
<a href="https://links.example/path?q=1&amp;b=2#part" title="A &amp; B">link</a>"""


def test_safe_content_preserves_text_structure_attributes_and_link_rel():
    cleaned = sanitize_webmention_html(SAFE_HTML)
    expected = fragment(SAFE_HTML)
    expected.find("a").set("rel", "nofollow noopener ugc")
    assert semantics(fragment(cleaned)) == semantics(expected)
    assert "".join(fragment(cleaned).find("pre").itertext()) == "  α < β\n    x & y\n"
    assert_safe(cleaned)
    assert semantics(fragment(sanitize_webmention_html(cleaned))) == semantics(expected)


@pytest.mark.parametrize("value", [None, ""])
def test_empty_html_is_empty(value):
    assert sanitize_webmention_html(value) == ""


@pytest.mark.parametrize(
    "value", ["https://safe.example/path?q=雪&b=2#cite", "http://safe.example:8080/", "https://[::1]/"]
)
def test_safe_remote_urls_preserve_identity(value):
    assert sanitize_remote_webmention_url(value) == value
    assert sanitize_remote_webmention_url(f"  {value}\n") == value
    assert sanitize_remote_webmention_url(sanitize_remote_webmention_url(value)) == value


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        " \n",
        "/local",
        "//safe.example/",
        "javascript:evil",
        "data:text/html,evil",
        "https://trusted.example@evil.example/",
        "https://user:pass@safe.example/",
        "https://[broken/",
        "https://safe.example:bad/",
        "https://safe.example:99999/",
        "https://",
        "https://bad host/",
    ],
)
def test_unsafe_remote_urls_are_blank(value):
    assert sanitize_remote_webmention_url(value) == ""


@pytest.mark.parametrize(
    "html,expected",
    [
        ("<svg><script>evil</script></svg><p>after</p>", "<p>after</p>"),
        ("<!-- comment --><script>evil</script><p>Grüße &amp; 雪</p>", "<p>Grüße &amp; 雪</p>"),
        (
            '<a href=https://safe.example/ title="broken><img src=x onerror=evil>">quotes</a>',
            '<a href="https://safe.example/" title="broken&gt;&lt;img src=x onerror=evil&gt;" '
            'rel="nofollow noopener ugc">quotes</a>',
        ),
    ],
)
def test_safe_content_survives_hostile_siblings_and_malformed_quotes(html, expected):
    cleaned = sanitize_webmention_html(html)
    assert_safe(cleaned)
    assert semantics(fragment(cleaned)) == semantics(fragment(expected))
    assert semantics(fragment(sanitize_webmention_html(cleaned))) == semantics(fragment(expected))
