"""Helpers shared by audit.py and fix.py: user agent, curl wrapper, post-body slicing."""
from __future__ import annotations

import re
import subprocess
from typing import List

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"
VIEWPORT = {"width": 1280, "height": 900}


def sh(cmd: List[str]) -> str:
    """Run ``cmd`` and return its stdout as text (stderr and exit status are ignored)."""
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def fetch_html(url: str) -> str:
    """GET ``url`` with curl and a browser User-Agent; return the response body."""
    return sh(["curl", "-s", "-A", UA, url])


def body_of(html: str) -> str:
    """Return just the post body (the balanced ``<div class='post-body'>`` element).

    Blogger renders no post-footer on this theme, so walk balanced <div> tags
    from the opening post-body tag. Scoping matters: falling back to the whole
    page pulls the theme's own CSS in and every dark-mode rule fires falsely.
    Returns ``""`` when the page has no post body.
    """
    s = html.find("<div class='post-body'>")
    if s < 0:
        s = html.find('<div class="post-body"')
    if s < 0:
        return ""
    tail = html[s:]
    depth = 0
    for m in re.finditer(r'<div\b|</div>', tail):
        if m.group(0) == '</div>':
            depth -= 1
            if depth == 0:
                return tail[:m.end()]
        else:
            depth += 1
    return tail
