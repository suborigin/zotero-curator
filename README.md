![zotero-curator](https://capsule-render.vercel.app/api?type=waving&height=220&color=0:0f172a,100:1e293b&text=zotero-curator&fontColor=e2e8f0&fontSize=54&desc=Sync-safe%20ingestion,%20classification,%20and%20attachments%20for%20Zotero&descAlignY=66)

# zotero-curator

[![CI](https://github.com/suborigin/zotero-curator/actions/workflows/ci.yml/badge.svg)](https://github.com/suborigin/zotero-curator/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/badge/PyPI-pending-lightgrey)](https://pypi.org/project/zotero-curator/)
[![Python](https://img.shields.io/badge/Python-%3E%3D3.10-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Zotero API](https://img.shields.io/badge/Zotero%20API-v3-red)](https://www.zotero.org/support/dev/web_api/v3/start)

Production-grade Zotero ingestion and curation for AI-assisted research workflows.

## Why this project

Most ad-hoc scripts can add items, but fail on long-term reliability:
- attachment type not sync-safe,
- broken local file links,
- inconsistent naming,
- duplicated collections.

`zotero-curator` solves this with an opinionated, sync-safe pipeline.

## Features

- Auto-create and enforce collection/sub-collection paths.
- Upsert papers by DOI/arXiv/title dedup logic.
- Attach PDFs via official Zotero `imported_file` upload flow.
- Normalize attachment `filename` and visible attachment `title`:
  - `Author - Year - Title.pdf`
- Optionally prune temporary attachment types (`linked_url`, `imported_url`, `linked_file`).
- Agent-friendly CLI for Codex / Claude Code workflows.

## Architecture

```mermaid
flowchart TD
  A["🧠 Research Plan (YAML/JSON)"] --> B["🔎 Detect Existing Items (DOI/arXiv/title)"]
  B --> C["🗂️ Build Collection Path"]
  C --> D["📄 Resolve PDF Source (arXiv)"]
  D --> E["☁️ Official Zotero Upload (imported_file)"]
  E --> F["💾 Local Storage Mirror (storage/&lt;itemKey&gt;)"]
  F --> G["🏷️ Auto Rename (Author - Year - Title)"]
  G --> H{"🧹 Prune Temporary Attachments?"}
  H -->|Yes| I["🧼 Remove linked_url/imported_url/linked_file"]
  H -->|No| J["📦 Keep Existing Extras"]
  I --> K["✅ Sync-safe Zotero Item"]
  J --> K
```

## Install

```bash
pip install zotero-curator
```

or local dev:

```bash
pip install -e .
```

## PyPI status

PyPI publication is not live yet, so the PyPI badge is intentionally marked as `pending`.

When release automation is ready, publish with:

```bash
python -m build
python -m twine upload dist/*
```

Trusted Publishing setup guide:
- [`docs/PUBLISHING.md`](docs/PUBLISHING.md)

## Credentials

```bash
export ZOTERO_USER_ID='YOUR_USER_ID'
export ZOTERO_API_KEY='YOUR_PRIVATE_KEY'
```

## Quick start

```bash
zotero-curator sync \
  --plan examples/plan.yaml \
  --prune-pdf-attachments
```

Dry-run:

```bash
zotero-curator sync --plan examples/plan.yaml --dry-run
```

## Plan format

```yaml
global_tags:
  - zotero-curated

papers:
  - title: "Self-Refine: Iterative Refinement with Self-Feedback"
    item_type: preprint
    arxiv_id: "2303.17651"
    target_collection: "Artificial Intelligence/Large Language Models/Context Engineering/Self-Refinement"
    tags: ["self-refinement"]
```

## CLI reference

```bash
zotero-curator sync --help
```

Key options:
- `--plan`: input YAML/JSON
- `--prune-pdf-attachments`: remove temporary/non-canonical PDF attachments
- `--data-dir`: Zotero local data dir (default: `~/Zotero`)
- `--download-cache-dir`: local PDF cache
- `--dry-run`: no writes

## Compatibility notes

- Designed for Zotero Web API v3 and local Zotero desktop data model.
- Best results when PDFs are available on arXiv.
- Non-arXiv metadata/classification still works; attachment may be skipped.

## Roadmap

- [x] Sync-safe `imported_file` attachment flow (official Web API upload)
- [x] Collection/sub-collection auto-classification
- [x] Attachment filename/title normalization
- [x] Optional temporary attachment pruning
- [ ] PyPI trusted publishing (OIDC)
- [ ] Non-arXiv resolver plugins (publisher pages / open-access mirrors)
- [ ] Integration test harness with a disposable Zotero sandbox library

## Security

- API keys are sensitive. Keep in environment variables.
- Never commit keys or personal exports containing private notes.

See [SECURITY.md](SECURITY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
