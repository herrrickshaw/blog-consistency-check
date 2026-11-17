# blog-consistency-check

A consistency and visual-regression checker for the blog **masaladeutsch.blogspot.com**. It fetches every post,
runs a rule set that encodes defects actually found on the live site, and writes a Markdown and JSON report. It
can also generate corrected post bodies (nothing is ever uploaded) and insert house-style elements into those
fixes.

> Status: maintained. Single-author tool for one blog; it reads the live site over HTTP but never publishes to it.
> The report in `out/` and the files in `fixes/` are generated artefacts.

<!-- how-to-use-with-ai -->
> **New here?** See [How to use this repo with AI (Claude, Gemini, ChatGPT)](HOW_TO_USE_WITH_AI.md) — clone it,
> paste it into an AI tool, and ask in plain English.

It is deliberately not a generic screenshot-diff tool. Percy, Applitools and BackstopJS all answer "did this page
change?" — the wrong question for a blog whose posts legitimately differ from each other and rarely change once
published. The question that matters here is **"is this post broken?"**, and the defects worth catching are known and
specific: JavaScript spliced by an automated edit, backwards media queries, unreadable contrast, wrong data
attribution. See [CHECKLIST.md](CHECKLIST.md) for what each rule is and why it exists.

## What it does
- `audit.py` — static pass over every post from the blog's JSON feed (about 30 s), optional Playwright pass
  for computed contrast and overflow in light **and** dark mode, optional screenshot baselines.
- Exits non-zero when any BLOCKER rule fails, so it can gate CI.
- `fix.py` — builds corrected bodies into `fixes/<slug>.html` and verifies them by swapping the repaired body into the
  live page's DOM in a headless browser.
- `add_index_link.py` / `add_revision_line.py` — insert the back-to-index link and the house revision line into
  the pending files in `fixes/`.

## Quick start
```bash
git clone https://github.com/herrrickshaw/blog-consistency-check.git
cd blog-consistency-check
python3 -m venv .venv && source .venv/bin/activate
pip install playwright && python -m playwright install chromium   # only for --rendered / fix.py verification
python3 audit.py            # static pass, all posts; writes out/report.md and out/report.json
```
Needs `curl` and `node` on PATH (node syntax-checks post scripts).

```bash
python3 audit.py --rendered                 # + Playwright contrast/overflow, light AND dark
python3 audit.py --rendered --limit 5
python3 audit.py --url https://masaladeutsch.blogspot.com/2026/08/some-post.html
python3 audit.py --urls-file out/broken_urls.txt
python3 audit.py --priority                 # only posts failing both inverted-MQ and dark-vars-locked
python3 audit.py --rendered --baseline      # also write screenshot baselines to baseline/
python3 fix.py --urls-file out/broken_urls.txt        # or --url <post>, --no-verify
python3 add_index_link.py --dry-run
python3 add_revision_line.py --dry-run      # needs MASALADEUTSCH_ARCHIVE, see Configuration
```

## How it works
| Stage | Module | Output |
|---|---|---|
| list posts (feed, 25 per page) | `audit.post_list` | post id, title, URL |
| fetch + slice the post body | `common.fetch_html`, `common.body_of` | balanced `post-body` div |
| static rules | `checks.STATIC_RULES` | `(ok, detail)` per rule |
| rendered rules | `audit.rendered_audit` + `checks.CONTRAST_JS`/`OVERFLOW_JS` | per-scheme contrast and overflow |
| report | `audit.summarise`, `audit.render_markdown` | `out/report.md`, `out/report.json` |
| repair | `fix.repair` | `fixes/<slug>.html`, `fixes/manifest.json` |

Design decisions: rules are scoped to the post body (not the whole page) because the theme's own CSS would make every
dark-mode rule fire falsely; contrast and overflow run in both colour schemes because the backwards media query only
bites in light mode; the light-lock in `fix.py` is derived from each post's own `:root` so the design never changes.

### What it checks
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

### Adding a rule
Write a function in `checks.py` taking `(body, **kw)` and returning `(ok, detail)`, register it in `STATIC_RULES`
with a severity, and add the matching line to `CHECKLIST.md`. Rendered rules go in `audit.rendered_audit` using the
JS snippets at the bottom of `checks.py`.

## Repository layout
| Path | Purpose |
|---|---|
| `audit.py` | CLI: fetch, run rules, write report |
| `checks.py` | rule definitions and browser JS snippets |
| `common.py` | shared user agent, curl wrapper, post-body slicer |
| `fix.py` | generate and verify corrected post bodies |
| `add_index_link.py`, `add_revision_line.py` | patch pending files in `fixes/` |
| `CHECKLIST.md` | what each rule is and why it exists |
| `tests/` | offline pytest suite, including a characterisation snapshot |
| `fixes/`, `out/` | generated artefacts (corrected bodies, reports); not hand-edited |
| `graphify-out/` | generated knowledge-graph output |

## Data sources
| Source | What is taken | Access route | Licence / caveat |
|---|---|---|---|
| masaladeutsch.blogspot.com | post HTML and the Blogger JSON feed | `curl` with a browser User-Agent | The author's own blog; read-only |

## Configuration
- `MASALADEUTSCH_ARCHIVE` — path to the `blogger_writeups_code` checkout holding `meta/manifest.json`; used only by
  `add_revision_line.py` (default: a sibling directory of this repo).
- No secrets are used or needed.

## Testing
```bash
pip install pytest ruff
ruff check . && pytest -q
```
Tests never touch the network or a browser. `tests/golden_baseline.json` was captured from the pre-refactor code
and asserts that rule results, repair output and the full `audit.py` report over the `fixes/` corpus are unchanged.

## Limitations and known issues
- Last recorded run (88 posts, 2026-08-06): `no-inverted-media-query` failed on 43/88, `dark-vars-locked` 23/88,
  `no-disclaimer-in-script` 1/88, `js-parses` 0/88 (was 7), `disclaimer-present` 27/88, `index-link` 37/88,
  `table-units-in-header` 10/88, `translate-widget` 8/88, `bw-override` 5/88. Worst single post: *Where India's
  Factories Actually Get Built*, 256 of 530 text nodes below 3:1 in light mode.
- `--baseline` screenshots are for eyeballing a redesign, not for pixel-diff gating; the computed-style checks are the
  reliable signal.
- `fixes/manifest.json` records absolute local paths from the author's machine.
- `audit.py` writes a helper script to `out/_syntax.js` at run time.

## Licence
No licence file yet — all rights reserved.
