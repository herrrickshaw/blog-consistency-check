#!/usr/bin/env python3
"""Insert the house revision line into pending fix files in fixes/.

The line goes immediately after the index backlink (the last of the standard
pre-content elements), so it sits above the hero exactly as the template
specifies. Idempotent: a file that already carries `data-gs-revision-v1` is left
alone.

    python3 add_revision_line.py --dry-run
    python3 add_revision_line.py
"""
import argparse
import json
import os
import pathlib
import re
import sys

FIXES = pathlib.Path(__file__).resolve().parent / "fixes"
# This standalone repo has no fixed relationship to the archive checkout
# (blogger_writeups_code) that holds meta/manifest.json -- unlike the copy of
# this file embedded inside that archive repo, where consistency-check/ is a
# subdirectory and the path is always one level up. Point MASALADEUTSCH_ARCHIVE
# at your checkout; this only guesses a sibling directory as a fallback, and
# pending_slugs() below fails with a clear message rather than a bare
# FileNotFoundError if that guess is wrong.
ARCHIVE = pathlib.Path(os.environ.get(
    "MASALADEUTSCH_ARCHIVE",
    pathlib.Path(__file__).resolve().parent.parent / "blogger_writeups_code",
))
MANIFEST = ARCHIVE / "meta" / "manifest.json"
MARKER = "data-gs-revision-v1"

# These fixes are design repairs — light-lock, dark-panel guard, removing an
# inverted media query. They change no figure and add no section, so every one of
# them is a PATCH against the post's 1.0.0 baseline.
VERSION = "1.0.1"
DATE_ISO = "2026-08-06"
DATE_HUMAN = "6 August 2026"

LINE = (
    '<p class="gs-revised" {marker}="1" style="font-size:.8rem;color:#555;'
    'margin:0 0 14px">Revised '
    '<time datetime="{iso}" itemprop="dateModified">{human}</time> '
    "&middot; v{version} &middot; design and readability fixes"
    "</p>"
).format(marker=MARKER, iso=DATE_ISO, human=DATE_HUMAN, version=VERSION)

INDEX_LINK = re.compile(
    r"(<div class=[\"']topnav-index-link[\"'][\s\S]*?</div>)", re.I
)
# The FIRST </style>, not the last: fix.py appends the light-lock and dark-panel
# guard as extra <style> blocks at the END of the document, so anchoring on the
# last one drops the revision line at the foot of the post next to the AI
# disclosure instead of at the top where a reader will see it.
STYLE_END = re.compile(r"(</style>)", re.I)
# Sanity bounds — the line belongs in the preamble, not at the foot of the post.
# A raw fraction alone is unreliable: these documents are up to half CSS by
# weight, so an anchor at 43% can still be above the first line of prose. Pair a
# loose fraction with a hard rule that it must land well clear of the closing
# AI-disclosure paragraph.
MAX_OFFSET_FRACTION = 0.5
DISCLOSURE = re.compile(r"gs-ai-disclosure|class=[\"']disclaimer[\"']", re.I)
MIN_GAP_BEFORE_DISCLOSURE = 500  # characters


def pending_slugs():
    """A fix is pending when the live post does not yet satisfy what it repairs."""
    if not MANIFEST.exists():
        sys.exit(
            f"can't find {MANIFEST} -- set MASALADEUTSCH_ARCHIVE to your "
            "blogger_writeups_code checkout, e.g.\n"
            "  MASALADEUTSCH_ARCHIVE=~/blogger_writeups_code python3 add_revision_line.py"
        )
    live = {r["slug"]: r for r in json.loads(MANIFEST.read_text())["posts"].values()}
    out = []
    for e in json.loads((FIXES / "manifest.json").read_text()):
        rec = live.get(e["slug"])
        if rec is None:
            continue  # not live under this slug (already republished elsewhere)
        body = pathlib.Path(e["path"]).read_text(encoding="utf-8", errors="replace")
        m = rec["markers"]
        satisfied = (
            (m["light_lock"] or "gs-light-lock" not in body)
            and (m["dark_panel_guard"] or "gs-dark-panel-guard" not in body)
            and not m["inverted_media_query"]
        )
        if not satisfied:
            out.append(e)
    return out


def insert(body):
    """Return (new_body, where) or (None, reason) if there is nowhere sane."""
    if MARKER in body:
        return None, "already has a revision line"
    for pattern, where in ((INDEX_LINK, "after index link"), (STYLE_END, "after first </style>")):
        m = pattern.search(body)
        if not m:
            continue
        if m.end() > len(body) * MAX_OFFSET_FRACTION:
            return None, f"{where} would land at {m.end() / len(body):.0%} through the doc"
        disc = DISCLOSURE.search(body)
        if disc and disc.start() - m.end() < MIN_GAP_BEFORE_DISCLOSURE:
            return None, f"{where} would land on top of the AI disclosure"
        return body[: m.end()] + "\n" + LINE + body[m.end():], where
    return None, "no index link and no </style> — insert by hand"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    todo = pending_slugs()
    print(f"{len(todo)} pending fixes\n")
    done = skipped = 0
    for e in todo:
        path = pathlib.Path(e["path"])
        body = path.read_text(encoding="utf-8")
        new, where = insert(body)
        if new is None:
            print(f"  skip  {e['slug']:<48} {where}")
            skipped += 1
            continue
        if not args.dry_run:
            path.write_text(new, encoding="utf-8")
        print(f"  ok    {e['slug']:<48} {where}")
        done += 1

    print(f"\n{done} updated, {skipped} skipped" + (" (dry run)" if args.dry_run else ""))
    return 1 if skipped and not done else 0


if __name__ == "__main__":
    sys.exit(main())
