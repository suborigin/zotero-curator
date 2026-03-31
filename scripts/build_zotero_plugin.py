from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "plugins" / "zotero-curator-plugin"
DIST_DIR = ROOT / "dist"


def main() -> int:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    target = DIST_DIR / "zotero-curator-plugin.xpi"
    if target.exists():
        target.unlink()
    archive_base = DIST_DIR / "zotero-curator-plugin"
    archive = shutil.make_archive(str(archive_base), "zip", root_dir=PLUGIN_DIR)
    Path(archive).replace(target)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
