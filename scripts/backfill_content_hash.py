#!/usr/bin/env python3
"""Backfill content_hash field in corpus frontmatter."""

import argparse

from sync_antraege import MD_DIR, compute_content_hash, parse_markdown_frontmatter, write_markdown_file


def main():
    parser = argparse.ArgumentParser(description="Backfill content_hash for markdown corpus")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute hash even if content_hash already exists",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max file count for partial runs",
    )
    args = parser.parse_args()

    files = sorted(MD_DIR.rglob("*.md"))
    if args.limit > 0:
        files = files[: args.limit]

    updated = 0
    skipped = 0
    failed = 0

    for idx, path in enumerate(files):
        print(f"\r[{idx + 1}/{len(files)}] {path.name[:60]:60}", end="", flush=True)
        try:
            fm, body = parse_markdown_frontmatter(path)
            if not fm:
                skipped += 1
                continue

            if fm.get("content_hash") and not args.force:
                skipped += 1
                continue

            fm["content_hash"] = compute_content_hash(body)
            write_markdown_file(path, fm, body)
            updated += 1
        except Exception:
            failed += 1

    print("\n")
    print(f"Updated: {updated}")
    print(f"Skipped: {skipped}")
    print(f"Failed:  {failed}")


if __name__ == "__main__":
    main()
