#!/usr/bin/env python3
"""CLI: sync Play Store + App Store reviews into local SQLite."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.sync import sync_all  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync UZ finance app reviews")
    parser.add_argument("--slug", help="Sync only one app slug")
    parser.add_argument("--play-count", type=int, default=150)
    parser.add_argument("--ios-pages", type=int, default=5)
    args = parser.parse_args()

    result = sync_all(
        play_review_count=args.play_count,
        ios_pages=args.ios_pages,
        only_slug=args.slug,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result.get("status") != "ok":
        sys.exit(1)


if __name__ == "__main__":
    main()
