"""insert() placement guards in add_index_link.py and add_revision_line.py."""
import add_index_link as ail


def test_index_link_inserted_after_first_style_when_no_translate():
    body = "<style>a{}</style>" + "x" * 2000
    new, where = ail.insert(body)
    assert where == "after first </style>"
    assert new.startswith("<style>a{}</style>\n" + ail.LINE)


def test_index_link_refuses_when_already_present_or_too_late():
    assert ail.insert(ail.MARKER)[0] is None
    body = "x" * 2000 + "<style></style>"
    new, reason = ail.insert(body)
    assert new is None and "through the doc" in reason
    assert ail.insert("plain")[0] is None


def test_index_link_refuses_to_land_on_disclosure():
    body = "<style></style>" + '<p class="disclaimer">AI</p>' + "y" * 2000
    new, reason = ail.insert(body)
    assert new is None and "AI disclosure" in reason
