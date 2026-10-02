"""Encrypted backups of the board stored in Neon.

    python backup_board.py export                  # writes backup-YYYY-MM-DD.kbk
    python backup_board.py decrypt backup-....kbk  # writes board.json

The weekly GitHub Action (.github/workflows/backup.yml) runs "export". The
repository is public, so backups are encrypted with BACKUP_PASSPHRASE and
the script only ever prints task counts, never task text.

To restore, decrypt a backup and copy it back into Neon:

    python backup_board.py decrypt backup-2026-10-04.kbk
    python migrate_to_neon.py --from-file board.json --replace

Settings come from environment variables or .streamlit/secrets.toml:
DATABASE_URL_POOLED (or DATABASE_URL) and BACKUP_PASSPHRASE. "decrypt" asks
for the passphrase if BACKUP_PASSPHRASE isn't set. Needs the "cryptography"
package: uv run --with cryptography python backup_board.py ...
"""

import argparse
import getpass
import hashlib
import json
import os
import secrets
import sys
import tomllib
from datetime import date
from pathlib import Path

from store import STATUSES, NeonStore, StoreError

MAGIC = b"KBK1"  # file format: MAGIC + salt (16) + nonce (12) + AES-GCM ciphertext


def setting(name, *fallbacks):
    path = Path(".streamlit/secrets.toml")
    file_secrets = (
        tomllib.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    )
    for key in (name, *fallbacks):
        value = os.environ.get(key) or file_secrets.get(key)
        if value:
            return value
    return None


def derive_key(passphrase, salt):
    # scrypt makes guessing the passphrase from a stolen backup expensive
    return hashlib.scrypt(
        passphrase.encode(), salt=salt, n=2**15, r=8, p=1, maxmem=64 * 1024**2,
        dklen=32,
    )


def encrypt(data, passphrase):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    ciphertext = AESGCM(derive_key(passphrase, salt)).encrypt(nonce, data, MAGIC)
    return MAGIC + salt + nonce + ciphertext


def decrypt(blob, passphrase):
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not blob.startswith(MAGIC):
        sys.exit("That isn't a board backup file.")
    salt, nonce, ciphertext = blob[4:20], blob[20:32], blob[32:]
    try:
        return AESGCM(derive_key(passphrase, salt)).decrypt(nonce, ciphertext, MAGIC)
    except InvalidTag:
        sys.exit("Wrong passphrase, or the backup file is damaged.")


def counts(board):
    return ", ".join(f"{s} {len(board.get(s, []))}" for s in STATUSES)


def export(args):
    url = setting("DATABASE_URL_POOLED", "DATABASE_URL")
    passphrase = setting("BACKUP_PASSPHRASE")
    if not url or not passphrase:
        sys.exit("Set DATABASE_URL_POOLED and BACKUP_PASSPHRASE.")
    if len(passphrase) < 12:
        sys.exit("BACKUP_PASSPHRASE should be at least 12 characters.")
    try:
        board = NeonStore(url).load()
    except StoreError as e:
        sys.exit(str(e))
    data = json.dumps(
        {"exported": date.today().isoformat(), **board}, ensure_ascii=False
    ).encode("utf-8")
    out = Path(args.out or f"backup-{date.today().isoformat()}.kbk")
    out.write_bytes(encrypt(data, passphrase))
    print(f"Backed up {counts(board)} to {out}")


def decrypt_file(args):
    passphrase = setting("BACKUP_PASSPHRASE") or getpass.getpass("Passphrase: ")
    board = json.loads(decrypt(Path(args.file).read_bytes(), passphrase))
    out = Path(args.out)
    if out.exists() and not args.force:
        sys.exit(f"{out} already exists; use --out to pick another name or --force.")
    board.pop("exported", None)
    out.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {counts(board)} to {out}")


def main():
    parser = argparse.ArgumentParser(description="Encrypted board backups.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("export", help="back up the board from Neon")
    p.add_argument("--out", help="file to write (default backup-DATE.kbk)")
    p.set_defaults(run=export)
    p = sub.add_parser("decrypt", help="turn a backup back into board JSON")
    p.add_argument("file")
    p.add_argument("--out", default="board.json")
    p.add_argument("--force", action="store_true", help="overwrite --out")
    p.set_defaults(run=decrypt_file)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
