"""Print a password hash to paste under [auth.users] in Streamlit secrets.

Usage:  python make_password_hash.py
"""

from getpass import getpass

from auth import hash_password

password = getpass("Password: ")
if password != getpass("Repeat password: "):
    raise SystemExit("Passwords don't match.")
if not password:
    raise SystemExit("Password can't be empty.")
print(hash_password(password))
