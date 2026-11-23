import json
import sys
import types

import pytest

import checks
import fix
from . import fakes


@pytest.fixture(autouse=True)
def _no_theme_fetch(monkeypatch):
    """dark_panel_guard consults the live theme; never hit the network."""
    monkeypatch.setattr(fix, "theme_css", lambda: "")
    fix._THEME_CACHE.clear()


# ---------- body_of ----------
def test_body_of():
    assert fix.body_of("<div class='post-body'><div>x</div></div>tail") == "<div class='post-body'><div>x</div></div>"
    assert fix.body_of('<div class="post-body">a</div>z') == '<div class="post-body">a</div>'
    assert fix.body_of("none") == ""
    assert fix.body_of("<div class='post-body'><div>open") == "<div class='post-body'><div>open"


# ---------- strip_inverted ----------
def test_strip_inverted_balanced_braces():
    src = "a{} " + checks.INVERTED_MQ + ":dark){ .x{color:#fff} .y{a:b} } b{}"
    out, n = fix.strip_inverted(src)
    assert n == 1 and out == "a{} /* gs-fix: removed inverted dark-mode block (it matched in LIGHT mode) */ b{}"


def test_strip_inverted_none_and_malformed():
    assert fix.strip_inverted("a{}") == ("a{}", 0)
    assert fix.strip_inverted("x " + checks.INVERTED_MQ) == ("x " + checks.INVERTED_MQ, 0)   # no '{' at all


def test_strip_inverted_loop_cap_is_nine():
    blk = checks.INVERTED_MQ + ":dark){.a{b:c}}"
    out, n = fix.strip_inverted(blk * 11)
    assert n == 9 and out.count(checks.INVERTED_MQ) == 2


def test_strip_inverted_unterminated_block_runs_to_end():
    out, n = fix.strip_inverted("a " + checks.INVERTED_MQ + ":dark){ .x{y:z}")
    assert n == 1 and out == "a /* gs-fix: removed inverted dark-mode block (it matched in LIGHT mode) */"


# ---------- unsplice_disclaimer ----------
def test_unsplice_primary_pattern():
    s = ("<script>var h='<div>'+x+'<p class=\"disclaimer\" data-gs-ai-disclosure-v1=\"1\" style=\"s\">T</p>\n</div>';"
         "</script>")
    out, n = fix.unsplice_disclaimer(s)
    assert n == 1 and out == "<script>var h='<div>'+x+'</div>';</script>"


def test_unsplice_fallback_scrubs_only_scripts():
    spliced = '<p class="disclaimer" data-gs-ai-disclosure-v1="1">T</p>'
    s = f"<script>var a='{spliced}';</script>{spliced}"
    out, n = fix.unsplice_disclaimer(s)
    assert n == 1
    assert out == f"<script>var a='';</script>{spliced}"      # the copy outside the script survives


def test_unsplice_nothing_to_do():
    assert fix.unsplice_disclaimer("<script>1</script>") == ("<script>1</script>", 0)
    s = "<script>var a=1;</script>"
    assert fix.unsplice_disclaimer(s)[1] == 0


# ---------- light_lock ----------
def test_light_lock_from_root():
    out = fix.light_lock("<style>:root{--a:#fff;--b: red ;x:y}</style>")
    assert out.startswith("\n<style>/*gs-light-lock-v1*/:root,:root[data-theme=\"dark\"],:root[data-theme=\"light\"]{")
    assert "--a:#fff!important;--b:red!important;" in out and out.endswith("color-scheme:light!important;}</style>")


def test_light_lock_prefers_light_theme_rule():
    src = ':root{--a:#000} :root[data-theme="light"]{--a:#eee}'
    out = fix.light_lock(src)
    assert "--a:#eee!important" in out and "#000" not in out


def test_light_lock_skips():
    assert fix.light_lock("gs-light-lock-v1 :root{--a:1}") == ""
    assert fix.light_lock("p{x:y}") == ""
    assert fix.light_lock(":root{color:red}") == ""      # no custom properties


# ---------- _lum ----------
@pytest.mark.parametrize("c,v", [("#fff", 1.0), ("#000000", 0.0), (" #ffffff ", 1.0), ("rgb(255, 0, 0)", 0.2126),
                                  ("rgba(0,255,0,.5)", 0.7152), ("rgb(0 0 255 / 50%)", None)])
def test_lum_values(c, v):
    got = fix._lum(c)
    assert (got is None) if v is None else abs(got - v) < 1e-9


@pytest.mark.parametrize("c", ["#ab", "#gggggg", "rgb(1,2)", "hsl(0,0%,0%)", "red", "rgb(a,b,c)"])
def test_lum_invalid(c):
    assert fix._lum(c) is None


def test_lum_slash_separator():
    assert abs(fix._lum("rgb(255,255,255/0.5)") - 1.0) < 1e-9


# ---------- _is_panel ----------
@pytest.mark.parametrize("sel,expected", [
    ("body", False), ("html", False), (":root", False), ("*", False), ("select", False), ("input", False),
    ("textarea", False), ("option", False), (".post-body", False), (".artx", False), (".post", False),
    ("article", False), ("main", False), (".POST-BODY", False), (".artx >", False), ("section", False),
    (".hero", True), ("#panel", True), ("div p", True), ("a:hover", True), ("[data-x]", True),
])
def test_is_panel(sel, expected):
    assert fix._is_panel(sel) is expected


# ---------- dark_panel_guard ----------
def test_guard_no_css_or_no_dark():
    assert fix.dark_panel_guard("<p>no style</p>") == ""
    assert fix.dark_panel_guard("<style>.a{background:#fff}</style>") == ""
    assert fix.dark_panel_guard("<style>.a{color:red}</style>") == ""


def test_guard_emits_three_rules_per_panel_with_resolved_colour():
    css = ".hero{background:#112233} .card{background:var(--panel)} :root{--panel:#222222} body{background:#000} .l{background:#fff}"
    out = fix.dark_panel_guard(f"<style>{css}</style>")
    assert out.startswith("\n<style>/*gs-dark-panel-guard*/") and out.endswith("</style>")
    assert ".hero{background:#112233!important}" in out
    assert ".hero,.hero *{color:#fff!important}" in out
    assert ".hero a,.hero a *{color:#cfe3ff!important}" in out
    assert ".card{background:#222222!important}" in out and "var(" not in out
    assert "body" not in out and ".l{" not in out


def test_guard_threshold_boundary():
    dark = fix.dark_panel_guard("<style>.a{background:#6b6b6b}</style>")      # lum 0.4196 < 0.42
    light = fix.dark_panel_guard("<style>.a{background:#6c6c6c}</style>")     # lum 0.4235
    assert ".a{background:#6b6b6b!important}" in dark and light == ""


def test_guard_averages_gradient_stops_and_selector_list_and_dedup():
    css = ".a,.b{background:linear-gradient(#000,#fff)} .a{background:#000} .c{background-image:linear-gradient(#000,#111)}"
    out = fix.dark_panel_guard(f"<style>{css}</style>")
    assert ".a{background:" in out and out.count(".a{background:") == 1       # deduped
    assert ".c{background:linear-gradient(#000,#111)!important}" in out
    assert ".b{" not in out                                                   # avg lum 0.5 -> not dark


def test_guard_skips_at_rules_root_long_selectors_and_non_background():
    long_sel = "." + "x" * 80
    css = f"@media x{{.a{{background:#000}}}} :root{{background:#000}} {long_sel}{{background:#000}} .n{{color:#000}} .z{{background:none}}"
    assert fix.dark_panel_guard(f"<style>{css}</style>") == ""


def test_guard_resolves_vars_from_theme_and_chains(monkeypatch):
    monkeypatch.setattr(fix, "theme_css", lambda: ":root{--h1:#101010}")
    out = fix.dark_panel_guard("<style>.hero{background:var(--h1)} .c{background:var(--a)} :root{--a:var(--b);--b:#050505}</style>")
    assert ".hero{background:#101010!important}" in out
    assert ".c{background:#050505!important}" in out


def test_guard_var_chain_depth_limit():
    four = "<style>.x{background:var(--a)} :root{--a:var(--b);--b:var(--c);--c:var(--d);--d:#000000}</style>"
    five = "<style>.x{background:var(--a)} :root{--a:var(--b);--b:var(--c);--c:var(--d);--d:var(--e);--e:#000000}</style>"
    assert ".x{background:#000000!important}" in fix.dark_panel_guard(four)
    assert fix.dark_panel_guard(five) == ""


def test_sh_runs_subprocess(monkeypatch):
    seen = []
    monkeypatch.setattr(fix.subprocess, "run", lambda c, capture_output, text: (seen.append((c, capture_output, text)),
                                                                                   types.SimpleNamespace(stdout="o"))[1])
    assert fix.sh(["x"]) == "o" and seen == [(["x"], True, True)]


def test_guard_unresolvable_var_is_skipped():
    assert fix.dark_panel_guard("<style>.a{background:var(--nope)}</style>") == ""


def test_guard_post_vars_win_over_theme(monkeypatch):
    monkeypatch.setattr(fix, "theme_css", lambda: ":root{--p:#ffffff}")
    out = fix.dark_panel_guard("<style>:root{--p:#000000} .a{background:var(--p)}</style>")
    assert ".a{background:#000000!important}" in out


# ---------- add_translate ----------
def test_add_translate_variants():
    t = fix.TRANSLATE
    src = '<div class="wrap other">X</div>'
    out, added = fix.add_translate(src)
    assert added and out == '<div class="wrap other">' + "\n" + t + "X</div>"
    out, added = fix.add_translate("<div class='post-body'>X")
    assert added and out == "<div class='post-body'>\n" + t + "X"
    out, added = fix.add_translate("<p>plain</p>")
    assert added and out == t + "\n<p>plain</p>"
    assert fix.add_translate("google_translate_element") == ("google_translate_element", False)
    # wrapper class names must match as whole words
    out, _ = fix.add_translate('<div class="artxy">X</div>')
    assert out.startswith(t)


# ---------- repair / static_pass ----------
def test_repair_full_pipeline():
    spliced = '<p class="disclaimer" data-gs-ai-disclosure-v1="1" style="s">T</p>\n'
    body = ("<div class='post-body'><style>:root{--surface:#fff;--p:#111111} .hero{background:#112233}"
            + checks.INVERTED_MQ + ":dark){.x{color:#fff}} p{color:var(--surface)}</style>"
            "<script>var h='<div>'+x+'" + spliced + "</div>';</script></div>")
    fixed, notes = fix.repair(body)
    assert notes[0] == "removed 1 inverted media-query block(s)"
    assert notes[1] == "lifted 1 disclaimer(s) out of <script>"
    assert notes[2] == "appended light-lock from the post's own :root"
    assert notes[3].startswith("dark-panel guard (")
    assert notes[4:] == ["added Google Translate widget", "appended AI disclosure at end of body"]
    assert checks.INVERTED_MQ not in fixed and "gs-light-lock-v1" in fixed and "gs-dark-panel-guard" in fixed
    assert fixed.rstrip().endswith("</p>") and fixed.count("data-gs-ai-disclosure-v1") == 1
    assert fix.static_pass(fixed) == ["index-link"]
    # idempotent apart from the translate widget/disclosure already being present
    again, notes2 = fix.repair(fixed)
    assert notes2 == [] and again == fixed


def test_repair_clean_post_only_adds_translate_and_disclosure():
    out, notes = fix.repair("<div class='post-body'>hello</div>")
    assert notes == ["added Google Translate widget", "appended AI disclosure at end of body"]
    assert out.endswith(fix.DISCLAIMER)


def test_repair_keeps_existing_disclosure():
    body = "<div class='post-body'>" + fix.DISCLAIMER + "google_translate_element</div>"
    out, notes = fix.repair(body)
    assert notes == [] and out == body


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="fix.py repair(): the note counts commas in the guard CSS (`guard.count(',') // 2 + 1`), "
                          "which is 2 per selector, so one dark panel is reported as '2 selectors kept dark'")
def test_repair_guard_note_counts_selectors():
    _, notes = fix.repair("<div class='post-body'><style>.hero{background:#112233}</style></div>")
    assert [n for n in notes if n.startswith("dark-panel")] == ["dark-panel guard (1 selectors kept dark)"]


def test_static_pass(monkeypatch):
    clean = ('<div id="google_translate_element"></div><div class="topnav-index-link"></div>' + fix.DISCLAIMER)
    assert fix.static_pass(clean) == []
    assert fix.static_pass("x") == ["disclaimer-present", "translate-widget", "index-link"]

    def boom(**kw):
        raise RuntimeError

    monkeypatch.setattr(fix, "STATIC_RULES", [("a", "BLOCKER", boom), ("b", "MINOR", lambda **k: (True, ""))])
    assert fix.static_pass("x") == ["a"]


# ---------- theme_css ----------
def test_theme_css_page_skin_and_cache(monkeypatch):
    monkeypatch.undo()          # drop the autouse stub for this test
    fix._THEME_CACHE.clear()
    calls = []
    html = ("<style>ignored{}</style><style type='text/css' id='page-skin-1'><!-- a{b:c} --></style>"
            "<style id='page-skin-1'>d{e:f}</style>")
    monkeypatch.setattr(fix, "sh", lambda cmd: (calls.append(cmd), html)[1])
    css = fix.theme_css()
    assert css == " a{b:c} \nd{e:f}" and "<!--" not in css and "-->" not in css
    assert fix.theme_css() is css and len(calls) == 1
    assert calls[0] == ["curl", "-s", "-A", fix.UA, "https://masaladeutsch.blogspot.com/"]
    fix._THEME_CACHE.clear()


def test_theme_css_fallback_first_three_styles(monkeypatch):
    monkeypatch.undo()
    fix._THEME_CACHE.clear()
    monkeypatch.setattr(fix, "sh", lambda cmd: "".join(f"<style>s{i}{{}}</style>" for i in range(5)))
    assert fix.theme_css() == "s0{}\ns1{}\ns2{}"
    fix._THEME_CACHE.clear()


# ---------- serve ----------
def test_serve_binds_loopback_and_runs_thread(monkeypatch):
    made = {}

    class FakeTCP:
        def __init__(self, addr, handler):
            made["addr"] = addr
            made["handler"] = handler
            self.started = False

        def serve_forever(self):
            made["served"] = True

    monkeypatch.setattr(fix.socketserver, "TCPServer", FakeTCP)

    class ImmediateThread:
        def __init__(self, target, daemon):
            made["daemon"] = daemon
            self.t = target

        def start(self):
            self.t()

    monkeypatch.setattr(fix.threading, "Thread", ImmediateThread)
    httpd = fix.serve("/some/dir", 8123)
    assert made["addr"] == ("127.0.0.1", 8123) and made["daemon"] is True and made["served"] is True
    assert isinstance(httpd, FakeTCP) and callable(made["handler"])
    fix._Q.log_message(None)      # silent logger


# ---------- verify_live / verify ----------
def _contrast_seq(*vals):
    it = iter(vals)

    def h(js, arg):
        if js == checks.CONTRAST_JS:
            f = next(it)
            return {"fails": f, "checked": 5, "worst": []}
        return True
    return h


def test_verify_live_swaps_body_and_measures(monkeypatch):
    log = fakes.install(monkeypatch, _contrast_seq(4, 0, 2, 2))
    meta = [{"id": "a", "url": "http://u/a"}, {"id": "b", "url": "http://u/b"}]
    pairs = [("a", "old", "NEW_A"), ("b", "old", "NEW_B")]
    out = fix.verify_live(meta, pairs)
    assert out["a"][0]["fails"] == 4 and out["a"][1]["fails"] == 0
    assert out["b"][0]["fails"] == 2 and out["b"][1]["fails"] == 2
    assert [e for e in log if e[0] == "eval" and e[1] == "arg"] == [("eval", "arg")] * 2
    assert log[0] == ("ctx", {"viewport": {"width": 1280, "height": 900}, "color_scheme": "light", "user_agent": fix.UA})
    assert log[-1] == ("br-close",)


def test_verify_live_errors_become_minus_one(monkeypatch):
    fakes.install(monkeypatch, _contrast_seq())
    out = fix.verify_live([{"id": "x", "url": "http://u/BOOM"}], [("x", "o", "n")])
    assert out["x"] == ({"fails": -1, "checked": 0}, {"fails": -1, "checked": 0})


def test_verify_offline_harness(monkeypatch, tmp_path):
    monkeypatch.setattr(fix, "FIXES", str(tmp_path))
    monkeypatch.setattr(fix, "theme_css", lambda: "T{}")
    served = {}

    class H:
        def shutdown(self):
            served["down"] = True

    monkeypatch.setattr(fix, "serve", lambda d, port: (served.update(dir=d, port=port), H())[1])
    log = fakes.install(monkeypatch, _contrast_seq(7, 1))
    res = fix.verify([("p1", "BEFORE", "AFTER")], port=8999)
    assert res["p1"][0]["fails"] == 7 and res["p1"][1]["fails"] == 1
    d = tmp_path / "_verify"
    assert (d / "p1.before.html").read_text() == fix.PAGE.replace("{THEME}", "T{}").replace("{BODY}", "BEFORE")
    assert "AFTER" in (d / "p1.after.html").read_text()
    assert served == {"dir": str(d), "port": 8999, "down": True}
    gotos = [e[1] for e in log if e[0] == "goto"]
    assert gotos == ["http://127.0.0.1:8999/p1.before.html", "http://127.0.0.1:8999/p1.after.html"]


def test_verify_offline_error_isolated_and_server_stopped(monkeypatch, tmp_path):
    monkeypatch.setattr(fix, "FIXES", str(tmp_path))
    down = []
    monkeypatch.setattr(fix, "serve", lambda d, port: types.SimpleNamespace(shutdown=lambda: down.append(1)))
    fakes.install(monkeypatch, _contrast_seq())
    # pid containing BOOM makes the fake page raise on goto
    res = fix.verify([("BOOM", "b", "a")])
    assert res["BOOM"] == ({"fails": -1, "checked": 0}, {"fails": -1, "checked": 0}) and down == [1]


def test_contrast_of(monkeypatch):
    log = fakes.install(monkeypatch, _contrast_seq(3))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        pg = p.chromium.launch().new_context().new_page()
        assert fix.contrast_of(pg, "http://x")["fails"] == 3
    assert ("goto", "http://x", {"wait_until": "load", "timeout": 30000}) in log and ("wait", 400) in log


# ---------- main ----------
POST = "<html><div class='post-body'><p>hello</p></div></html>"


def _main(monkeypatch, tmp_path, argv, html_for=lambda u: POST, verify_result=None):
    fx = tmp_path / "fixes"
    monkeypatch.setattr(fix, "FIXES", str(fx))
    monkeypatch.setattr(fix, "sh", lambda cmd: html_for(cmd[-1]))
    if verify_result is not None:
        monkeypatch.setattr(fix, "verify_live", lambda meta, pairs: {m["id"]: verify_result(m) for m in meta})
    monkeypatch.setattr(sys, "argv", ["fix.py", *argv])
    fix.main()
    return fx


def test_main_no_verify_writes_files_and_manifest(monkeypatch, tmp_path, capsys):
    fx = _main(monkeypatch, tmp_path, ["--url", "http://b/2026/08/my-post.html", "--no-verify"])
    out = capsys.readouterr().out
    assert "repairing 1 posts" in out and "my-post" in out and "Nothing was uploaded" in out
    assert "verifying" not in out
    assert "hello" in (fx / "my-post.html").read_text()
    man = json.loads((fx / "manifest.json").read_text())
    assert man[0]["slug"] == "my-post" and man[0]["path"] == str(fx / "my-post.html")
    assert man[0]["url"] == "http://b/2026/08/my-post.html" and len(man[0]["id"]) == 8
    assert "added Google Translate widget" in man[0]["notes"]
    assert "translate-widget" in man[0]["before"] and "translate-widget" not in man[0]["after"]


def test_main_urls_file_and_missing_body(monkeypatch, tmp_path, capsys):
    uf = tmp_path / "u.txt"
    uf.write_text("http://b/ok.html\n\nhttp://b/bad.html\n")
    fx = _main(monkeypatch, tmp_path, ["--urls-file", str(uf), "--no-verify"],
               html_for=lambda u: POST if "ok" in u else "<html>no body</html>")
    out = capsys.readouterr().out
    assert "repairing 2 posts" in out and "!! could not extract body: http://b/bad.html" in out
    assert [m["slug"] for m in json.loads((fx / "manifest.json").read_text())] == ["ok"]


def _verdicts(monkeypatch, tmp_path, capsys, results):
    uf = tmp_path / "u.txt"
    uf.write_text("\n".join(f"http://b/{k}.html" for k in results) + "\n")
    _main(monkeypatch, tmp_path, ["--urls-file", str(uf)],
          verify_result=lambda m: results[m["slug"]])
    return capsys.readouterr().out


def test_main_verdicts(monkeypatch, tmp_path, capsys):
    f = lambda b, a: ({"fails": b}, {"fails": a})  # noqa: E731
    out = _verdicts(monkeypatch, tmp_path, capsys, {
        "fixed": f(5, 0), "clean": f(0, 0), "better": f(9, 4), "same": f(3, 3), "worse": f(1, 2), "err": f(1, -1)})
    line = {k: [l for l in out.splitlines() if l.startswith(k)][0] for k in ("fixed", "clean", "better", "same", "worse", "err")}
    assert line["fixed"].rstrip().endswith("FIXED") and line["clean"].rstrip().endswith("already clean")
    assert line["better"].rstrip().endswith("improved (5 fewer)")
    assert line["same"].rstrip().endswith("NOT FIXED") and line["worse"].rstrip().endswith("NOT FIXED")
    assert line["err"].rstrip().endswith("render error")
    assert "some posts need manual attention" in out and "\nall repaired" not in out


def test_main_all_repaired_message_and_contrast_recorded(monkeypatch, tmp_path, capsys):
    f = lambda b, a: ({"fails": b}, {"fails": a})  # noqa: E731
    out = _verdicts(monkeypatch, tmp_path, capsys, {"a": f(5, 0), "b": f(0, 0)})
    assert "\nall repaired" in out and "some posts need" not in out
    man = json.loads((tmp_path / "fixes" / "manifest.json").read_text())
    assert (man[0]["contrast_before"], man[0]["contrast_after"]) == (5, 0)


def test_main_does_not_verify_when_nothing_repaired(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(fix, "verify_live", lambda *a: pytest.fail("verify_live called"))
    _main(monkeypatch, tmp_path, ["--url", "http://b/x.html"], html_for=lambda u: "<html/>")
    assert "verifying" not in capsys.readouterr().out
