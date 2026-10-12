"""Bounded microformats2 parsing for fetched, untrusted HTML.

The fetch size limit only bounds the input. A small document can still be
expensive to parse, so three things are bounded here before ``mf2py`` runs:

* ``mf2py`` returns the markup and text of every property element, parses the
  subtree of a nested microformat once per property class, and resolves every
  URL against the document's base URL. Nested property elements therefore
  repeat or multiply their content. An upper bound of the parse result size is
  computed on the DOM first.
* Building the DOM must stay linear in the input, so the tree is built with
  Python's own HTML parser. ``mf2py``'s default ``html5lib`` builder follows
  the HTML5 error-recovery rules, which re-create open formatting elements and
  can turn a small hostile document into millions of nodes.
* ``mf2py`` walks the tree recursively, so its nesting depth is limited.

The estimate is a model of a third-party parser, so the actual result is
measured as well and discarded when it is over the limit.
"""

from __future__ import annotations

import functools
import json
import logging
from collections.abc import Iterable
from typing import Any

import mf2py
from bs4 import BeautifulSoup
from bs4.element import NavigableString, PageElement, Tag
from django.conf import settings
from mf2py import backcompat, mf2_classes

logger = logging.getLogger(__name__)

DEFAULT_MF2_MAX_EXPANSION_BYTES = 8 * 1024 * 1024
# Elements nested deeper than this are not parsed for microformats.
MF2_MAX_NESTING_DEPTH = 200
# Attributes whose values mf2py resolves against the base URL.
URL_ATTRIBUTES = frozenset({"href", "src", "srcset", "cite", "data", "poster", "title", "value"})
# Allowance for the structure (keys, type list, language) of one parsed property or item.
PROPERTY_OVERHEAD_BYTES = 128
# Allowance for the fixed parts of a parse result (debug information, empty containers).
RESULT_OVERHEAD_BYTES = 1024


def mf2_max_expansion_bytes() -> int:
    """Return the configured expansion bound, falling back to the default when invalid."""
    configured = getattr(settings, "INDIEWEB_MF2_MAX_EXPANSION_BYTES", DEFAULT_MF2_MAX_EXPANSION_BYTES)
    if isinstance(configured, bool) or not isinstance(configured, int) or configured <= 0:
        logger.warning(
            "Ignoring invalid INDIEWEB_MF2_MAX_EXPANSION_BYTES value; using default %s",
            DEFAULT_MF2_MAX_EXPANSION_BYTES,
        )
        return DEFAULT_MF2_MAX_EXPANSION_BYTES
    return configured


def empty_parse_result() -> dict[str, Any]:
    """Return the shape ``mf2py`` produces for a document without microformats."""
    return {"items": [], "rels": {}, "rel-urls": {}}


def _tokens(tag: Tag, attribute: str) -> list[str]:
    value = tag.get(attribute)
    if isinstance(value, str):
        return value.split()
    return [str(token) for token in value or []]


@functools.cache
def _classic_rules() -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]] | None:
    """Return the mf2 classes mf2py adds for classic class names and link relations.

    Read from mf2py's own rule table. ``None`` when that table is not available
    in the expected shape; callers then assume the worst for every token.
    """
    table = getattr(backcompat, "_CLASSIC_MAP", None)
    if not isinstance(table, dict) or not table:
        return None
    classes: dict[str, set[str]] = {}
    rels: dict[str, set[str]] = {}
    try:
        for root, rules in table.items():
            classes.setdefault(root, set()).update(rules["type"])
            for old_names, new_classes in rules.get("properties", {}).items():
                for old_name in old_names.split():
                    classes.setdefault(old_name, set()).update(new_classes)
            for old_rels, new_classes in rules.get("rels", {}).items():
                for old_rel in old_rels.split():
                    rels.setdefault(old_rel, set()).update(new_classes)
    except (AttributeError, KeyError, TypeError):
        return None
    return (
        {name: frozenset(mapped) for name, mapped in classes.items()},
        {name: frozenset(mapped) for name, mapped in rels.items()},
    )


def _mf2_copies(class_tokens: Iterable[str]) -> int:
    found = mf2_classes.filter_classes(class_tokens)
    return 2 * len(found["e"]) + len(found["p"]) + len(found["u"]) + len(found["dt"]) + (1 if found["h"] else 0)


def _property_copies(class_tokens: list[str], rel_tokens: list[str], *, in_classic_root: bool) -> int:
    """Return how many copies of an element's content its classes can add to the result."""
    if not in_classic_root:
        return _mf2_copies(class_tokens)
    # Inside a classic microformat mf2py maps plain class names and link
    # relations to mf2 classes, some of them to a nested microformat as well.
    rules = _classic_rules()
    if rules is None:
        # Unknown rules: every token counts as embedded markup (HTML and text)
        # for up to three properties.
        return 6 * (len(class_tokens) + len(rel_tokens))
    classic_classes, classic_rels = rules
    effective = set(class_tokens)
    for token in class_tokens:
        effective.update(classic_classes.get(token, ()))
    for token in rel_tokens:
        effective.update(classic_rels.get(token, ()))
    return _mf2_copies(effective)


def _document_lengths(soup: BeautifulSoup, url: str) -> tuple[int, int]:
    """Return upper bounds for the base URL length and the language tag length mf2py repeats."""
    longest_base = 0
    longest_lang = 0
    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):  # pragma: no cover - find_all(True) yields tags
            continue
        lang = tag.get("lang")
        if isinstance(lang, str):
            longest_lang = max(longest_lang, len(lang))
        if tag.name == "base":
            href = tag.get("href")
            if isinstance(href, str):
                longest_base = max(longest_base, len(href))
    return len(url) + longest_base, longest_lang


def _own_size(node: PageElement, base_length: int) -> int:
    """Return an upper bound for the output one copy of ``node`` itself contributes."""
    if not isinstance(node, Tag):
        return len(str(node)) if isinstance(node, NavigableString) else 0
    size = 2 * len(node.name) + 5
    for name, value in node.attrs.items():
        value_size = sum(len(str(part)) + 1 for part in value) if isinstance(value, list) else len(str(value))
        size += len(name) + value_size + 4
        if name in URL_ATTRIBUTES:
            # srcset holds several candidates, separated by commas or just
            # whitespace; each one is resolved. No value has more candidates
            # than separators plus one.
            text = str(value)
            size += base_length * (1 + text.count(",") + len(text.split()))
    return size


def within_parse_limits(soup: BeautifulSoup, url: str, max_bytes: int) -> bool:
    """Return whether ``soup`` is safe to hand to ``mf2py``.

    Checks the nesting depth and an upper bound of the parse result size. A
    node's content can appear once per copy that each enclosing property
    element makes, and a nested microformat is parsed again for each of its
    property classes, so a node counts ``product(1 + copies)`` times over its
    ancestors. One iterative pass; stops at a limit.
    """
    base_length, lang_length = _document_lengths(soup, url)
    estimate = RESULT_OVERHEAD_BYTES
    stack: list[tuple[PageElement, int, int, bool]] = [(soup, 0, 1, False)]
    while stack:
        node, depth, multiplier, in_classic_root = stack.pop()
        own_size = _own_size(node, base_length)
        if isinstance(node, Tag):
            if depth > MF2_MAX_NESTING_DEPTH:
                return False
            class_tokens = _tokens(node, "class")
            rel_tokens = _tokens(node, "rel")
            in_classic_root = in_classic_root or bool(backcompat.root(class_tokens))
            copies = _property_copies(class_tokens, rel_tokens, in_classic_root=in_classic_root)
            if copies:
                multiplier *= 1 + copies
                # u-* values and implied URLs are resolved against the base URL;
                # embedded values and items carry the language.
                own_size += copies * (PROPERTY_OVERHEAD_BYTES + base_length + lang_length)
            if rel_tokens:
                # Each relation lists the resolved link, which is also returned with its text.
                link_size = len(str(node.get("href") or "")) + base_length + PROPERTY_OVERHEAD_BYTES
                estimate += len(rel_tokens) * link_size + 2 * sum(len(token) for token in rel_tokens)
                multiplier += 1
            if multiplier > max_bytes:
                return False
            stack.extend((child, depth + 1, multiplier, in_classic_root) for child in node.contents)
        if multiplier > 1:
            estimate += multiplier * own_size
        if estimate > max_bytes:
            return False
    return True


def parse_microformats(html: str, url: str) -> dict[str, Any] | None:
    """Parse microformats2 from untrusted ``html``.

    Returns ``None`` when the document is nested too deeply or its parse result
    would exceed ``INDIEWEB_MF2_MAX_EXPANSION_BYTES``.
    """
    max_bytes = mf2_max_expansion_bytes()
    soup = BeautifulSoup(html, features="html.parser")
    if not within_parse_limits(soup, url, max_bytes):
        logger.warning("Not parsing microformats: document exceeds the nesting or expansion limit")
        return None
    try:
        parsed: dict[str, Any] = mf2py.parse(doc=soup, url=url)
    except RecursionError:  # pragma: no cover - the depth limit is meant to prevent this
        logger.warning("Not parsing microformats: document is nested too deeply")
        return None
    if len(json.dumps(parsed, default=str)) > max_bytes:
        logger.warning("Discarding microformats parse result over INDIEWEB_MF2_MAX_EXPANSION_BYTES")
        return None
    return parsed
