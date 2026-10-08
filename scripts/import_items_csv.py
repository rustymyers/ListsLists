#!/usr/bin/env python3
import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.services.csv_import import CSV_HEADERS, import_canonical_items  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import new canonical items from CSV without changing existing items."
    )
    parser.add_argument("csv_file", type=Path, help="CSV file to import")
    parser.add_argument("--owner", required=True, help="Username that will own the imported items")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many rows would be created or skipped without changing the database",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.csv_file.is_file():
        print(f"CSV file not found: {args.csv_file}", file=sys.stderr)
        return 2
    with args.csv_file.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or "name" not in reader.fieldnames:
            print(
                f"CSV must contain a name column. Supported columns: {', '.join(CSV_HEADERS)}",
                file=sys.stderr,
            )
            return 2
        rows = list(reader)
    with SessionLocal() as session:
        owner = session.scalar(select(User).where(User.username == args.owner))
        if not owner:
            print(f"User not found: {args.owner}", file=sys.stderr)
            return 2
        try:
            result = import_canonical_items(session, owner, rows, dry_run=args.dry_run)
        except ValueError as exc:
            print(f"Import failed: {exc}", file=sys.stderr)
            return 2
        if not args.dry_run:
            session.commit()
    mode = "Would create" if args.dry_run else "Created"
    print(
        f"{mode} {result.created} item(s); "
        f"skipped {result.skipped} existing item row(s); "
        f"created {result.lists_created} list(s); "
        f"added {result.placements_created} list placement(s); "
        f"skipped {result.placements_skipped} existing placement(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
