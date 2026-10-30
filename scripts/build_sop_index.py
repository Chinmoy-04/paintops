"""Rebuild the local synthetic SOP vector/keyword index."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.rag.index import build_sop_index


def main() -> None:
    meta = build_sop_index(force=True)
    print(meta)


if __name__ == "__main__":
    main()
