#!/usr/bin/env python3
"""Insert the site index backlink into fix files that are missing it.

The backlink is a required element of the frozen design (see DESIGN_LOG.md), but
ten live posts never got one. This adds it to their fix files so it lands the
next time each fix is applied.

Placement follows the template's element order — translate widget, then index
link, then hero, then the revision line — so the anchor is the translate widget
where present, otherwise the first `</style>`. Anchoring on the first `</style>`
matters: fix.py appends the light-lock and dark-panel guard as extra <style>
blocks at the END of the document, so the last one sits beside the AI disclosure.

    python3 add_index_link.py --dry-run
    python3 add_index_link.py
"""
import argparse
import json
import pathlib
import re
import sys

FIXES = pathlib.Path(__file__).resolve().parent / "fixes"
INDEX_URL = "https://masaladeutsch.blogspot.com/2026/08/article-index-start-here.html"
MARKER = "article-index-start-here"

LINE = (
    '<div class="topnav-index-link" style="font-size:.82em;margin:6px 0 14px">'
    f'<a href="{INDEX_URL}" style="color:#0b5394;text-decoration:none">'
    "&#8592; All Articles (Index)</a></div>"
)

TRANSLATE = re.compile(
    r"(<div id=[\"']google_translate_element[\"'][\s\S]*?</script>\s*"
    r"<script[^>]*translate\.google\.com[\s\S]*?</script>)",
    re.I,
)
STYLE_END = re.compile(r"(</style>)", re.I)
REVISION = re.compile(r"<p class=[\"']gs-revised[\"'][\s\S]*?</p>", re.I)
DISCLOSURE = re.compile(r"gs-ai-disclosure|class=[\"']disclaimer[\"']", re.I)
MAX_OFFSET_FRACTION = 0.5
MIN_GAP_BEFORE_DISCLOSURE = 500


def insert(body):
    if MARKER in body:
        return None, "already has an index link"
    for pattern, where in (
        (TRANSLATE, "after translate widget"),
        (STYLE_END, "after first </style>"),
    ):
        m = pattern.search(body)
        if not m:
            continue
        if m.end() > len(body) * MAX_OFFSET_FRACTION:
            return None, f"{where} would land at {m.end() / len(body):.0%} through the doc"
        disc = DISCLOSURE.search(body)
        if disc and disc.start() - m.end() < MIN_GAP_BEFORE_DISCLOSURE:
            return None, f"{where} would land on top of the AI disclosure"
        return body[: m.end()] + "\n" + LINE + body[m.end():], where
    return None, "no translate widget and no </style> — insert by hand"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    done = skipped = 0
    for e in json.loads((FIXES / "manifest.json").read_text()):
        path = pathlib.Path(e["path"])
        body = path.read_text(encoding="utf-8")
        new, where = insert(body)
        if new is None:
            if "already has" not in where:
                print(f"  skip  {e['slug']:<48} {where}")
                skipped += 1
            continue
        # The index link must precede the revision line (template element order).
        rev = REVISION.search(new)
        idx = new.index(MARKER)
        if rev and rev.start() < idx:
            # The revision line already sits above this anchor (it was placed on
            # the first </style>, which precedes the translate widget here).
            # Slot the index link in just above it rather than breaking order.
            r = REVISION.search(body)
            new = body[: r.start()] + LINE + "\n" + body[r.start():]
            where = "before the revision line"
        if not args.dry_run:
            path.write_text(new, encoding="utf-8")
        print(f"  ok    {e['slug']:<48} {where}")
        done += 1

    print(f"\n{done} updated, {skipped} skipped" + (" (dry run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
