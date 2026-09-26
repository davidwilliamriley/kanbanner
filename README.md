# 🎈 Blank app template

A simple Streamlit app template for you to modify!

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://blank-app-template.streamlit.app/)

### How to run it on your own machine

Prerequisite: install `uv` if you don't already have it.

```
$ curl -LsSf https://astral.sh/uv/install.sh | sh
```

1. Sync the dependencies

   ```
   $ uv sync
   ```

2. Run the app

   ```
   $ uv run streamlit run streamlit_app.py
   ```

### Logging in

The board asks for a username and password, and a signed cookie keeps you
logged in for 30 days (or until you click **Log Out**). Add these to your
Streamlit secrets (`.streamlit/secrets.toml` locally, or the app's
**Settings → Secrets** on Streamlit Community Cloud) before deploying, or
the app will stay locked:

```toml
[auth]
cookie_key = "paste-a-long-random-string-here"
cookie_days = 30  # optional

[auth.users]
david = "pbkdf2_sha256$600000$..."
```

- Make the cookie key with
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- Make each password hash with `python make_password_hash.py`, which asks for
  the password and prints the hash to paste. Passwords themselves are never
  stored.
- To add a user, add a line under `[auth.users]`. To remove one, delete their
  line. Changing a user's password or the cookie key logs out any browser
  that was logged in with the old one.
