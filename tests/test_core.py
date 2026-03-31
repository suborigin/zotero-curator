from pathlib import Path
import builtins

import zotero_curator.cli as cli

from zotero_curator.cli import (
    OAuthAccess,
    build_attachment_name,
    build_oauth_authorize_url,
    canonicalize_item_collections,
    collection_path_from_key,
    clear_env_exports,
    ensure_attachment,
    index_collections,
    parse_arxiv_id,
    render_env_exports,
    resolve_sync_credentials,
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


def test_canonicalize_item_collections_can_move_item_exclusively() -> None:
    collections = [
        {"data": {"key": "OLD", "name": "Old Bucket", "parentCollection": None, "version": 1}},
        {"data": {"key": "NEW", "name": "New Bucket", "parentCollection": None, "version": 2}},
    ]
    by_key, _, _ = index_collections(collections)
    out = canonicalize_item_collections(["OLD", "NEW"], "NEW", by_key, exclusive_target=True)
    assert out == ["NEW"]


def test_build_oauth_authorize_url_includes_requested_permissions() -> None:
    url = build_oauth_authorize_url(
        "temp-token",
        key_name="temporary sync",
        library_access=True,
        notes_access=False,
        write_access=True,
        all_groups="none",
    )
    assert "oauth_token=temp-token" in url
    assert "name=temporary+sync" in url
    assert "library_access=1" in url
    assert "notes_access=0" in url
    assert "write_access=1" in url
    assert "all_groups=none" in url


def test_render_env_exports_powershell() -> None:
    access = OAuthAccess(user_id="12345", api_key="secret", username="kenny")
    out = render_env_exports(access, "powershell")
    assert "$env:ZOTERO_USER_ID='12345'" in out
    assert "$env:ZOTERO_API_KEY='secret'" in out
    assert "$env:ZOTERO_USERNAME='kenny'" in out


def test_clear_env_exports_cmd() -> None:
    out = clear_env_exports("cmd")
    assert "set ZOTERO_USER_ID=" in out
    assert "set ZOTERO_API_KEY=" in out


def test_resolve_sync_credentials_uses_oauth_when_requested(monkeypatch) -> None:
    access = OAuthAccess(user_id="11", api_key="key-11", username="kenny")
    monkeypatch.delenv("ZOTERO_USER_ID", raising=False)
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    monkeypatch.setattr(cli, "perform_oauth_key_exchange", lambda args: access)
    printed: list[str] = []
    monkeypatch.setattr(builtins, "print", lambda *args, **kwargs: printed.append(" ".join(str(a) for a in args)))

    args = cli.build_parser().parse_args(
        [
            "sync",
            "--plan",
            "dummy.yaml",
            "--oauth-authorize",
            "--print-env-after-oauth",
        ]
    )

    user_id, api_key, oauth_access = resolve_sync_credentials(args)

    assert user_id == "11"
    assert api_key == "key-11"
    assert oauth_access == access
    assert any("ZOTERO_API_KEY" in line for line in printed)
