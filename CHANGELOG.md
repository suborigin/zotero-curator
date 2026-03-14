# Changelog

## 0.1.4
- Fix root collection matching bug where Zotero API returns `parentCollection=false`; now normalized to `None` to prevent accidental duplicate-tree creation.
- Add retry/backoff for transient network errors (`IncompleteRead`, `RemoteDisconnected`, reset/timeout, 5xx) to make long batch sync stable.
- Add regression test for `parentCollection=false` path resolution.

## 0.1.3
- Deduplicate existing item collection memberships by canonical collection path (prevents one item from being mounted to multiple same-name duplicate keys).
- Keep only one canonical key per path while still preserving intended target placement.

## 0.1.2
- Fix collection path resolution to strongly prefer existing full paths and avoid duplicate same-name collection trees.
- Add arXiv metadata enrichment (authors/title/date/abstract) by default for items with arXiv IDs/URLs.
- Make attachment upload idempotent by treating Zotero `HTTP 412 file exists` as a successful existing-file state.
- Add tests for collection-path resolution and arXiv ID normalization.

## 0.1.1
- Add issue templates and PyPI trusted-publishing workflow.
- Improve README architecture section and publishing guidance.

## 0.1.0
- Initial public release.
- Collection/sub-collection auto-classification.
- Official imported_file upload flow for PDF attachments.
- Attachment auto-naming (filename + title).
- Optional pruning of temporary PDF attachment types.
