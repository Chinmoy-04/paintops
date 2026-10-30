"""Reset local demo SQLite databases and optional Chroma directory.

WARNING: Deletes local demo data files.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.database.session import reset_engine
from app.graph.builder import reset_compiled_graph


def main() -> None:
    settings = get_settings()
    print(
        "WARNING: This deletes local PaintOps SQLite DB, checkpoint DB, "
        "and Chroma index directories."
    )
    confirm = input("Type DELETE to continue: ").strip()
    if confirm != "DELETE":
        print("Aborted.")
        return

    reset_compiled_graph()
    reset_engine()

    targets = [
        settings.database_path,
        Path(settings.checkpoint_db_path),
        Path(settings.chroma_dir),
    ]
    for path in targets:
        if path.is_file():
            path.unlink()
            print(f"Removed file {path}")
        elif path.is_dir():
            shutil.rmtree(path)
            print(f"Removed dir {path}")
        else:
            print(f"Skip missing {path}")
    print("Demo data reset complete.")


if __name__ == "__main__":
    main()
