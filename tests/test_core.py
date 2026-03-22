from pathlib import Path

import zotero_curator.cli as cli

from zotero_curator.cli import (
    build_attachment_name,
    canonicalize_item_collections,
    collection_path_from_key,
    ensure_attachment,
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


def test_ensure_attachment_renames_existing_imported_pdf_title_and_filename(
    tmp_path: Path, monkeypatch
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.patched: list[tuple[str, int, dict[str, str]]] = []

        def get_item_children(self, key: str) -> list[dict[str, dict[str, object]]]:
            assert key == "PARENT1"
            return [
                {
                    "data": {
                        "key": "ATT1",
                        "version": 7,
                        "itemType": "attachment",
                        "linkMode": "imported_file",
                        "contentType": "application/pdf",
                        "filename": "old.pdf",
                        "title": "PDF",
                    }
                }
            ]

        def patch_item(self, key: str, version: int, data: dict[str, str]) -> None:
            self.patched.append((key, version, data))

    client = FakeClient()
    paper = type("Paper", (), {"arxiv_id": "2603.18073"})()
    parent_data = {
        "title": "Continually self-improving AI",
        "date": "2026-03-18",
        "creators": [{"lastName": "Yang", "firstName": "Zitong"}],
    }

    local_pdf = tmp_path / "cache" / "dummy.pdf"
    local_pdf.parent.mkdir(parents=True, exist_ok=True)
    local_pdf.write_bytes(b"%PDF-1.4\n" + b"0" * 20000)

    monkeypatch.setattr(cli, "ensure_pdf_download", lambda url, cache_dir, filename: local_pdf)
    monkeypatch.setattr(cli, "upload_imported_file", lambda client, attachment_key, local_pdf: "exists")
    monkeypatch.setattr(cli, "ensure_local_storage_copy", lambda data_dir, attachment_key, source_pdf: None)

    out = ensure_attachment(
        client,
        paper,
        "PARENT1",
        parent_data,
        data_dir=tmp_path / "zotero",
        cache_dir=tmp_path / "cache",
        dry_run=False,
        prune=False,
    )

    assert out is not None
    assert out["attachment"] == "ATT1"
    assert client.patched == [
        (
            "ATT1",
            7,
            {
                "filename": "Yang - 2026 - Continually self-improving AI.pdf",
                "title": "Yang - 2026 - Continually self-improving AI",
            },
        )
    ]


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


def test_resolve_collection_with_false_parent_from_api() -> None:
    collections = [
        {"data": {"key": "AI_ROOT", "name": "Artificial Intelligence", "parentCollection": False, "version": 10}},
        {"data": {"key": "LLM", "name": "Large Language Models", "parentCollection": "AI_ROOT", "version": 11}},
    ]
    by_key, by_slot, _ = index_collections(collections)
    chain, leaf = resolve_collection_path_existing(
        path_segments=["Artificial Intelligence", "Large Language Models"],
        by_key=by_key,
        by_slot=by_slot,
    )
    assert chain == ["AI_ROOT", "LLM"]
    assert leaf == "LLM"
