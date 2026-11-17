"""Unit tests for body slicing and the repair helpers (no network)."""
import fix
from common import body_of

NESTED = "<html><div class='post-body'><div>a<div>b</div></div>tail</div><div>after</div></html>"


def test_body_of_balances_nested_divs():
    assert body_of(NESTED) == "<div class='post-body'><div>a<div>b</div></div>tail</div>"


def test_body_of_missing_returns_empty():
    assert body_of("<p>no body</p>") == ""


def test_strip_inverted_removes_nested_block():
    src = "a{} @media not all and (prefers-color-scheme:dark){ p{x:1} q{y:2} } b{}"
    out, n = fix.strip_inverted(src)
    assert n == 1 and "prefers-color-scheme" not in out and out.endswith("b{}")


def test_unsplice_disclaimer_lifts_paragraph_from_script():
    spliced = ("<script>var h='<div>'+x+'<p class=\"disclaimer\" data-gs-ai-disclosure-v1=\"1\">t</p>\n"
               "</div>';</script>")
    out, n = fix.unsplice_disclaimer(spliced)
    assert n == 1 and "data-gs-ai-disclosure" not in out


def test_light_lock_built_from_own_root_and_idempotent():
    src = "<style>:root{--text:#111;--surface:#fff}</style>"
    lock = fix.light_lock(src)
    assert "--text:#111!important" in lock and "gs-light-lock-v1" in lock
    assert fix.light_lock(src + lock) == ""
    assert fix.light_lock("<p>no root</p>") == ""


def test_lum_and_is_panel():
    assert fix._lum("#000") == 0 and abs(fix._lum("#ffffff") - 1) < 1e-9
    assert abs(fix._lum("rgb(255, 255, 255)") - 1) < 1e-9 and fix._lum("nonsense") is None
    assert not fix._is_panel("body") and not fix._is_panel(".post-body")
    assert fix._is_panel(".hero")


def test_add_translate_idempotent():
    out, added = fix.add_translate("<div class='post-body'>x</div>")
    assert added and "google_translate_element" in out
    assert fix.add_translate(out) == (out, False)


def test_repair_adds_disclosure_and_translate(monkeypatch):
    monkeypatch.setitem(fix._THEME_CACHE, "css", "")
    out, notes = fix.repair("<div class='post-body'><p>hi</p></div>")
    assert "data-gs-ai-disclosure-v1" in out and "google_translate_element" in out
    assert "added Google Translate widget" in notes
    assert fix.static_pass(out) == ["index-link"]
