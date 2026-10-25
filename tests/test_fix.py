"""Pure repair helpers in fix.py (theme_css stubbed: no network)."""
import pytest

import fix
from checks import INVERTED_MQ


@pytest.fixture(autouse=True)
def no_theme(monkeypatch):
    monkeypatch.setattr(fix, "theme_css", lambda: "")


def test_strip_inverted_handles_nested_braces():
    src = f"a{{}} {INVERTED_MQ}:dark){{ .x{{color:#eee}} .y{{color:#ddd}} }} b{{}}"
    out, n = fix.strip_inverted(src)
    assert n == 1
    assert INVERTED_MQ not in out and "#eee" not in out
    assert out.startswith("a{} /* gs-fix") and out.endswith(" b{}")


def test_strip_inverted_noop():
    assert fix.strip_inverted("p{}") == ("p{}", 0)


def test_unsplice_disclaimer_restores_script():
    d = '<p class="disclaimer" data-gs-ai-disclosure-v1="1">AI</p>'
    src = f"<script>var h='<div>' + v + '{d}\n</div>';</script>"
    out, n = fix.unsplice_disclaimer(src)
    assert n == 1 and "disclosure" not in out
    assert out == "<script>var h='<div>' + v + '</div>';</script>"


def test_light_lock_from_posts_own_root():
    lock = fix.light_lock("<style>:root{--text:#111; --bg: #fff}</style>")
    assert "--text:#111!important;--bg:#fff!important;" in lock
    assert "gs-light-lock-v1" in lock
    assert fix.light_lock("<style>p{}</style>") == ""
    assert fix.light_lock("/*gs-light-lock-v1*/ :root{--a:1}") == ""


@pytest.mark.parametrize("sel,panel", [
    ("body", False), (".post-body", False), ("main", False), ("div", False),
    (".hero", True), ("#stat", True), (".card .inner", True),
])
def test_is_panel(sel, panel):
    assert fix._is_panel(sel) is panel


def test_lum_parses_hex_and_rgb():
    assert fix._lum("#fff") == pytest.approx(1.0)
    assert fix._lum("rgb(0, 0, 0)") == 0
    assert fix._lum("#12") is None and fix._lum("red") is None


def test_dark_panel_guard_keeps_dark_panels_resolving_vars():
    src = ("<style>:root{--panel:#0b1220} .hero{background:var(--panel)} "
           "body{background:#000} .light{background:#fafafa}</style>")
    g = fix.dark_panel_guard(src)
    assert ".hero{background:#0b1220!important}" in g
    assert ".hero,.hero *{color:#fff!important}" in g
    assert "body" not in g and ".light" not in g
    assert fix.dark_panel_guard("<p>no css</p>") == ""


def test_add_translate_placement_and_idempotence():
    out, added = fix.add_translate('<div class="artx big"><p>x</p></div>')
    assert added and out.startswith('<div class="artx big">\n<div id="google_translate_element"')
    assert fix.add_translate(out) == (out, False)
    out, _ = fix.add_translate("<p>bare</p>")
    assert out.startswith('<div id="google_translate_element"')


def test_repair_clears_static_blockers():
    d = '<p class="disclaimer" data-gs-ai-disclosure-v1="1">AI</p>'
    body = (f"<style>:root{{--text:#111}} {INVERTED_MQ}:dark){{:root{{--text:#eee}}}} "
            f"p{{color:var(--text)}}</style><div class=\"artx\"><script>var s='{d}';</script></div>")
    before = fix.static_pass(body)
    assert {"no-inverted-media-query", "no-disclaimer-in-script", "disclaimer-present"} <= set(before)
    out, notes = fix.repair(body)
    after = fix.static_pass(out)
    for rule in ("no-inverted-media-query", "no-disclaimer-in-script", "dark-vars-locked",
                 "disclaimer-present", "translate-widget"):
        assert rule not in after, (rule, notes)
