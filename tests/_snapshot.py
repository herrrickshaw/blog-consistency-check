"""Compute a deterministic, offline snapshot of the tool's behaviour.

Used both to generate ``golden_baseline.json`` from the ORIGINAL code and to
assert the refactored code reproduces it. Never touches the network: curl and
the theme stylesheet are stubbed, and ``audit.main`` runs against the tracked
``fixes/*.html`` corpus in a temporary output directory.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
from pathlib import Path


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def compute(root: Path) -> dict:
    """Return the snapshot for the code tree rooted at ``root``."""
    sys.path.insert(0, str(root))
    for name in ("audit", "checks", "fix", "add_index_link", "add_revision_line"):
        sys.modules.pop(name, None)
    import add_index_link  # noqa: E402
    import audit  # noqa: E402
    import fix  # noqa: E402
    import add_revision_line  # noqa: E402,F401

    fix._THEME_CACHE["css"] = ""  # no network for the dark-panel guard
    files = sorted((root / "fixes").glob("*.html"))
    snap: dict = {"static": {}, "repair": {}, "index_link": {}, "body_of": {}}
    for f in files:
        body = f.read_text(encoding="utf-8", errors="replace")
        snap["static"][f.name] = [
            [n, s, bool(fn(body=body, node_check=[])[0]), fn(body=body, node_check=[])[1]]
            for n, s, fn in audit.STATIC_RULES
        ]
        fixed, notes = fix.repair(body)
        snap["repair"][f.name] = [_sha(fixed), notes, fix.static_pass(fixed)]
        new, where = add_index_link.insert(body)
        snap["index_link"][f.name] = [None if new is None else _sha(new), where]
        page = "<html><div class='post-body'>" + body + "</div></html>"
        snap["body_of"][f.name] = _sha(audit.body_of(page))

    # Whole-pipeline run of audit.main over the corpus with stubbed I/O.
    by_url = {f"https://x.test/{f.stem}.html": f for f in files}
    audit.fetch = lambda url: ("<div class='post-body'>"
                               + by_url[url].read_text(encoding="utf-8", errors="replace")
                               + "</div>")
    audit.js_syntax_errors = lambda html, tmp: []
    with tempfile.TemporaryDirectory() as td:
        audit.OUT = td
        urls = Path(td) / "urls.txt"
        urls.write_text("\n".join(by_url))
        argv, out = sys.argv, io.StringIO()
        sys.argv = ["audit.py", "--urls-file", str(urls)]
        code = 0
        try:
            with contextlib.redirect_stdout(out):
                audit.main()
        except SystemExit as ex:
            code = ex.code or 0
        finally:
            sys.argv = argv
        report = (Path(td) / "report.md").read_text()
        rjson = json.loads((Path(td) / "report.json").read_text())
    snap["audit"] = {"exit": code, "report_sha": _sha(report),
                     "report_json_sha": _sha(json.dumps(rjson, sort_keys=True)),
                     "stdout_sha": _sha(out.getvalue().replace(td, "<TMP>")),
                     "n": len(rjson)}
    return snap


if __name__ == "__main__":
    target = Path(sys.argv[1]).resolve()
    print(json.dumps(compute(target), indent=1, sort_keys=True))
