"""Copy the board from JSONBin (or a saved JSON file) into the Neon database.

Usage:
    python migrate_to_neon.py                      # read the board from JSONBin
    python migrate_to_neon.py --from-file board.json
    python migrate_to_neon.py --dry-run            # show what would be copied

Settings come from .streamlit/secrets.toml (DATABASE_URL_POOLED or
DATABASE_URL, plus JSONBIN_BIN_ID and JSONBIN_API_KEY when reading JSONBin),
or from environment variables with the same names.

The tasks table is created if needed. The script stops if the table already
has tasks, unless --replace is given, which deletes them first.
"""

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path

import requests

from store import STATUSES, SCHEMA, normalize_board


def setting(secrets, *names):
    for name in names:
        value = os.environ.get(name) or secrets.get(name)
        if value:
            return value
    return None


def read_board(args, secrets):
    if args.from_file:
        data = json.loads(Path(args.from_file).read_text())
        # Accept JSONBin's own export format as well as the bare board
        data = data.get("record", data)
    else:
        bin_id = setting(secrets, "JSONBIN_BIN_ID")
        api_key = setting(secrets, "JSONBIN_API_KEY")
        if not bin_id or not api_key:
            sys.exit("Set JSONBIN_BIN_ID and JSONBIN_API_KEY, or use --from-file.")
        resp = requests.get(
            f"https://api.jsonbin.io/v3/b/{bin_id}/latest",
            headers={"X-Master-Key": api_key},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("record", {})
    return normalize_board(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--from-file", help="a saved board JSON file")
    parser.add_argument("--dry-run", action="store_true", help="don't write anything")
    parser.add_argument(
        "--replace", action="store_true", help="delete existing tasks first"
    )
    args = parser.parse_args()

    secrets_file = Path(".streamlit/secrets.toml")
    secrets = tomllib.loads(secrets_file.read_text()) if secrets_file.exists() else {}

    board = read_board(args, secrets)
    counts = {status: len(board[status]) for status in STATUSES}
    print("Board to copy:", ", ".join(f"{s} {n}" for s, n in counts.items()))
    if args.dry_run:
        return

    url = setting(secrets, "DATABASE_URL_POOLED", "DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL_POOLED (or DATABASE_URL).")

    import psycopg

    # One transaction: either every task is copied or none is
    with psycopg.connect(url, connect_timeout=30, prepare_threshold=None) as conn:
        conn.execute(SCHEMA)
        existing = conn.execute("select count(*) from tasks").fetchone()[0]
        if existing and not args.replace:
            sys.exit(
                f"The tasks table already has {existing} tasks; nothing was copied. "
                "Use --replace to delete them and copy again."
            )
        if args.replace:
            conn.execute("delete from tasks")
        for status in STATUSES:
            for position, task in enumerate(board[status], start=1):
                conn.execute(
                    "insert into tasks (title, description, due, created, tags,"
                    " status, position, archived) values (%s, %s, %s, %s, %s, %s,"
                    " %s, %s)",
                    (
                        task["title"],
                        task["description"],
                        task["due"],
                        task["created"] or None,
                        task["tags"],
                        status,
                        position,
                        task.get("archived"),
                    ),
                )
        rows = conn.execute(
            "select status, count(*) from tasks group by status"
        ).fetchall()

    copied = dict(rows)
    print("Now in Neon:", ", ".join(f"{s} {copied.get(s, 0)}" for s in STATUSES))
    if any(copied.get(s, 0) != n for s, n in counts.items()):
        sys.exit("Counts don't match — check the tasks table.")
    print("Done. Set STORAGE = \"neon\" in Streamlit Secrets to switch the app.")


if __name__ == "__main__":
    main()
