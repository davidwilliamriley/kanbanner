"""Print a password hash to paste under [auth.users] in Streamlit secrets.

Usage:  python make_password_hash.py
"""

from getpass import getpass

import bcrypt

password = getpass("Password: ")
if password != getpass("Repeat password: "):
    raise SystemExit("Passwords don't match.")
if not password:
    raise SystemExit("Password can't be empty.")
if len(password.encode("utf-8")) > 72:
    raise SystemExit("Password can't be longer than 72 bytes (a bcrypt limit).")
print(bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8"))
