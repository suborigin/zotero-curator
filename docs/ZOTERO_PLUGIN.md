# Zotero Plugin MVP

This repository now includes a minimal Zotero 7 plugin shell under:

- `plugins/zotero-curator-plugin`

It is designed as a thin UI wrapper over the local Python CLI.

## What The MVP Does

- Adds `Tools -> Zotero Curator Import...` inside Zotero
- Lets you paste article text directly in Zotero
- Prefills the target collection from the currently selected Zotero collection when possible
- Generates a temporary `plan.yaml` via `zotero-curator plan from-text`
- Launches `zotero-curator sync` with OAuth browser flow and temporary-key revocation
- Shows a simple completion alert using the generated report JSON

## What You Need Installed

- Zotero 7
- Local Python with `zotero-curator` dependencies available
- A local checkout of this repository
- A Zotero OAuth application `client key` and `client secret`

## Package The Plugin

```bash
python scripts/build_zotero_plugin.py
```

That will produce:

- `dist/zotero-curator-plugin.xpi`

## Install In Zotero

1. Open Zotero
2. Go to `Tools -> Plugins`
3. Click the gear icon and choose `Install Plugin From File...`
4. Select `dist/zotero-curator-plugin.xpi`
5. Restart Zotero if prompted

The current MVP targets Zotero's modern manifest-based plugin format and does not ship `install.rdf`.

## First-Run Notes

The plugin asks for:

- Python executable path
- Curator repository root
- Zotero OAuth client key
- Zotero OAuth client secret

The plugin stores those values in Zotero preferences for convenience.

## Current Limitations

- The import runs through the local Python interpreter; this is not yet a pure in-plugin implementation
- The plugin currently depends on the CLI for extraction and sync logic
- It shows completion summaries from the generated report, but does not yet render a rich per-paper table
- It does not yet manage duplicate collection cleanup inside Zotero UI
