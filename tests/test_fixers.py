import json
import pathlib

import pytest

import add_index_link as ail
import add_revision_line as arl

LONG = "x" * 4000


def _doc(translate=True, style=True, disclosure=True, revision=False, tail=LONG):
    s = ""
    if style:
        s += "<style>a{}</style>"
    if translate:
        s += ('<div id="google_translate_element"></div><script>a</script>'
              '<script src="https://translate.google.com/x.js"></script>')
    if revision:
        s += '<p class="gs-revised" data-gs-revision-v1="1">r</p>'
    s += "<p>" + tail + "</p>"
    if disclosure:
        s += '<p class="gs-ai-disclosure">AI</p>'
    return s


# ---------- add_index_link.insert ----------
def test_index_insert_after_translate_widget():
    new, where = ail.insert(_doc())
    assert where == "after translate widget"
    i = new.index('<div class="topnav-index-link"')
    assert new[:i].rstrip().endswith("</script>") and ail.LINE in new
    assert new.index("translate.google.com") < i


def test_index_insert_falls_back_to_first_style():
    new, where = ail.insert(_doc(translate=False))
    assert where == "after first </style>"
    assert new.startswith("<style>a{}</style>\n" + ail.LINE)


def test_index_already_present_and_nowhere():
    assert ail.insert("x article-index-start-here y") == (None, "already has an index link")
    assert ail.insert("<p>nothing</p>") == (None, "no translate widget and no </style> — insert by hand")


def test_index_offset_guard_boundary():
    # anchor at exactly half the document is allowed, past half is refused
    head = "<style>a</style>"
    body = head + "z" * (len(head) * 1)               # anchor end == 50%
    assert ail.insert(body)[1] == "after first </style>"
    body2 = head + "z" * (len(head) - 1)               # anchor end > 50%
    new, why = ail.insert(body2)
    assert new is None and "through the doc" in why and why.startswith("after first </style> would land at ")


def test_index_disclosure_gap_guard():
    head = "<style>a</style>"
    # the regex matches at `gs-ai-disclosure`, 10 chars after the `<p class="` that opens the tag
    near = head + "q" * 489 + '<p class="gs-ai-disclosure">x</p>' + "z" * 2000
    new, why = ail.insert(near)
    assert new is None and why == "after first </style> would land on top of the AI disclosure"
    ok = head + "q" * 490 + '<p class="gs-ai-disclosure">x</p>' + "z" * 2000
    assert ail.insert(ok)[1] == "after first </style>"
    # the disclaimer class variant is recognised too
    near2 = head + "q" * 10 + '<p class="disclaimer">x</p>' + "z" * 2000
    assert ail.insert(near2)[0] is None


# ---------- add_index_link.main ----------
def _setup_fixes(tmp_path, monkeypatch, mod, docs):
    fx = tmp_path / "fixes"
    fx.mkdir()
    entries = []
    for slug, body in docs.items():
        p = fx / f"{slug}.html"
        p.write_text(body, encoding="utf-8")
        entries.append({"slug": slug, "path": str(p)})
    (fx / "manifest.json").write_text(json.dumps(entries))
    monkeypatch.setattr(mod, "FIXES", fx)
    return fx


def test_index_main_updates_and_reports(tmp_path, monkeypatch, capsys):
    fx = _setup_fixes(tmp_path, monkeypatch, ail, {
        "good": _doc(), "has": "article-index-start-here", "bad": "<p>none</p>"})
    monkeypatch.setattr("sys.argv", ["x"])
    assert ail.main() == 0
    out = capsys.readouterr().out
    assert "  ok    good" in out and "after translate widget" in out
    assert "  skip  bad" in out and "has" not in out.replace("has_", "")
    assert "1 updated, 1 skipped" in out and "(dry run)" not in out
    assert "topnav-index-link" in (fx / "good.html").read_text(encoding="utf-8")


def test_index_main_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    fx = _setup_fixes(tmp_path, monkeypatch, ail, {"good": _doc()})
    before = (fx / "good.html").read_text(encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["x", "--dry-run"])
    ail.main()
    assert (fx / "good.html").read_text(encoding="utf-8") == before
    assert "1 updated, 0 skipped (dry run)" in capsys.readouterr().out


def test_index_main_puts_link_above_revision_line(tmp_path, monkeypatch, capsys):
    # revision line sits before the translate widget, so the link goes above the revision line
    body = ("<style>a{}</style>" + '<p class="gs-revised" data-gs-revision-v1="1">r</p>' +
            '<div id="google_translate_element"></div><script>a</script>'
            '<script src="https://translate.google.com/x.js"></script><p>' + LONG + "</p>")
    fx = _setup_fixes(tmp_path, monkeypatch, ail, {"p": body})
    monkeypatch.setattr("sys.argv", ["x"])
    ail.main()
    new = (fx / "p.html").read_text(encoding="utf-8")
    assert new.index("topnav-index-link") < new.index("gs-revised")
    assert "before the revision line" in capsys.readouterr().out


# ---------- add_revision_line ----------
def test_revision_insert_after_index_link():
    body = ('<style>a{}</style><div class="topnav-index-link"><a>i</a></div><p>' + LONG + "</p>"
            '<p class="gs-ai-disclosure">AI</p>')
    new, where = arl.insert(body)
    assert where == "after index link"
    assert new.index("topnav-index-link") < new.index(arl.MARKER) < new.index("<p>" + LONG)
    assert 'datetime="2026-08-06"' in new and "v1.0.1" in new and "6 August 2026" in new


def test_revision_insert_fallbacks_and_guards():
    assert arl.insert("data-gs-revision-v1") == (None, "already has a revision line")
    assert arl.insert("<p>x</p>") == (None, "no index link and no </style> — insert by hand")
    new, where = arl.insert("<style>a</style><p>" + LONG + "</p>")
    assert where == "after first </style>" and new.startswith("<style>a</style>\n<p class=\"gs-revised\"")
    head = "<style>a</style>"
    assert arl.insert(head + "z" * len(head))[1] == "after first </style>"
    new, why = arl.insert(head + "z" * (len(head) - 1))
    assert new is None and "through the doc" in why
    near = head + "q" * 489 + '<p class="gs-ai-disclosure">x</p>' + "z" * 2000
    assert arl.insert(near) == (None, "after first </style> would land on top of the AI disclosure")
    ok = head + "q" * 490 + '<p class="gs-ai-disclosure">x</p>' + "z" * 2000
    assert arl.insert(ok)[1] == "after first </style>"
    # `class="disclaimer"` matches at `class=`, 3 chars after `<p `
    assert arl.insert(head + "q" * 496 + '<p class="disclaimer">x</p>' + "z" * 2000)[0] is None
    assert arl.insert(head + "q" * 497 + '<p class="disclaimer">x</p>' + "z" * 2000)[1] == "after first </style>"


def test_revision_line_content():
    assert arl.VERSION == "1.0.1" and arl.DATE_ISO == "2026-08-06"
    assert arl.MARKER in arl.LINE and 'itemprop="dateModified"' in arl.LINE


def _archive(tmp_path, monkeypatch, posts):
    arch = tmp_path / "arch" / "meta"
    arch.mkdir(parents=True)
    (arch / "manifest.json").write_text(json.dumps({"posts": posts}))
    monkeypatch.setattr(arl, "MANIFEST", arch / "manifest.json")


def test_pending_slugs_missing_manifest_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(arl, "MANIFEST", tmp_path / "nope.json")
    with pytest.raises(SystemExit) as e:
        arl.pending_slugs()
    assert "MASALADEUTSCH_ARCHIVE" in str(e.value.code)


def test_pending_slugs_classification(tmp_path, monkeypatch):
    marks = lambda ll, dp, inv: {"light_lock": ll, "dark_panel_guard": dp, "inverted_media_query": inv}  # noqa: E731
    _archive(tmp_path, monkeypatch, {
        "1": {"slug": "a-done", "markers": marks(True, True, False)},
        "2": {"slug": "b-needs-lock", "markers": marks(False, True, False)},
        "3": {"slug": "c-needs-guard", "markers": marks(True, False, False)},
        "4": {"slug": "d-inverted", "markers": marks(True, True, True)},
        "5": {"slug": "e-lock-not-in-fix", "markers": marks(False, False, False)},
    })
    docs = {
        "a-done": "gs-light-lock gs-dark-panel-guard",
        "b-needs-lock": "gs-light-lock",
        "c-needs-guard": "gs-dark-panel-guard",
        "d-inverted": "nothing",
        "e-lock-not-in-fix": "plain body with neither marker",
        "not-live": "x",
    }
    _setup_fixes(tmp_path, monkeypatch, arl, docs)
    got = [e["slug"] for e in arl.pending_slugs()]
    assert got == ["b-needs-lock", "c-needs-guard", "d-inverted"]


def test_revision_main(tmp_path, monkeypatch, capsys):
    marks = {"light_lock": False, "dark_panel_guard": True, "inverted_media_query": False}
    _archive(tmp_path, monkeypatch, {"1": {"slug": "ok", "markers": marks}, "2": {"slug": "bad", "markers": marks}})
    good = '<div class="topnav-index-link">i</div><p>' + LONG + "</p>"
    fx = _setup_fixes(tmp_path, monkeypatch, arl, {"ok": "gs-light-lock " + good, "bad": "gs-light-lock <p>x</p>"})
    monkeypatch.setattr("sys.argv", ["x", "--dry-run"])
    assert arl.main() == 0
    out = capsys.readouterr().out
    assert "2 pending fixes" in out and "1 updated, 1 skipped (dry run)" in out
    assert arl.MARKER not in (fx / "ok.html").read_text(encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["x"])
    assert arl.main() == 0
    assert arl.MARKER in (fx / "ok.html").read_text(encoding="utf-8")


def test_revision_main_exit_code_when_nothing_done(tmp_path, monkeypatch):
    marks = {"light_lock": False, "dark_panel_guard": True, "inverted_media_query": False}
    _archive(tmp_path, monkeypatch, {"1": {"slug": "bad", "markers": marks}})
    _setup_fixes(tmp_path, monkeypatch, arl, {"bad": "gs-light-lock <p>x</p>"})
    monkeypatch.setattr("sys.argv", ["x"])
    assert arl.main() == 1
