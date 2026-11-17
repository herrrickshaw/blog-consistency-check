#!/usr/bin/env python3
"""
masaladeutsch consistency checker.

Two passes:
  static   - fetch every post, run the rule set (fast, no browser)
  rendered - Playwright, computed contrast + overflow in LIGHT and DARK,
             plus a screenshot baseline for visual-regression diffing

Usage:
  python3 audit.py                      # static pass over all posts
  python3 audit.py --rendered           # + browser pass (slower)
  python3 audit.py --rendered --limit 5
  python3 audit.py --baseline           # write/refresh screenshot baselines
  python3 audit.py --url <single post>

Exit code is non-zero if any BLOCKER fails, so it can gate CI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from checks import STATIC_RULES, BLOCKER, MAJOR, MINOR, CONTRAST_JS, OVERFLOW_JS  # noqa: E402
from common import UA, VIEWPORT, body_of, fetch_html, sh  # noqa: E402,F401  (re-exported)

log = logging.getLogger(__name__)

BLOG = "https://masaladeutsch.blogspot.com"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SHOTS = os.path.join(HERE, "baseline")
FEED_PAGE_SIZE = 25
WORKERS = 8
SEV_RANK = {BLOCKER: 0, MAJOR: 1, MINOR: 2}


def post_list() -> List[dict]:
    """Page through the blog's JSON summary feed; return ``[{id, title, url}]``."""
    posts, seen, i = [], set(), 1
    while True:
        raw = sh(["curl", "-s", "-A", UA,
                  f"{BLOG}/feeds/posts/summary?start-index={i}&max-results={FEED_PAGE_SIZE}&alt=json"])
        try:
            d = json.loads(raw)
        except ValueError:
            log.warning("feed page at start-index=%d was not JSON; stopping", i)
            break
        entries = d.get("feed", {}).get("entry", [])
        if not entries:
            break
        for e in entries:
            pid = re.search(r"post-(\d+)", e["id"]["$t"]).group(1)
            if pid in seen:
                continue
            seen.add(pid)
            posts.append({"id": pid, "title": e["title"]["$t"],
                          "url": [l["href"] for l in e["link"] if l["rel"] == "alternate"][0]})
        i += FEED_PAGE_SIZE
    return posts


def fetch(url: str) -> str:
    """Fetch one post page (thin alias so tests can stub the network)."""
    return fetch_html(url)


NODE_SYNTAX = r"""
const fs=require('fs');
const html=fs.readFileSync(process.argv[1],'utf8');
const re=/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g;
let m,i=0,bad=[];
while((m=re.exec(html))){ i++;
  let c=m[1].replace(/^\s*\/\/<!\[CDATA\[/,'').replace(/\/\/\]\]>\s*$/,'');
  if(!c.trim()) continue;
  try{ new Function(c); }catch(e){ bad.push(i); }
}
console.log(JSON.stringify(bad));
"""


def js_syntax_errors(html: str, tmp: str) -> List[int]:
    """Return 1-based indexes of ``<script>`` blocks in ``html`` that fail to parse (needs node)."""
    with open(tmp, "w") as f:
        f.write(html)
    script = os.path.join(OUT, "_syntax.js")
    if not os.path.exists(script):
        with open(script, "w") as f:
            f.write(NODE_SYNTAX)
    out = sh(["node", script, tmp]).strip()
    try:
        return json.loads(out)
    except ValueError:
        log.warning("node syntax check gave unparseable output: %r", out[:80])
        return []


def static_audit(post: dict) -> dict:
    """Fetch ``post`` and run every static rule; return the post dict plus ``checks``."""
    html = fetch(post["url"])
    body = body_of(html)
    # syntax-check only the post's own scripts, not the theme's
    tmp = os.path.join(OUT, f"_t{post['id']}.html")
    errs = js_syntax_errors(body, tmp)
    try:
        os.remove(tmp)
    except OSError:
        pass
    res = []
    for name, sev, fn in STATIC_RULES:
        try:
            ok, detail = fn(body=body, node_check=errs)
        except Exception as ex:  # a broken rule must not abort the whole audit
            log.exception("rule %s crashed on %s", name, post["url"])
            ok, detail = False, f"rule error: {type(ex).__name__}"
        res.append({"rule": name, "severity": sev, "ok": bool(ok), "detail": detail})
    return {**post, "checks": res, "bytes": len(html)}


def rendered_audit(posts: List[dict], baseline: bool = False) -> dict:
    """Playwright pass: contrast + overflow per ``(post id, scheme)``; optional screenshots."""
    from playwright.sync_api import sync_playwright
    os.makedirs(SHOTS, exist_ok=True)
    out = {}
    with sync_playwright() as p:
        br = p.chromium.launch()
        for scheme in ("light", "dark"):
            ctx = br.new_context(viewport=VIEWPORT,
                                 color_scheme=scheme, user_agent=UA)
            pg = ctx.new_page()
            for post in posts:
                try:
                    pg.goto(post["url"], wait_until="networkidle", timeout=45000)
                    pg.wait_for_timeout(700)
                    con = pg.evaluate(CONTRAST_JS)
                    ovf = pg.evaluate(OVERFLOW_JS)
                    key = (post["id"], scheme)
                    out[key] = {"contrast": con, "overflow": ovf}
                    if baseline:
                        pg.screenshot(path=os.path.join(SHOTS, f"{post['id']}.{scheme}.png"),
                                      full_page=True)
                except Exception as ex:  # one bad page must not abort the run
                    log.warning("rendered audit failed for %s: %s", post["url"], ex)
                    out[(post["id"], scheme)] = {"error": f"{type(ex).__name__}: {ex}"[:120]}
            ctx.close()
        br.close()
    return out


def _post_from_url(url: str) -> dict:
    """Build a post record for a bare URL (id = first 8 hex of its md5)."""
    return {"id": hashlib.md5(url.encode()).hexdigest()[:8],
            "title": url.rsplit("/", 1)[-1], "url": url}


def select_posts(args: argparse.Namespace) -> List[dict]:
    """Resolve CLI arguments to the list of posts to audit."""
    if args.url:
        posts = [_post_from_url(args.url)]
    elif args.urls_file:
        with open(args.urls_file) as fh:
            posts = [_post_from_url(u.strip()) for u in fh if u.strip()]
    else:
        print("fetching post list ...", flush=True)
        posts = post_list()
        if args.priority:
            # keep only posts failing BOTH inverted-MQ and dark-vars-locked
            print("pre-screening for the white-on-white combination ...", flush=True)
            with ThreadPoolExecutor(max_workers=WORKERS) as ex:
                pre = list(ex.map(static_audit, posts))
            keep = set()
            for r in pre:
                c = {x["rule"]: x for x in r["checks"]}
                if not c["no-inverted-media-query"]["ok"] and not c["dark-vars-locked"]["ok"]:
                    keep.add(r["id"])
            posts = [p for p in posts if p["id"] in keep]
    if args.limit:
        posts = posts[:args.limit]
    return posts


def add_rendered_checks(results: List[dict], rend: dict) -> None:
    """Append contrast/overflow results from ``rendered_audit`` to each post's checks (in place)."""
    for r in results:
        for scheme in ("light", "dark"):
            d = rend.get((r["id"], scheme))
            if not d or "error" in d:
                continue
            c, o = d["contrast"], d["overflow"]
            r["checks"].append({"rule": f"contrast-{scheme}", "severity": BLOCKER,
                                "ok": c["fails"] == 0,
                                "detail": (f"{c['fails']}/{c['checked']} nodes below 3:1"
                                           if c["fails"] else f"0/{c['checked']}")})
            r["checks"].append({"rule": f"no-overflow-{scheme}", "severity": MINOR,
                                "ok": not o["pageOverflow"],
                                "detail": (f"doc {o['docW']}px > view {o['viewW']}px"
                                           if o["pageOverflow"] else "")})


Failing = List[Tuple[int, int, dict, List[dict]]]


def summarise(results: List[dict]) -> Tuple[Failing, Dict[Tuple[str, str], List[int]]]:
    """Return (failing posts sorted worst-first, per-rule ``[failing, checked]`` counts)."""
    failing: Failing = []
    for r in results:
        bad = [c for c in r["checks"] if not c["ok"]]
        if bad:
            worst = min(SEV_RANK[c["severity"]] for c in bad)
            failing.append((worst, len(bad), r, bad))
    failing.sort(key=lambda x: (x[0], -x[1]))

    counts: Dict[Tuple[str, str], List[int]] = {}
    for r in results:
        for c in r["checks"]:
            k = (c["severity"], c["rule"])
            counts.setdefault(k, [0, 0])
            counts[k][1] += 1
            if not c["ok"]:
                counts[k][0] += 1
    return failing, counts


def render_markdown(results: List[dict], failing: Failing,
                    counts: Dict[Tuple[str, str], List[int]]) -> str:
    """Render the markdown report text (pure function of its inputs)."""
    lines = []
    lines.append("# masaladeutsch consistency report\n")
    lines.append(f"posts audited: **{len(results)}** · posts with at least one failure: "
                 f"**{len(failing)}**\n")
    lines.append("## Rule summary\n")
    lines.append("| severity | rule | failing | checked |")
    lines.append("|---|---|---:|---:|")
    for (sev, rule), (bad, tot) in sorted(counts.items(), key=lambda kv: (SEV_RANK[kv[0][0]], -kv[1][0])):
        lines.append(f"| {sev} | `{rule}` | {bad} | {tot} |")
    lines.append("\n## Posts needing attention\n")
    for worst, n, r, bad in failing:
        lines.append(f"### {r['title'][:80]}")
        lines.append(f"{r['url']}")
        for c in sorted(bad, key=lambda c: SEV_RANK[c["severity"]]):
            d = f" — {c['detail']}" if c["detail"] else ""
            lines.append(f"- **{c['severity']}** `{c['rule']}`{d}")
        lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """CLI definition (flags unchanged)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--rendered", action="store_true")
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--url", default="")
    ap.add_argument("--urls-file", default="",
                    help="file with one post URL per line; audit only these")
    ap.add_argument("--priority", action="store_true",
                    help="audit only posts that fail BOTH no-inverted-media-query "
                         "and dark-vars-locked (the white-on-white combination)")
    return ap


def main() -> None:
    args = build_parser().parse_args()
    os.makedirs(OUT, exist_ok=True)

    posts = select_posts(args)
    print(f"auditing {len(posts)} posts\n", flush=True)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = list(ex.map(static_audit, posts))

    if args.rendered or args.baseline:
        print("rendered pass (light + dark) ...", flush=True)
        add_rendered_checks(results, rendered_audit(posts, baseline=args.baseline))

    failing, counts = summarise(results)
    report = render_markdown(results, failing, counts)

    with open(os.path.join(OUT, "report.md"), "w") as f:
        f.write(report)
    with open(os.path.join(OUT, "report.json"), "w") as f:
        json.dump(results, f, indent=1)

    print(report[:4000])
    print(f"\nfull report: {os.path.join(OUT,'report.md')}")

    blockers = sum(1 for _, _, _, bad in failing
                   for c in bad if c["severity"] == BLOCKER)
    if blockers:
        print(f"\n{blockers} BLOCKER failures")
        sys.exit(1)


if __name__ == "__main__":
    main()
