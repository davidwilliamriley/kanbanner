"""Username/password login for the board, with a signed "stay logged in" cookie.

Users and the cookie signing key live in Streamlit secrets:

    [auth]
    cookie_key = "a long random string"   # signs login cookies
    cookie_days = 30                       # optional, how long a login lasts

    [auth.users]
    david = "$2b$12$..."   # bcrypt hash of the password

Create a password hash with:  python make_password_hash.py
"""

import base64
import functools
import hashlib
import hmac
import json
import time

import bcrypt
import streamlit as st

COOKIE_NAME = "kanban_auth"


def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_pbkdf2(password, stored):
    # Hashes made by the earlier helper ("pbkdf2_sha256$...") still work
    try:
        _, iterations, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(iterations)
        ).hex()
    except ValueError:
        return False
    return hmac.compare_digest(candidate, digest)


def verify_password(password, stored):
    if stored.startswith("pbkdf2_sha256$"):
        return _verify_pbkdf2(password, stored)
    try:
        return bcrypt.checkpw(password.encode(), stored.encode())
    except ValueError:  # malformed hash, or a password over bcrypt's 72 bytes
        return False


@functools.cache
def _dummy_hash():
    return hash_password("dummy")


def _config():
    auth = st.secrets.get("auth", {})
    users = dict(auth.get("users", {}))
    key = auth.get("cookie_key", "")
    days = int(auth.get("cookie_days", 30))
    return users, key, days


def _sign(key, payload):
    return hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(username, users, key, days):
    # Signing over the stored password hash means changing a user's password
    # (or removing the user) invalidates their existing cookies
    expires = int(time.time()) + days * 86400
    name = base64.urlsafe_b64encode(username.encode()).decode().rstrip("=")
    payload = f"{name}.{expires}"
    return f"{payload}.{_sign(key, payload + users[username])}"


def read_token(token, users, key):
    try:
        name, expires, signature = token.split(".")
        username = base64.urlsafe_b64decode(name + "=" * (-len(name) % 4)).decode()
        expired = int(expires) < time.time()
    except ValueError:
        return None
    if username not in users or expired:
        return None
    expected = _sign(key, f"{name}.{expires}{users[username]}")
    return username if hmac.compare_digest(signature, expected) else None


def _write_cookie(value, max_age):
    # Cookies can't be set from Python, so a tiny script sets it in the browser.
    # The value is our own signed token, never user input.
    st.html(
        "<script>document.cookie = "
        + json.dumps(
            f"{COOKIE_NAME}={value}; path=/; max-age={max_age}; SameSite=Strict"
        )
        + " + (location.protocol === 'https:' ? '; Secure' : '');</script>",
        unsafe_allow_javascript=True,
    )


def require_login():
    """Return the logged-in username, or show the login form and stop the app."""
    users, key, days = _config()
    if not users or not key:
        st.error(
            "Login Isn't Set Up — Add [auth] cookie_key and [auth.users] "
            "to Streamlit Secrets."
        )
        st.stop()

    state = st.session_state
    if state.get("user") in users:
        if "new_cookie" in state:
            _write_cookie(state.pop("new_cookie"), days * 86400)
        return state.user

    if state.pop("clear_cookie", False):
        _write_cookie("", 0)

    # Cookies arrive with the page load, so they're stale after a log out in
    # the same browser session — ignore them until the page is reloaded
    if not state.get("logged_out"):
        token = st.context.cookies.get(COOKIE_NAME)
        user = token and read_token(token, users, key)
        if user:
            state.user = user
            return user

    st.title("📌 Kanban Board")
    with st.form("login_form", width=400):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log In", type="primary")
    if submitted:
        stored = users.get(username.strip())
        # Check a dummy hash for unknown users so both cases take the same time
        if verify_password(password, stored or _dummy_hash()) and stored:
            state.user = username.strip()
            state.new_cookie = make_token(state.user, users, key, days)
            state.pop("logged_out", None)
            st.rerun()
        time.sleep(1)  # slow down password guessing
        st.error("Incorrect Username or Password.")
    st.stop()


def log_out():
    for name in ("user", "new_cookie"):
        st.session_state.pop(name, None)
    st.session_state.logged_out = True
    st.session_state.clear_cookie = True
