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
import argparse, json, os, re, subprocess, sys, hashlib
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from checks import STATIC_RULES, BLOCKER, MAJOR, MINOR, CONTRAST_JS, OVERFLOW_JS

BLOG = "https://masaladeutsch.blogspot.com"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
SHOTS = os.path.join(HERE, "baseline")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def post_list():
    posts, seen, i = [], set(), 1
    while True:
        raw = sh(["curl", "-s", "-A", UA,
                  f"{BLOG}/feeds/posts/summary?start-index={i}&max-results=25&alt=json"])
        try:
            d = json.loads(raw)
        except Exception:
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
        i += 25
    return posts


def fetch(url):
    return sh(["curl", "-s", "-A", UA, url])


def body_of(html):
    """Return just the post body.

    Blogger renders no post-footer on this theme, so walk balanced <div> tags
    from the opening post-body tag. Scoping matters: falling back to the whole
    page pulls the theme's own CSS in and every dark-mode rule fires falsely.
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


def js_syntax_errors(html, tmp):
    with open(tmp, "w") as f:
        f.write(html)
    script = os.path.join(OUT, "_syntax.js")
    if not os.path.exists(script):
        with open(script, "w") as f:
            f.write(NODE_SYNTAX)
    out = sh(["node", script, tmp]).strip()
    try:
        return json.loads(out)
    except Exception:
        return []


def static_audit(post):
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
        except Exception as ex:
            ok, detail = False, f"rule error: {type(ex).__name__}"
        res.append({"rule": name, "severity": sev, "ok": bool(ok), "detail": detail})
    return {**post, "checks": res, "bytes": len(html)}


def rendered_audit(posts, baseline=False):
    from playwright.sync_api import sync_playwright
    os.makedirs(SHOTS, exist_ok=True)
    out = {}
    with sync_playwright() as p:
        br = p.chromium.launch()
        for scheme in ("light", "dark"):
            ctx = br.new_context(viewport={"width": 1280, "height": 900},
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
                except Exception as ex:
                    out[(post["id"], scheme)] = {"error": f"{type(ex).__name__}: {ex}"[:120]}
            ctx.close()
        br.close()
    return out


def main():
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
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    if args.url:
        posts = [{"id": hashlib.md5(args.url.encode()).hexdigest()[:8],
                  "title": args.url.rsplit("/", 1)[-1], "url": args.url}]
    elif args.urls_file:
        urls = [l.strip() for l in open(args.urls_file) if l.strip()]
        posts = [{"id": hashlib.md5(u.encode()).hexdigest()[:8],
                  "title": u.rsplit("/", 1)[-1], "url": u} for u in urls]
    else:
        print("fetching post list ...", flush=True)
        posts = post_list()
        if args.priority:
            # keep only posts failing BOTH inverted-MQ and dark-vars-locked
            print("pre-screening for the white-on-white combination ...", flush=True)
            with ThreadPoolExecutor(max_workers=8) as ex:
                pre = list(ex.map(static_audit, posts))
            keep = set()
            for r in pre:
                c = {x["rule"]: x for x in r["checks"]}
                if not c["no-inverted-media-query"]["ok"] and not c["dark-vars-locked"]["ok"]:
                    keep.add(r["id"])
            posts = [p for p in posts if p["id"] in keep]
    if args.limit:
        posts = posts[:args.limit]
    print(f"auditing {len(posts)} posts\n", flush=True)

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(static_audit, posts))

    rend = {}
    if args.rendered or args.baseline:
        print("rendered pass (light + dark) ...", flush=True)
        rend = rendered_audit(posts, baseline=args.baseline)
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

    # ---- report ----
    sev_rank = {BLOCKER: 0, MAJOR: 1, MINOR: 2}
    failing = []
    for r in results:
        bad = [c for c in r["checks"] if not c["ok"]]
        if bad:
            worst = min(sev_rank[c["severity"]] for c in bad)
            failing.append((worst, len(bad), r, bad))
    failing.sort(key=lambda x: (x[0], -x[1]))

    counts = {}
    for r in results:
        for c in r["checks"]:
            k = (c["severity"], c["rule"])
            counts.setdefault(k, [0, 0])
            counts[k][1] += 1
            if not c["ok"]:
                counts[k][0] += 1

    lines = []
    lines.append(f"# masaladeutsch consistency report\n")
    lines.append(f"posts audited: **{len(results)}** · posts with at least one failure: "
                 f"**{len(failing)}**\n")
    lines.append("## Rule summary\n")
    lines.append("| severity | rule | failing | checked |")
    lines.append("|---|---|---:|---:|")
    for (sev, rule), (bad, tot) in sorted(counts.items(), key=lambda kv: (sev_rank[kv[0][0]], -kv[1][0])):
        lines.append(f"| {sev} | `{rule}` | {bad} | {tot} |")
    lines.append("\n## Posts needing attention\n")
    for worst, n, r, bad in failing:
        lines.append(f"### {r['title'][:80]}")
        lines.append(f"{r['url']}")
        for c in sorted(bad, key=lambda c: sev_rank[c["severity"]]):
            d = f" — {c['detail']}" if c["detail"] else ""
            lines.append(f"- **{c['severity']}** `{c['rule']}`{d}")
        lines.append("")
    report = "\n".join(lines)

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
