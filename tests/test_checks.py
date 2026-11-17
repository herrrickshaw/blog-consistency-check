"""Unit tests for the pure static rules in checks.py."""
from checks import (
    r_dark_vars_locked, r_disclaimer_not_in_script, r_disclaimer_present, r_index_link,
    r_no_inverted_media_query, r_scripts_parse, r_table_units_in_header, r_wpi_attribution,
)

DISC = '<p data-gs-ai-disclosure-v1="1">x</p>'


def test_inverted_media_query_flagged():
    ok, detail = r_no_inverted_media_query('<style>@media not all and (prefers-color-scheme:dark){a{}}</style>')
    assert not ok and "1 inverted" in detail
    assert r_no_inverted_media_query("<p>clean</p>")[0]


def test_disclaimer_inside_script_flagged_and_outside_required():
    spliced = f"<script>var s='{DISC}';</script>"
    assert not r_disclaimer_not_in_script(spliced)[0]
    assert not r_disclaimer_present(spliced)[0]
    assert r_disclaimer_present(spliced + DISC)[0]
    assert r_disclaimer_not_in_script(DISC)[0]


def test_dark_vars_locked():
    assert r_dark_vars_locked("<p>no palette</p>") == (True, "n/a (no dark palette)")
    css = "@media (prefers-color-scheme:dark){:root{--text:#fff}} p{color:var(--text)}"
    assert not r_dark_vars_locked(css)[0]
    assert r_dark_vars_locked(css + " /*gs-light-lock-v1*/")[0]


def test_index_link():
    assert r_index_link('<div class="topnav-index-link"></div>')[0]
    assert not r_index_link("<p></p>")[0]


def test_wpi_attribution():
    assert r_wpi_attribution("no mention") == (True, "n/a")
    assert not r_wpi_attribution("MoSPI publishes the Wholesale Price Index")[0]
    assert r_wpi_attribution("DPIIT publishes the Wholesale Price Index")[0]


def test_table_units_threshold():
    few = "<td>1</td>" * 5
    assert r_table_units_in_header(few)[1].startswith("n/a")
    unity = "<td>10 %</td>" * 20
    assert not r_table_units_in_header(unity)[0]
    assert r_table_units_in_header("<td>10</td>" * 20)[0]


def test_scripts_parse_uses_node_result():
    assert r_scripts_parse("", None) == (True, "skipped (no node)")
    assert r_scripts_parse("", [2]) == (False, "JS syntax error in script(s) [2]")
    assert r_scripts_parse("", [])[0]
