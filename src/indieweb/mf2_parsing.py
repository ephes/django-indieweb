"""Bounded microformats2 parsing for fetched, untrusted HTML.

The fetch size limit only bounds the input. Two things can still make a small
document expensive, and both are bounded here before ``mf2py`` runs:

* ``mf2py`` returns the markup and text of every property element, so nested
  property elements repeat their shared content once per level. The expected
  size of the parse result is estimated on the DOM first.
* Building the DOM itself must stay linear in the input, and ``mf2py`` walks it
  recursively, so the tree is built with Python's own HTML parser and its
  nesting depth is limited.
"""

from __future__ import annotations

import logging
from typing import Any

import mf2py
from bs4 import BeautifulSoup
from bs4.element import NavigableString, PageElement, Tag
from django.conf import settings
from mf2py import backcompat, mf2_classes

logger = logging.getLogger(__name__)

DEFAULT_MF2_MAX_EXPANSION_BYTES = 4 * 1024 * 1024
# Elements nested deeper than this are not parsed for microformats.
MF2_MAX_NESTING_DEPTH = 200


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


def _class_tokens(tag: Tag) -> list[str]:
    classes = tag.get("class")
    if isinstance(classes, str):
        return classes.split()
    return [str(token) for token in classes or []]


def _copies(tokens: list[str], *, in_classic_root: bool) -> int:
    """Return how often ``mf2py`` may repeat an element's content in its result."""
    if in_classic_root:
        # Classic microformats map plain class names to properties. Which ones
        # is up to the parser's rules, so every class token counts as embedded
        # markup (returned as HTML and as text).
        return 2 * len(tokens)
    found = mf2_classes.filter_classes(tokens)
    return 2 * len(found["e"]) + len(found["p"]) + len(found["u"]) + len(found["dt"]) + (1 if found["h"] else 0)


def _own_size(node: PageElement) -> int:
    if isinstance(node, Tag):
        size = 2 * len(node.name) + 5
        for name, value in node.attrs.items():
            value_size = sum(len(str(part)) + 1 for part in value) if isinstance(value, list) else len(str(value))
            size += len(name) + value_size + 4
        return size
    return len(str(node)) if isinstance(node, NavigableString) else 0


def within_parse_limits(soup: BeautifulSoup, max_bytes: int) -> bool:
    """Return whether ``soup`` is safe to hand to ``mf2py``.

    Checks the nesting depth (``mf2py`` recurses over the tree) and the
    estimated size of the parse result: every node's own size, once per
    enclosing property element copy. One iterative pass; stops at a limit.
    """
    estimate = 0
    stack: list[tuple[PageElement, int, int, bool]] = [(soup, 0, 0, False)]
    while stack:
        node, depth, copies, in_classic_root = stack.pop()
        if isinstance(node, Tag):
            if depth > MF2_MAX_NESTING_DEPTH:
                return False
            tokens = _class_tokens(node)
            if tokens:
                in_classic_root = in_classic_root or bool(backcompat.root(tokens))
                copies += _copies(tokens, in_classic_root=in_classic_root)
            if node.get("rel") is not None:
                # Link relations are returned with the link's text.
                copies += 1
            stack.extend((child, depth + 1, copies, in_classic_root) for child in node.contents)
        if copies:
            estimate += copies * _own_size(node)
            if estimate > max_bytes:
                return False
    return True


def parse_microformats(html: str, url: str) -> dict[str, Any]:
    """Parse microformats2 from untrusted ``html``.

    Returns an empty result when the document is nested too deeply or its
    properties would expand beyond ``INDIEWEB_MF2_MAX_EXPANSION_BYTES``.
    """
    # Python's own parser builds the tree in time and memory linear in the
    # input. mf2py's default html5lib builder follows the HTML5 error-recovery
    # rules, which re-create open formatting elements and can turn a small
    # hostile document into millions of nodes.
    soup = BeautifulSoup(html, features="html.parser")
    if not within_parse_limits(soup, mf2_max_expansion_bytes()):
        logger.warning("Not parsing microformats: document exceeds the nesting or expansion limit")
        return empty_parse_result()
    try:
        parsed: dict[str, Any] = mf2py.parse(doc=soup, url=url)
    except RecursionError:  # pragma: no cover - the depth limit is meant to prevent this
        logger.warning("Not parsing microformats: document is nested too deeply")
        return empty_parse_result()
    return parsed
