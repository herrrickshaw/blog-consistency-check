"""Tests for audit.py's pure report pieces and the CLI wiring (network stubbed)."""
import json

import audit


def _post(rules):
    return {"id": "1", "title": "T", "url": "u",
            "checks": [{"rule": n, "severity": s, "ok": ok, "detail": d} for n, s, ok, d in rules]}


def test_summarise_and_render_markdown():
    results = [_post([("a", "BLOCKER", False, "boom"), ("b", "MINOR", True, "")]),
               _post([("a", "BLOCKER", True, ""), ("b", "MINOR", False, "")])]
    failing, counts = audit.summarise(results)
    assert [f[0] for f in failing] == [0, 2]            # BLOCKER post sorts first
    assert counts[("BLOCKER", "a")] == [1, 2]
    md = audit.render_markdown(results, failing, counts)
    assert "posts audited: **2**" in md and "| BLOCKER | `a` | 1 | 2 |" in md and "— boom" in md


def test_add_rendered_checks_skips_errors():
    r = _post([])
    rend = {("1", "light"): {"contrast": {"fails": 2, "checked": 10},
                              "overflow": {"pageOverflow": False, "docW": 1, "viewW": 1}},
            ("1", "dark"): {"error": "x"}}
    audit.add_rendered_checks([r], rend)
    names = [c["rule"] for c in r["checks"]]
    assert names == ["contrast-light", "no-overflow-light"]
    assert r["checks"][0]["detail"] == "2/10 nodes below 3:1" and not r["checks"][0]["ok"]


def test_parser_flags_unchanged():
    ns = audit.build_parser().parse_args(["--rendered", "--limit", "3", "--url", "u"])
    assert ns.rendered and ns.limit == 3 and ns.url == "u" and not ns.priority


def test_main_exit_code_gates_on_blocker(tmp_path, monkeypatch, capsys):
    bad = "<div class='post-body'><style>@media not all and (prefers-color-scheme:dark){a{}}</style></div>"
    monkeypatch.setattr(audit, "fetch", lambda url: bad)
    monkeypatch.setattr(audit, "js_syntax_errors", lambda html, tmp: [])
    monkeypatch.setattr(audit, "OUT", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["audit.py", "--url", "https://x.test/p.html"])
    try:
        audit.main()
        code = 0
    except SystemExit as ex:
        code = ex.code
    assert code == 1
    assert (tmp_path / "report.md").exists()
    assert json.loads((tmp_path / "report.json").read_text())[0]["url"] == "https://x.test/p.html"
