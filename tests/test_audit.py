"""audit.py: post-body scoping, static audit wiring, and the rendered pass
with a fake Playwright (no browser, no network)."""
import json
import sys
import types

import pytest

import audit


def test_body_of_returns_balanced_post_body_only():
    html = ("<style>.theme{}</style><div class='post-body'><div>a<div>b</div></div>"
            "<p>c</p></div><div class='footer'>theme</div>")
    assert audit.body_of(html) == "<div class='post-body'><div>a<div>b</div></div><p>c</p></div>"
    assert audit.body_of("<div>no post</div>") == ""
    assert audit.body_of('<div class="post-body" id="x"><div>open').startswith('<div class="post-body"')


def test_static_audit_scopes_rules_to_body(monkeypatch, tmp_path):
    monkeypatch.setattr(audit, "OUT", str(tmp_path))
    page = ("<style>@media not all and (prefers-color-scheme:dark){}</style>"
            "<div class='post-body'><p>hi</p></div>")
    monkeypatch.setattr(audit, "fetch", lambda url: page)
    monkeypatch.setattr(audit, "js_syntax_errors", lambda html, tmp: [])
    res = audit.static_audit({"id": "1", "title": "t", "url": "u"})
    by = {c["rule"]: c for c in res["checks"]}
    assert by["no-inverted-media-query"]["ok"]  # theme CSS outside the body is ignored
    assert not by["disclaimer-present"]["ok"]
    assert res["bytes"] == len(page)


class _Page:
    def __init__(self, shots):
        self.shots = shots

    def goto(self, *a, **k):
        pass

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js):
        if "pageOverflow" in js:
            return {"pageOverflow": False, "docW": 1, "viewW": 1, "wideEls": []}
        return {"checked": 1, "fails": 0, "worst": []}

    def screenshot(self, path, full_page=False):
        self.shots.append(path)
        with open(path, "wb") as f:
            f.write(b"NEW-RENDER")


def _install_fake_playwright(monkeypatch, shots):
    class Ctx:
        def new_page(self):
            return _Page(shots)

        def close(self):
            pass

    class Browser:
        def new_context(self, **kw):
            return Ctx()

        def close(self):
            pass

    class P:
        chromium = types.SimpleNamespace(launch=lambda: Browser())

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    mod = types.ModuleType("playwright.sync_api")
    mod.sync_playwright = lambda: P()
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", mod)


def test_baseline_mode_writes_screenshots(monkeypatch, tmp_path):
    shots = []
    _install_fake_playwright(monkeypatch, shots)
    monkeypatch.setattr(audit, "SHOTS", str(tmp_path / "baseline"))
    monkeypatch.setattr(audit, "OUT", str(tmp_path / "out"))
    audit.rendered_audit([{"id": "p1", "url": "u"}], baseline=True)
    assert (tmp_path / "baseline" / "p1.light.png").read_bytes() == b"NEW-RENDER"
    assert (tmp_path / "baseline" / "p1.dark.png").exists()


def test_rendered_pass_diffs_against_existing_baseline(monkeypatch, tmp_path):
    """The docstring promises 'a screenshot baseline for visual-regression
    diffing'. With a baseline on disk, a normal rendered pass must compare the
    current render to it, and must not overwrite it."""
    shots = []
    _install_fake_playwright(monkeypatch, shots)
    base = tmp_path / "baseline"
    base.mkdir()
    (base / "p1.light.png").write_bytes(b"OLD-RENDER")
    (base / "p1.dark.png").write_bytes(b"NEW-RENDER")
    monkeypatch.setattr(audit, "SHOTS", str(base))
    monkeypatch.setattr(audit, "OUT", str(tmp_path / "out"))
    out = audit.rendered_audit([{"id": "p1", "url": "u"}], baseline=False)
    assert out[("p1", "light")]["visual"]["changed"] is True
    assert out[("p1", "dark")]["visual"]["changed"] is False
    assert (base / "p1.light.png").read_bytes() == b"OLD-RENDER"


def test_main_reports_visual_regression_rule(monkeypatch, tmp_path):
    shots = []
    _install_fake_playwright(monkeypatch, shots)
    base = tmp_path / "baseline"
    base.mkdir()
    (base / "p1.light.png").write_bytes(b"OLD-RENDER")
    monkeypatch.setattr(audit, "SHOTS", str(base))
    monkeypatch.setattr(audit, "OUT", str(tmp_path / "out"))
    page = "<div class='post-body'><p>x</p></div>"
    monkeypatch.setattr(audit, "fetch", lambda url: page)
    monkeypatch.setattr(audit, "js_syntax_errors", lambda html, tmp: [])
    monkeypatch.setattr(audit.hashlib, "md5", lambda b: types.SimpleNamespace(hexdigest=lambda: "p1" + "0" * 30))
    monkeypatch.setattr(sys, "argv", ["audit.py", "--url", "https://x/p.html", "--rendered"])
    audit.main()  # no BLOCKER -> no SystemExit
    results = json.loads((tmp_path / "out" / "report.json").read_text())
    by = {c["rule"]: c for c in results[0]["checks"]}
    assert by["visual-light"]["ok"] is False
    assert "visual-dark" not in by  # no baseline for dark -> nothing to compare
    assert by["contrast-light"]["ok"] is True
