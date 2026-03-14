# Publishing (Trusted PyPI)

This project uses GitHub OIDC Trusted Publishing.

## One-time PyPI setup

1. Log into PyPI and create/access the project `zotero-curator` publisher settings.
2. Add a **Pending publisher** with:
   - Owner: `suborigin`
   - Repository name: `zotero-curator`
   - Workflow name: `publish-pypi.yml`
   - Environment name: *(leave empty unless you enforce one in GitHub)*
3. Save.

## Release flow

1. Create and publish a GitHub release (tag `vX.Y.Z`).
2. Workflow `.github/workflows/publish-pypi.yml` runs automatically.
3. Package appears on PyPI.

## Verification

- PyPI: `https://pypi.org/project/zotero-curator/`
- CI logs: GitHub Actions -> `Publish to PyPI`
