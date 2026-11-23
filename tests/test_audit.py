import json
import os
import sys
import types

import pytest

import audit
import checks
from . import fakes

BODY_HTML = "<html><div class='post-body'><div>inner</div><p>t</p></div><div>after</div></html>"


def test_body_of_single_quote_nested_divs():
    assert audit.body_of(BODY_HTML) == "<div class='post-body'><div>inner</div><p>t</p></div>"


def test_body_of_double_quote_and_missing_and_unbalanced():
    assert audit.body_of('<div class="post-body" id="x">a</div>tail') == '<div class="post-body" id="x">a</div>'
    assert audit.body_of("<p>no post body</p>") == ""
    assert audit.body_of("<div class='post-body'><div>never closed") == "<div class='post-body'><div>never closed"


def _feed(ids_titles):
    return json.dumps({"feed": {"entry": [
        {"id": {"$t": f"tag:blogger.com,1999:blog-1.post-{i}"}, "title": {"$t": t},
         "link": [{"rel": "replies", "href": "r"}, {"rel": "alternate", "href": f"http://b/{i}"}]}
        for i, t in ids_titles]}})


def test_post_list_paginates_dedupes_and_stops(monkeypatch):
    pages = {1: _feed([(11, "A"), (12, "B")]), 26: _feed([(12, "B again"), (13, "C")]), 51: json.dumps({"feed": {}})}
    calls = []

    def fake_sh(cmd):
        calls.append(cmd)
        i = int(cmd[-1].split("start-index=")[1].split("&")[0])
        return pages[i]

    monkeypatch.setattr(audit, "sh", fake_sh)
    posts = audit.post_list()
    assert [p["id"] for p in posts] == ["11", "12", "13"]
    assert posts[1]["title"] == "B" and posts[2]["url"] == "http://b/13"
    assert len(calls) == 3
    assert calls[0][:4] == ["curl", "-s", "-A", audit.UA]
    assert "max-results=25&alt=json" in calls[0][-1] and calls[0][-1].startswith(audit.BLOG)


def test_post_list_stops_on_bad_json(monkeypatch):
    seq = iter([_feed([(1, "x")]), "<html>not json"])
    monkeypatch.setattr(audit, "sh", lambda cmd: next(seq))
    assert [p["id"] for p in audit.post_list()] == ["1"]


def test_sh_and_fetch(monkeypatch):
    seen = []
    monkeypatch.setattr(audit.subprocess, "run",
                        lambda cmd, capture_output, text: (seen.append((cmd, capture_output, text)),
                                                           types.SimpleNamespace(stdout="OUT"))[1])
    assert audit.sh(["echo"]) == "OUT" and seen[0] == (["echo"], True, True)
    assert audit.fetch("http://u") == "OUT" and seen[1][0] == ["curl", "-s", "-A", audit.UA, "http://u"]


def test_js_syntax_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "OUT", str(tmp_path))
    calls = []
    monkeypatch.setattr(audit, "sh", lambda cmd: (calls.append(cmd), " [2, 4]\n")[1])
    tmp = str(tmp_path / "t.html")
    assert audit.js_syntax_errors("<html/>", tmp) == [2, 4]
    assert open(tmp).read() == "<html/>"
    script = tmp_path / "_syntax.js"
    assert "new Function" in script.read_text()
    assert calls[0] == ["node", str(script), tmp]
    # an existing script is not rewritten
    script.write_text("// custom")
    audit.js_syntax_errors("x", tmp)
    assert script.read_text() == "// custom"


def test_js_syntax_errors_bad_output(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "OUT", str(tmp_path))
    monkeypatch.setattr(audit, "sh", lambda cmd: "node: command not found")
    assert audit.js_syntax_errors("x", str(tmp_path / "t.html")) == []


def test_static_audit(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "OUT", str(tmp_path))
    html = "<html>" + BODY_HTML + "</html>"
    monkeypatch.setattr(audit, "fetch", lambda url: html)
    seen = {}
    monkeypatch.setattr(audit, "js_syntax_errors", lambda body, tmp: (seen.update(body=body, tmp=tmp), [3])[1])
    r = audit.static_audit({"id": "77", "title": "T", "url": "http://u"})
    assert seen["body"].startswith("<div class='post-body'>") and seen["tmp"].endswith("_t77.html")
    assert r["bytes"] == len(html) and r["id"] == "77"
    by = {c["rule"]: c for c in r["checks"]}
    assert len(by) == 10
    assert by["js-parses"]["ok"] is False and "[3]" in by["js-parses"]["detail"]
    assert by["no-inverted-media-query"]["ok"] is True
    assert by["translate-widget"]["ok"] is False and by["translate-widget"]["severity"] == "MINOR"


def test_static_audit_cleans_temp_file_and_isolates_rule_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "OUT", str(tmp_path))
    monkeypatch.setattr(audit, "fetch", lambda url: BODY_HTML)
    tmp = tmp_path / "_t5.html"

    def jse(body, tmpf):
        tmp.write_text("x")
        return []

    monkeypatch.setattr(audit, "js_syntax_errors", jse)

    def boom(body, node_check):
        raise KeyError("x")

    monkeypatch.setattr(audit, "STATIC_RULES", [("boom", checks.MAJOR, boom), ("ok", checks.MINOR, lambda **k: (True, ""))])
    r = audit.static_audit({"id": "5", "title": "t", "url": "u"})
    assert not tmp.exists()
    assert r["checks"] == [
        {"rule": "boom", "severity": "MAJOR", "ok": False, "detail": "rule error: KeyError"},
        {"rule": "ok", "severity": "MINOR", "ok": True, "detail": ""}]


def test_static_audit_missing_temp_file_tolerated(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "OUT", str(tmp_path))
    monkeypatch.setattr(audit, "fetch", lambda url: BODY_HTML)
    monkeypatch.setattr(audit, "js_syntax_errors", lambda body, tmp: [])
    assert audit.static_audit({"id": "9", "title": "t", "url": "u"})["checks"]


def _handler(contrast_fails=0, overflow=False):
    def h(js, arg):
        if js == checks.CONTRAST_JS:
            return {"checked": 10, "fails": contrast_fails, "worst": []}
        if js == checks.OVERFLOW_JS:
            return {"pageOverflow": overflow, "docW": 1500, "viewW": 1280, "wideEls": []}
        raise AssertionError(js)
    return h


def test_rendered_audit(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "SHOTS", str(tmp_path / "shots"))
    log = fakes.install(monkeypatch, _handler(2, True))
    posts = [{"id": "a", "url": "http://u/a"}, {"id": "b", "url": "http://u/BOOM"}]
    out = audit.rendered_audit(posts)
    assert set(out) == {("a", "light"), ("a", "dark"), ("b", "light"), ("b", "dark")}
    assert out[("a", "dark")]["contrast"]["fails"] == 2 and out[("a", "dark")]["overflow"]["pageOverflow"]
    assert out[("b", "light")] == {"error": "RuntimeError: navigation failed"}
    assert [e[1]["color_scheme"] for e in log if e[0] == "ctx"] == ["light", "dark"]
    assert all(e[1]["viewport"] == {"width": 1280, "height": 900} for e in log if e[0] == "ctx")
    assert not any(e[0] == "shot" for e in log)
    gotos = [e for e in log if e[0] == "goto"]
    assert gotos[0][2] == {"wait_until": "networkidle", "timeout": 45000}
    assert (tmp_path / "shots").is_dir() and log.count(("ctx-close",)) == 2 and log[-1] == ("br-close",)


def test_rendered_audit_baseline_screenshots(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "SHOTS", str(tmp_path / "s"))
    log = fakes.install(monkeypatch, _handler())
    audit.rendered_audit([{"id": "a", "url": "http://u/a"}], baseline=True)
    shots = [e for e in log if e[0] == "shot"]
    assert [os.path.basename(s[1]) for s in shots] == ["a.light.png", "a.dark.png"]
    assert all(s[2] is True for s in shots)


# ---------- main ----------
def _run_main(monkeypatch, tmp_path, argv, posts, rules_ok=True, rendered=None):
    monkeypatch.setattr(audit, "OUT", str(tmp_path / "out"))
    monkeypatch.setattr(audit, "post_list", lambda: posts)

    def sa(post):
        ok = rules_ok if not callable(rules_ok) else rules_ok(post)
        return {**post, "bytes": 1, "checks": [
            {"rule": "js-parses", "severity": "BLOCKER", "ok": ok, "detail": "" if ok else "bad js"},
            {"rule": "index-link", "severity": "MINOR", "ok": True, "detail": ""}]}

    monkeypatch.setattr(audit, "static_audit", sa)
    if rendered is not None:
        monkeypatch.setattr(audit, "rendered_audit", lambda ps, baseline=False: rendered)
    monkeypatch.setattr(sys, "argv", ["audit.py", *argv])
    audit.main()


POSTS = [{"id": "1", "title": "First", "url": "http://u/1"}, {"id": "2", "title": "Second", "url": "http://u/2"}]


def test_main_clean_run_writes_reports(monkeypatch, tmp_path, capsys):
    _run_main(monkeypatch, tmp_path, [], POSTS)
    out = capsys.readouterr().out
    assert "auditing 2 posts" in out and "full report:" in out and "BLOCKER failures" not in out
    rep = (tmp_path / "out" / "report.md").read_text()
    assert "posts audited: **2** · posts with at least one failure: **0**" in rep
    assert "| BLOCKER | `js-parses` | 0 | 2 |" in rep and "| MINOR | `index-link` | 0 | 2 |" in rep
    assert len(json.loads((tmp_path / "out" / "report.json").read_text())) == 2


def test_main_blocker_exits_1_and_lists_posts(monkeypatch, tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        _run_main(monkeypatch, tmp_path, [], POSTS, rules_ok=lambda p: p["id"] != "2")
    assert e.value.code == 1
    out = capsys.readouterr().out
    assert "1 BLOCKER failures" in out
    rep = (tmp_path / "out" / "report.md").read_text()
    assert "posts with at least one failure: **1**" in rep
    assert "### Second\nhttp://u/2\n- **BLOCKER** `js-parses` — bad js" in rep and "### First" not in rep
    assert "| BLOCKER | `js-parses` | 1 | 2 |" in rep


def test_main_orders_failures_by_severity_then_count(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "OUT", str(tmp_path / "out"))
    monkeypatch.setattr(audit, "post_list", lambda: [{"id": "m", "title": "minor-only", "url": "m"},
                                                      {"id": "b", "title": "blocker", "url": "b"}])

    def sa(post):
        if post["id"] == "m":
            cs = [{"rule": "x", "severity": "MINOR", "ok": False, "detail": ""},
                  {"rule": "y", "severity": "MINOR", "ok": False, "detail": ""}]
        else:
            cs = [{"rule": "z", "severity": "BLOCKER", "ok": False, "detail": ""}]
        return {**post, "checks": cs}

    monkeypatch.setattr(audit, "static_audit", sa)
    monkeypatch.setattr(sys, "argv", ["audit.py"])
    with pytest.raises(SystemExit):
        audit.main()
    rep = (tmp_path / "out" / "report.md").read_text()
    assert rep.index("### blocker") < rep.index("### minor-only")


def test_main_limit_url_and_urls_file(monkeypatch, tmp_path, capsys):
    many = [{"id": str(i), "title": f"t{i}", "url": f"u{i}"} for i in range(5)]
    _run_main(monkeypatch, tmp_path, ["--limit", "2"], many)
    assert "auditing 2 posts" in capsys.readouterr().out
    _run_main(monkeypatch, tmp_path, ["--url", "http://x/y/post.html"], [])
    assert "auditing 1 posts" in capsys.readouterr().out
    uf = tmp_path / "urls.txt"
    uf.write_text("http://a/1.html\n\n  http://a/2.html  \n")
    _run_main(monkeypatch, tmp_path, ["--urls-file", str(uf)], [])
    assert "auditing 2 posts" in capsys.readouterr().out
    rep = json.loads((tmp_path / "out" / "report.json").read_text())
    assert [r["title"] for r in rep] == ["1.html", "2.html"]
    assert rep[0]["id"] == __import__("hashlib").md5(b"http://a/1.html").hexdigest()[:8]


def test_main_priority_prescreen(monkeypatch, tmp_path, capsys):
    posts = [{"id": str(i), "title": f"t{i}", "url": f"u{i}"} for i in range(3)]
    monkeypatch.setattr(audit, "OUT", str(tmp_path / "out"))
    monkeypatch.setattr(audit, "post_list", lambda: posts)

    def sa(post):
        both = post["id"] == "1"
        one = post["id"] == "2"
        return {**post, "checks": [
            {"rule": "no-inverted-media-query", "severity": "BLOCKER", "ok": not (both or one), "detail": ""},
            {"rule": "dark-vars-locked", "severity": "BLOCKER", "ok": not both, "detail": ""}]}

    monkeypatch.setattr(audit, "static_audit", sa)
    monkeypatch.setattr(sys, "argv", ["audit.py", "--priority"])
    with pytest.raises(SystemExit):
        audit.main()
    assert "auditing 1 posts" in capsys.readouterr().out


def test_main_rendered_adds_contrast_and_overflow_checks(monkeypatch, tmp_path, capsys):
    rend = {("1", "light"): {"contrast": {"checked": 50, "fails": 3, "worst": []},
                              "overflow": {"pageOverflow": True, "docW": 1400, "viewW": 1280, "wideEls": []}},
            ("1", "dark"): {"contrast": {"checked": 50, "fails": 0, "worst": []},
                             "overflow": {"pageOverflow": False, "docW": 1, "viewW": 1, "wideEls": []}},
            ("2", "light"): {"error": "boom"}}
    with pytest.raises(SystemExit):
        _run_main(monkeypatch, tmp_path, ["--rendered"], POSTS, rendered=rend)
    rep = (tmp_path / "out" / "report.md").read_text()
    assert "`contrast-light` — 3/50 nodes below 3:1" in rep
    assert "`no-overflow-light` — doc 1400px > view 1280px" in rep
    assert "contrast-dark` | 0 | 1 |" in rep
    res = json.loads((tmp_path / "out" / "report.json").read_text())
    dark = [c for c in res[0]["checks"] if c["rule"] == "contrast-dark"][0]
    assert dark["detail"] == "0/50" and dark["ok"] is True
    assert not [c for c in res[1]["checks"] if c["rule"].startswith("contrast")]   # errored post: no rendered rows


def test_main_contrast_one_failing_node_is_a_failure(monkeypatch, tmp_path):
    rend = {("1", "light"): {"contrast": {"checked": 5, "fails": 1, "worst": []},
                              "overflow": {"pageOverflow": False, "docW": 1, "viewW": 1, "wideEls": []}}}
    with pytest.raises(SystemExit):
        _run_main(monkeypatch, tmp_path, ["--rendered"], POSTS[:1], rendered=rend)
    res = json.loads((tmp_path / "out" / "report.json").read_text())
    c = {x["rule"]: x for x in res[0]["checks"]}
    assert c["contrast-light"]["ok"] is False and c["contrast-light"]["severity"] == "BLOCKER"
    assert c["no-overflow-light"]["ok"] is True and c["no-overflow-light"]["severity"] == "MINOR"


def test_main_uses_eight_workers(monkeypatch, tmp_path):
    seen = []

    class Pool:
        def __init__(self, max_workers):
            seen.append(max_workers)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def map(self, fn, it):
            return map(fn, it)

    monkeypatch.setattr(audit, "ThreadPoolExecutor", Pool)
    _run_main(monkeypatch, tmp_path, [], POSTS)
    assert seen == [8]


def test_main_same_severity_sorted_by_failure_count_desc(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "OUT", str(tmp_path / "out"))
    monkeypatch.setattr(audit, "post_list", lambda: [{"id": "1", "title": "one-fail", "url": "1"},
                                                      {"id": "2", "title": "three-fails", "url": "2"}])

    def sa(post):
        n = 1 if post["id"] == "1" else 3
        return {**post, "checks": [{"rule": f"r{i}", "severity": "MINOR", "ok": False, "detail": ""} for i in range(n)]}

    monkeypatch.setattr(audit, "static_audit", sa)
    monkeypatch.setattr(sys, "argv", ["audit.py"])
    audit.main()
    rep = (tmp_path / "out" / "report.md").read_text()
    assert rep.index("### three-fails") < rep.index("### one-fail")


def test_main_baseline_implies_rendered(monkeypatch, tmp_path):
    called = {}
    monkeypatch.setattr(audit, "OUT", str(tmp_path / "out"))
    monkeypatch.setattr(audit, "post_list", lambda: POSTS)
    monkeypatch.setattr(audit, "static_audit", lambda p: {**p, "checks": []})
    monkeypatch.setattr(audit, "rendered_audit", lambda ps, baseline=False: (called.update(b=baseline), {})[1])
    monkeypatch.setattr(sys, "argv", ["audit.py", "--baseline"])
    audit.main()
    assert called == {"b": True}
