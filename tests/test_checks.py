import checks as c

DISC = '<p class="disclaimer" data-gs-ai-disclosure-v1="1">AI</p>'


def test_disclaimer_not_in_script():
    ok, d = c.r_disclaimer_not_in_script(f"<script>var x='{DISC}';</script>")
    assert not ok and d == "disclaimer inside <script> #[1]"
    ok, d = c.r_disclaimer_not_in_script(f"<script>1</script><script type='x'>{DISC}</script>")
    assert not ok and "#[2]" in d
    assert c.r_disclaimer_not_in_script(f"<script>1</script>{DISC}") == (True, "")
    assert c.r_disclaimer_not_in_script("") == (True, "")


def test_disclaimer_present_only_outside_scripts():
    assert c.r_disclaimer_present(DISC) == (True, "")
    ok, d = c.r_disclaimer_present(f"<script>{DISC}</script>")
    assert not ok and d == "no AI-disclosure outside a <script>"
    assert c.r_disclaimer_present(f"<script>1</script>{DISC}")[0]


def test_inverted_media_query_count():
    assert c.r_no_inverted_media_query("a") == (True, "")
    ok, d = c.r_no_inverted_media_query(c.INVERTED_MQ * 2)
    assert not ok and d == "2 inverted dark-mode media query block(s)"


def test_dark_vars_locked_branches():
    assert c.r_dark_vars_locked("plain")[1] == "n/a (no dark palette)"
    dark_unused = "@media (prefers-color-scheme: dark){a{b:c}}"
    assert c.r_dark_vars_locked(dark_unused) == (True, "n/a (vars declared but never consumed)")
    used = dark_unused + " p{color:var(--surface)}"
    ok, d = c.r_dark_vars_locked(used)
    assert not ok and d == "dark palette consumed with no !important light lock"
    assert c.r_dark_vars_locked(used + " gs-light-lock-v1") == (True, "")
    assert c.r_dark_vars_locked(used + " :root{--surface:#fff !important}") == (True, "")
    # data-theme="dark" alone also counts as a dark palette
    assert not c.r_dark_vars_locked('<html data-theme="dark"> p{color:var( --text )}')[0]
    # every consumed variable name in the list is recognised
    for v in ("surface", "surface-alt", "border", "text", "text-mut", "ink", "page-bg"):
        assert not c.r_dark_vars_locked(f"prefers-color-scheme a{{x:var(--{v})}}")[0], v
    assert c.r_dark_vars_locked("prefers-color-scheme a{x:var(--other)}")[1].startswith("n/a (vars")


def test_translate_and_index():
    assert c.r_translate_widget("google_translate_element") == (True, "")
    assert c.r_translate_widget("x") == (False, "missing Google Translate widget")
    assert c.r_index_link("topnav-index-link") == (True, "")
    assert c.r_index_link("x") == (False, "missing All-Articles index link")


def test_bw_override():
    assert c.r_bw_override("plain") == (True, "n/a (no dark palette)")
    assert c.r_bw_override("prefers-color-scheme BW-OVERRIDE") == (True, "")
    assert c.r_bw_override('data-theme="dark" gs-light-lock-v1') == (True, "")
    ok, d = c.r_bw_override("prefers-color-scheme")
    assert not ok and d == "dark palette present with no BW-override / light lock"


def _cells(n_with_unit, n_total):
    return "".join(f"<td>{'5 %' if i < n_with_unit else 'plain'}</td>" for i in range(n_total))


def test_table_units_threshold_and_min_cells():
    assert c.r_table_units_in_header(_cells(11, 11)) == (True, "n/a (few cells)")
    assert c.r_table_units_in_header(_cells(0, 12)) == (True, "0%")
    # 30% is allowed, anything above fails
    ok, d = c.r_table_units_in_header(_cells(3, 10) + "<td>x</td>" * 0 + _cells(0, 0))
    assert d == "n/a (few cells)"
    ok, d = c.r_table_units_in_header(_cells(6, 20))
    assert ok and d == "30%"
    ok, d = c.r_table_units_in_header(_cells(7, 20))
    assert not ok and d == "35% of 20 cells carry units"


def test_table_units_unit_tokens_and_markup_stripped():
    for tok in ("₹", "&#8377;", "US$", "cr", "crore", "lakh", "%", "MT", "LMT", "MW", "kg", "bn", "mn", "CRORE"):
        html = f"<td>12 {tok}</td>" * 12
        assert not c.r_table_units_in_header(html)[0], tok
    # a unit inside a tag attribute is not cell text
    assert c.r_table_units_in_header('<td><span title="%">12</span></td>' * 12)[0]
    # word-boundary: 'cross' and 'mnemonic' do not count
    assert c.r_table_units_in_header("<td>cross mnemonic</td>" * 12)[0]


def test_scripts_parse():
    assert c.r_scripts_parse("", None) == (True, "skipped (no node)")
    assert c.r_scripts_parse("", []) == (True, "")
    ok, d = c.r_scripts_parse("", [2, 5])
    assert not ok and d == "JS syntax error in script(s) [2, 5]"


def test_wpi_attribution():
    assert c.r_wpi_attribution("nothing here") == (True, "n/a")
    assert c.r_wpi_attribution("WPI is published by DPIIT") == (True, "")
    bad1 = "MoSPI publishes the Wholesale Price Index"
    assert c.r_wpi_attribution(bad1) == (False, "WPI attributed to MoSPI")
    bad2 = "The Wholesale Price Index, released by MoSPI today"
    assert c.r_wpi_attribution(bad2) == (False, "WPI attributed to MoSPI")
    assert c.r_wpi_attribution("WPI by MoSPI Wholesale Price Index")[0] is False
    # corrective phrasing rescues the post
    for fix in ("not a MoSPI product", "not by MoSPI", "published by DPIIT"):
        assert c.r_wpi_attribution(bad1 + " " + fix)[0], fix
    # sentence end right after MoSPI is allowed
    assert c.r_wpi_attribution("Wholesale Price Index (WPI) is not CPI, unlike MoSPI.")[0]
    # a long gap breaks the association
    assert c.r_wpi_attribution("MoSPI " + "x" * 50 + " Wholesale Price Index")[0]
    assert c.r_wpi_attribution("Wholesale Price Index " + "x" * 60 + " MoSPI")[0]
    assert c.r_wpi_attribution("MoSPI says. WPI Wholesale Price Index")[0]  # '.' stops the match


def test_static_rules_registry():
    names = [n for n, _, _ in c.STATIC_RULES]
    assert len(names) == len(set(names)) == 10
    sev = {n: s for n, s, _ in c.STATIC_RULES}
    assert sev["js-parses"] == c.BLOCKER and sev["wpi-attribution"] == c.MAJOR and sev["index-link"] == c.MINOR
    assert (c.BLOCKER, c.MAJOR, c.MINOR) == ("BLOCKER", "MAJOR", "MINOR")
    clean = ('<div id="google_translate_element"></div><div class="topnav-index-link"></div>' + DISC)
    for n, _, fn in c.STATIC_RULES:
        ok, _ = fn(body=clean, node_check=[])
        assert ok, n


def test_js_snippets_present():
    assert "getComputedStyle" in c.CONTRAST_JS and "r < 3.0" in c.CONTRAST_JS
    assert "pageOverflow" in c.OVERFLOW_JS
