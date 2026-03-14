from zotero_curator.cli import (
    build_attachment_name,
    canonicalize_item_collections,
    collection_path_from_key,
    index_collections,
    parse_arxiv_id,
    resolve_collection_path_existing,
    strip_arxiv_version,
)


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


def test_strip_arxiv_version() -> None:
    assert strip_arxiv_version("2501.12948v2") == "2501.12948"
    assert strip_arxiv_version("2501.12948") == "2501.12948"


def test_resolve_collection_prefers_existing_full_path() -> None:
    collections = [
        {"data": {"key": "ROOT_A", "name": "Artificial Intelligence", "parentCollection": None, "version": 100}},
        {"data": {"key": "ROOT_B", "name": "Artificial Intelligence", "parentCollection": None, "version": 200}},
        {"data": {"key": "LLM_A", "name": "Large Language Models", "parentCollection": "ROOT_A", "version": 100}},
        {"data": {"key": "LLM_B", "name": "Large Language Models", "parentCollection": "ROOT_B", "version": 200}},
        {"data": {"key": "CTX_A", "name": "Context Engineering", "parentCollection": "LLM_A", "version": 100}},
        {"data": {"key": "CTX_B", "name": "Context Engineering", "parentCollection": "LLM_B", "version": 200}},
        {"data": {"key": "SELF_A", "name": "Self-Refinement", "parentCollection": "CTX_A", "version": 100}},
        {"data": {"key": "SELF_B", "name": "Self-Refinement", "parentCollection": "CTX_B", "version": 200}},
    ]
    by_key, by_slot, _ = index_collections(collections)
    chain, leaf = resolve_collection_path_existing(
        path_segments=["Artificial Intelligence", "Large Language Models", "Context Engineering", "Self-Refinement"],
        by_key=by_key,
        by_slot=by_slot,
    )
    assert leaf == "SELF_A"
    assert chain == ["ROOT_A", "LLM_A", "CTX_A", "SELF_A"]


def test_canonicalize_item_collections_dedupes_same_path() -> None:
    collections = [
        {"data": {"key": "ROOT_OLD", "name": "Artificial Intelligence", "parentCollection": None, "version": 10}},
        {"data": {"key": "ROOT_NEW", "name": "Artificial Intelligence", "parentCollection": None, "version": 200}},
        {"data": {"key": "LLM_OLD", "name": "Large Language Models", "parentCollection": "ROOT_OLD", "version": 10}},
        {"data": {"key": "LLM_NEW", "name": "Large Language Models", "parentCollection": "ROOT_NEW", "version": 200}},
        {"data": {"key": "POST_OLD", "name": "Post Training", "parentCollection": "LLM_OLD", "version": 10}},
        {"data": {"key": "POST_NEW", "name": "Post Training", "parentCollection": "LLM_NEW", "version": 200}},
    ]
    by_key, _, _ = index_collections(collections)
    assert collection_path_from_key("POST_OLD", by_key) == "Artificial Intelligence/Large Language Models/Post Training"
    assert collection_path_from_key("POST_NEW", by_key) == "Artificial Intelligence/Large Language Models/Post Training"

    out = canonicalize_item_collections(["POST_OLD", "POST_NEW"], "POST_OLD", by_key)
    assert out == ["POST_OLD"]
