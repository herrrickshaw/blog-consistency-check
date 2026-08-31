# blog-consistency-check

A consistency / visual-regression checker for **masaladeutsch.blogspot.com**.

It is deliberately not a generic screenshot-diff tool. Percy, Applitools and
BackstopJS all answer "did this page change?" — which is the wrong question for
a blog whose posts legitimately differ from each other and rarely change once
published. The question that actually matters here is **"is this post broken?"**,
and the defects worth catching are known and specific: JavaScript spliced by an
automated edit, backwards media queries, unreadable contrast, wrong data
attribution.

So the rules encode real defects found on the live site. See
[CHECKLIST.md](CHECKLIST.md) for what each one is and why it exists.

## Install

```bash
~/.venvs/testing/bin/python3 -m pip install playwright
~/.venvs/testing/bin/python3 -m playwright install chromium
```

Needs `curl` and `node` on PATH (node is used to syntax-check post scripts).

## Use

```bash
python3 audit.py                     # static pass, all posts (~30s)
python3 audit.py --rendered          # + Playwright contrast/overflow, light AND dark
python3 audit.py --rendered --limit 5
python3 audit.py --url https://masaladeutsch.blogspot.com/2026/08/some-post.html
python3 audit.py --rendered --baseline   # also write screenshot baselines
```

Writes `out/report.md` and `out/report.json`. **Exits non-zero if any BLOCKER
fails**, so it can gate CI.

## What it checks

| Severity | Rule | Catches |
|---|---|---|
| BLOCKER | `js-parses` | any JS syntax error — one kills every chart in the block |
| BLOCKER | `no-disclaimer-in-script` | HTML spliced into a JS string literal |
| BLOCKER | `no-inverted-media-query` | `@media not all and (prefers-color-scheme:dark)` — applies in **light** mode |
| BLOCKER | `dark-vars-locked` | post's dark palette consumed with no `!important` light lock |
| BLOCKER | `contrast-light` / `contrast-dark` | computed WCAG ratio < 3:1, both schemes |
| MAJOR | `wpi-attribution` | WPI credited to MoSPI (it is DPIIT / Office of the Economic Adviser) |
| MAJOR | `disclaimer-present` | AI disclosure missing, or only present inside a script |
| MINOR | `translate-widget`, `index-link`, `bw-override`, `table-units-in-header`, `no-overflow-*` | house style |

Contrast and overflow run in **both** light and dark, because the two fail
differently — the backwards media query only bites in light mode, which is
exactly why it went unnoticed.

## Current state (88 posts, 2026-08-06)

```
BLOCKER  no-inverted-media-query   43/88
BLOCKER  dark-vars-locked          23/88
BLOCKER  no-disclaimer-in-script    1/88
BLOCKER  js-parses                  0/88   ← was 7, fixed this session
MAJOR    disclaimer-present        27/88
MAJOR    wpi-attribution            0/88
MINOR    index-link                37/88
MINOR    table-units-in-header     10/88
MINOR    translate-widget           8/88
MINOR    bw-override                5/88
```

Worst single post: *Where India's Factories Actually Get Built* —
**256 of 530 text nodes below 3:1 in light mode** (white-on-white body text).

## Adding a rule

Write a function in `checks.py` taking `(body, **kw)` and returning
`(ok, detail)`, register it in `STATIC_RULES` with a severity, and add the
matching line to `CHECKLIST.md`. Rendered rules go in `audit.py`'s
`rendered_audit` using the JS snippets at the bottom of `checks.py`.

## Screenshot baselines

`--baseline` writes full-page PNGs to `baseline/<postid>.<scheme>.png`. These
are for eyeballing a redesign, not for pixel-diff gating: post content changes
legitimately, so a pixel diff produces mostly false alarms. The computed-style
checks above are the reliable signal.
