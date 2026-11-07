"""Read the actual copyable RST examples for executable documentation tests."""

import re
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


def doc_block(page, marker):
    text = (ROOT / "docs" / page).read_text()
    blocks = re.findall(r"^([ ]*)\.\. code(?:-block)?:: \w+\n\n((?:(?: +[^\n]*|)\n)+)", text, re.M)
    return next(dedent(body) for _, body in blocks if marker in body)
