from zotero_curator.cli import parse_arxiv_id, build_attachment_name


def test_parse_arxiv_id_plain() -> None:
    assert parse_arxiv_id("2303.17651") == "2303.17651"


def test_parse_arxiv_id_url() -> None:
    assert parse_arxiv_id("https://arxiv.org/abs/2203.11171") == "2203.11171"


def test_build_attachment_name() -> None:
    parent = {
        "title": "Self-Refine: Iterative Refinement with Self-Feedback",
        "date": "2023-03-31",
        "creators": [{"lastName": "Madaan", "firstName": "Aman"}],
    }
    out = build_attachment_name(parent)
    assert out.startswith("Madaan - 2023 - Self-Refine")
    assert out.endswith(".pdf")
