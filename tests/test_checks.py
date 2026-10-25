"""Static rules in checks.py (pure) and CONTRAST_JS evaluated in node against
a stubbed DOM (no browser, no network)."""
import json
import shutil
import subprocess

import pytest

import checks as C

DISC = '<p class="disclaimer" data-gs-ai-disclosure-v1="1">AI</p>'


def test_disclaimer_inside_script_is_flagged_with_index():
    body = f"<script>var a=1;</script><script>var s='{DISC}';</script>"
    ok, detail = C.r_disclaimer_not_in_script(body)
    assert not ok and detail == "disclaimer inside <script> #[2]"
    assert C.r_disclaimer_not_in_script(f"<div>{DISC}</div>")[0]


def test_disclaimer_present_only_counts_outside_scripts():
    assert not C.r_disclaimer_present(f"<script>'{DISC}'</script>")[0]
    assert C.r_disclaimer_present(f"<script>x</script>{DISC}")[0]


def test_inverted_media_query_counted():
    body = "@media not all and (prefers-color-scheme:dark){a{}} @media not all and (prefers-color-scheme: dark){}"
    assert C.r_no_inverted_media_query(body) == (False, "2 inverted dark-mode media query block(s)")
    assert C.r_no_inverted_media_query("@media (prefers-color-scheme:dark){}")[0]


@pytest.mark.parametrize("body,ok", [
    ("<p>plain</p>", True),                                                       # no dark palette
    ("@media (prefers-color-scheme:dark){:root{--text:#eee}}", True),             # never consumed
    ("@media (prefers-color-scheme:dark){:root{--text:#eee}} p{color:var(--text)}", False),
    (":root{--text:#111!important} @media (prefers-color-scheme:dark){} p{color:var( --text)}", True),
    ('<style>/*gs-light-lock-v1*/</style><div data-theme="dark"></div> p{color:var(--ink)}', True),
])
def test_dark_vars_locked(body, ok):
    assert C.r_dark_vars_locked(body)[0] is ok


def test_bw_override_only_required_with_dark_palette():
    assert C.r_bw_override("<p>x</p>")[0]
    assert not C.r_bw_override('<div data-theme="dark">')[0]
    assert C.r_bw_override('<div data-theme="dark"><style>/*BW-OVERRIDE*/</style>')[0]


def test_translate_and_index_link():
    assert not C.r_translate_widget("x")[0] and C.r_translate_widget('id="google_translate_element"')[0]
    assert not C.r_index_link("x")[0] and C.r_index_link('class="topnav-index-link"')[0]


def test_table_units_threshold_is_30_percent():
    few = "<td>1 cr</td>" * 11
    assert C.r_table_units_in_header(few) == (True, "n/a (few cells)")
    cells = "<td>₹5</td>" * 3 + "<td>5</td>" * 7 + "<td>1</td>" * 2   # 3/12 = 25%
    assert C.r_table_units_in_header(cells)[0]
    cells = "<td><b>12%</b></td>" * 4 + "<td>5</td>" * 8                # 4/12 = 33%
    ok, detail = C.r_table_units_in_header(cells)
    assert not ok and detail == "33% of 12 cells carry units"


def test_scripts_parse_rule():
    assert C.r_scripts_parse("", node_check=None) == (True, "skipped (no node)")
    assert C.r_scripts_parse("", node_check=[]) == (True, "")
    assert C.r_scripts_parse("", node_check=[2]) == (False, "JS syntax error in script(s) [2]")


@pytest.mark.parametrize("body,ok", [
    ("no index here", True),
    ("The Wholesale Price Index (WPI) is released by MoSPI every month", False),
    ("MoSPI publishes the Wholesale Price Index", False),
    ("WPI is published by DPIIT; MoSPI publishes CPI.", True),
    ("Wholesale Price Index, compiled by MoSPI (WPI is not a MoSPI product)", True),
])
def test_wpi_attribution(body, ok):
    assert C.r_wpi_attribution(body)[0] is ok


def test_static_rules_table_is_complete_and_unique():
    names = [n for n, _, _ in C.STATIC_RULES]
    assert len(names) == len(set(names)) == 10
    assert {s for _, s, _ in C.STATIC_RULES} <= {C.BLOCKER, C.MAJOR, C.MINOR}


# ── CONTRAST_JS in node with a stub DOM ─────────────────────────────────

HARNESS = r"""
const spec = JSON.parse(process.argv[1]);
const els = spec.map(s => ({textContent: s.text, children: [], offsetParent: {},
  parentElement: {style: {backgroundColor: s.bg, backgroundImage: 'none'}, parentElement: null},
  style: {color: s.fg, backgroundColor: 'rgba(0, 0, 0, 0)', backgroundImage: 'none',
          fontSize: s.size, fontWeight: s.weight}}));
els.forEach(e => { e.parentElement.style.color = 'rgb(0, 0, 0)'; });
global.getComputedStyle = el => el.style;
global.document = {querySelectorAll: () => els};
const fn = eval(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(fn()));
"""

node = shutil.which("node")


def contrast(spec):
    r = subprocess.run([node, "-e", HARNESS, json.dumps(spec)], input=C.CONTRAST_JS,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


WHITE = "rgb(255, 255, 255)"


@pytest.mark.skipif(node is None, reason="node not installed")
def test_contrast_black_on_white_passes_and_white_on_white_fails():
    res = contrast([{"text": "readable", "fg": "rgb(0, 0, 0)", "bg": WHITE, "size": "16px", "weight": "400"},
                    {"text": "invisible", "fg": WHITE, "bg": WHITE, "size": "16px", "weight": "400"}])
    assert res["checked"] == 2 and res["fails"] == 1
    assert res["worst"][0]["text"] == "invisible" and res["worst"][0]["ratio"] == 1.0


@pytest.mark.skipif(node is None, reason="node not installed")
def test_contrast_normal_text_needs_wcag_aa_4_5_to_1():
    """WCAG 2.x SC 1.4.3: 4.5:1 for normal text. #828282 on white is 3.84:1,
    which passes a 3:1 check but fails AA for 16px body text."""
    res = contrast([{"text": "grey body copy", "fg": "rgb(130, 130, 130)", "bg": WHITE,
                     "size": "16px", "weight": "400"}])
    assert res["fails"] == 1, res


@pytest.mark.skipif(node is None, reason="node not installed")
@pytest.mark.parametrize("size,weight", [("24px", "400"), ("18.67px", "700")])
def test_contrast_large_text_needs_only_3_to_1(size, weight):
    res = contrast([{"text": "big heading", "fg": "rgb(130, 130, 130)", "bg": WHITE,
                     "size": size, "weight": weight}])
    assert res["fails"] == 0, res
