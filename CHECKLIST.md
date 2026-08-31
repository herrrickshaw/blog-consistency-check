# masaladeutsch post checklist

Every item below exists because it went wrong on a live post. Each one is
enforced by a rule in `checks.py`, so this document and the tool cannot drift
apart — if you add a rule, add the line here.

Run `python3 audit.py --rendered` to check all posts against it.

---

## A. Blockers — the reader sees something broken

### A1. No HTML inside a `<script>` tag
Automated content insertion must never land inside JavaScript. The bulk
disclaimer sweep spliced a `<p>` into a JS string literal, including a raw
newline inside a single-quoted string. That is a `SyntaxError`, and a
`SyntaxError` kills the *entire* script block — every chart, stat tile and
generated table on the page silently disappears.

- Found on **8 posts**. Seven had dead charts; one (Mineral-Oil dashboard) still
  has the splice today.
- When appending to a post, insert **after the last `</script>`**. Do not search
  for `</div>` — a `<script>` can contain that string as text, and inserting
  there recreates the bug.
- Rules: `no-disclaimer-in-script`, `js-parses`

### A2. No backwards media queries
`@media not all and (prefers-color-scheme: dark)` reads as "apply when NOT
dark", i.e. **in light mode** — the opposite of what its author intended. Blocks
written this way set dark values (`--text:#e8e8e8`, `.artx{color:#ddd}`) in the
default light view.

- Found on **43 of 88 posts**.
- On *Where India's Factories Actually Get Built* it produced white-on-white:
  **256 of 530 text nodes below 3:1 contrast in light mode.**
- Fix: delete the block. The post's own `:root` already carries the correct
  light values (`--surface:#fff`, `--text:#000`), so removing it restores the
  intended design exactly — no new CSS needed.
- Rule: `no-inverted-media-query`

### A3. A post's own dark palette must be pinned to light
If a post declares a dark colour scheme **and** something consumes those
variables, pin the light values with `!important`. Otherwise the site-wide
BW-override blackens some descendants while the post's own block darkens the
surface, and you get black text on a dark panel.

- Verified real: `.dek` computed to `rgb(0,0,0)` on `--page-bg #12151a`.
- Fix: append a `<style>/*gs-light-lock-v1*/:root,:root[data-theme="dark"],:root[data-theme="light"]{ …post's own light values… !important; color-scheme:light!important;}</style>`.
  **Derive the values from that post's own `:root`** — do not paste a generic
  palette, or you change the design.
- Note: a post that declares dark vars but never consumes them is *not* at risk.
  Measuring this cut the real worklist from 44 posts to 16.
- Rules: `dark-vars-locked`, `bw-override`, `contrast-light`, `contrast-dark`

### A4. Contrast ≥ 3:1, in **both** colour schemes
Check light *and* dark. The failure modes are different and a post can pass one
and fail the other badly.
- Rules: `contrast-light`, `contrast-dark`

---

## B. Major — the information is wrong

### B1. Attribute statistics to the agency that publishes them
- **WPI is published by the Office of the Economic Adviser, DPIIT** (Ministry of
  Commerce & Industry). **MoSPI publishes CPI.** Several posts said "MoSPI
  Wholesale Price Index" and cited a "MoSPI connector" for WPI. Wrong office,
  wrong primary source for any reader who follows it.
- One post is still *titled* "CPI & WPI Trends — MoSPI Bulletin", and that title
  propagates into the nav block on ~85 posts.
- Rule: `wpi-attribution`

### B2. State the base year, and never splice across a rebasing
WPI was rebased from 2011-12 to **2022-23** mid-series. Index *levels* on the
two bases are not splice-able (a rebasing resets to 100 on a new basket);
*inflation rates* are comparable. Say which base a number is on.

### B3. Don't claim a statistic is unavailable without checking
One post said WPI's release "doesn't carry a comparable inflation-rate field, so
the index itself is the only figure available". Year-on-year is arithmetic on
the index (`Iₜ / Iₜ₋₁₂ − 1`). Computed that way it reproduces the published rate
**exactly** — 9.87% headline for June 2026, matching the press release to the
second decimal. A gap in one data connector is not a gap in the statistic.

### B4. Recheck derived figures against the primary source
The DAP figure had drifted to +38.4%; the published series gives **+41.9%**
(Apr 2012 → Apr 2026). It matched no month in the official data.

### B5. Every post carries the AI disclosure, outside any script
- Rule: `disclaimer-present` (27 posts currently missing it)

---

## C. Minor — house style

| Item | Rule |
|---|---|
| Google Translate widget embedded per-post (site-wide placement is blocked in Blogger) | `translate-widget` |
| Back-to-index nav link present | `index-link` |
| Table units in `<th>`, not repeated in every `<td>` (threshold 30% of cells) | `table-units-in-header` |
| No horizontal page overflow at 1280px, light and dark | `no-overflow-light/dark` |
| Georgia serif typography via the `gs-typo-unify-v1` block | — |

---

## D. Process rules for editing posts

These are not about the HTML; they are about not corrupting it.

1. **Verify against the live URL, never the editor UI.** The unsaved-changes
   cloud icon and the "saved" state both lie. Use
   `curl -s "<url>?cb=$RANDOM"` and grep for the change. The `?cb=` matters —
   blogspot is edge-cached.
2. **`setValue` alone does not mark the editor dirty.** Clicking Update after a
   programmatic edit is a silent no-op. Focus the CodeMirror body and press a
   real key (space, then backspace) before clicking Update.
3. **The Update button's real hit box centres at (1379, 100)** on a 1512px-wide
   window; its right edge is x≈1416. Clicking at x≈1448 — where the button
   *appears* — misses it. x≈1369 opens the dropdown instead.
4. **A "Leave site?" dialog on navigation is the honest signal** that the save
   did not land.
5. Blogger will accept a few dozen saves and then start silently rejecting
   everything. If several posts in a row refuse to save, stop and come back
   later rather than assuming the content is at fault.
6. **Syntax-check before saving**: extract `<script>` blocks and run
   `new Function(src)` on each. Do this in Node, not in the Blogger page — the
   page's CSP blocks `eval`, which produces a false "broken" result.
