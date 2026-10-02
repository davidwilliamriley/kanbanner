# 🎈 Kanbanner App

A simple Streamlit app for Kanban Boards

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
link_days = 365   # optional, how long a Remember Device link works

[auth.users]
david = "$2b$12$..."
```

- Make the cookie key with
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- Make each password hash with `uv run python make_password_hash.py`, which
  asks for the password and prints a bcrypt hash to paste (bcrypt hashes from
  other tools, starting `$2b$`, `$2a$` or `$2y$`, work too; passwords are
  limited to 72 bytes). Passwords themselves are never
  stored.
- If a browser doesn't keep you logged in (some phone browsers and privacy
  settings clear cookies), use **Remember Device** in the toolbar. It gives a
  personal link that logs you in when opened; bookmark it or add it to your
  home screen. Anyone with the link can open the board, so keep it private.
  Changing your password or the cookie key cancels every such link.
- To add a user, add a line under `[auth.users]`. To remove one, delete their
  line. Changing a user's password or the cookie key logs out any browser
  that was logged in with the old one.

### Where the board is saved

The board can be saved in **JSONBin** (the original setup: the whole board is
one JSON document) or in a **Neon** Postgres database (one row per task, so
changes made on different devices don't overwrite each other). Choose with
`STORAGE` in your Streamlit secrets:

```toml
# JSONBin (the default when STORAGE isn't set)
JSONBIN_BIN_ID = "your-bin-id"
JSONBIN_API_KEY = "your-x-master-key"

# Neon
STORAGE = "neon"
DATABASE_URL_POOLED = "postgresql://...-pooler...neon.tech/neondb?sslmode=require&channel_binding=require"
```

#### Moving from JSONBin to Neon

1. In Neon, create a project and copy the **pooled** connection string
   (`DATABASE_URL_POOLED`, its host contains `-pooler`).
2. On your own machine, put `DATABASE_URL_POOLED` and your JSONBin settings
   in `.streamlit/secrets.toml` (never commit this file), then run:

   ```
   $ uv run python migrate_to_neon.py --dry-run   # shows what will be copied
   $ uv run python migrate_to_neon.py             # copies the board into Neon
   ```

   It creates the `tasks` table, copies every column in order (with archived
   dates), and checks the counts. It refuses to run twice; `--replace`
   deletes the copied tasks and starts again. To copy a saved board file
   instead of reading JSONBin, use `--from-file board.json`.
3. In the app's **Settings → Secrets** on Streamlit Community Cloud, add
   `STORAGE = "neon"` and `DATABASE_URL_POOLED = "..."`, then reboot the app.

To switch back, remove `STORAGE` (or set it to `"jsonbin"`). JSONBin isn't
changed by the move, but changes made while using Neon aren't copied back.

Neon's free database sleeps when unused and wakes on the next visit, so the
first load after a quiet spell can take a second or two.

### Weekly backups

A GitHub Action (`.github/workflows/backup.yml`) copies the Neon board every
Sunday at about 3 am Sydney time and keeps each copy for 90 days under the
run's **Artifacts**. The repository is public, so anyone can download those
files: each backup is encrypted with a passphrase only you know, and the
logs show task counts, never task text.

To set it up, in GitHub open **Settings → Secrets and variables → Actions**
and add two repository secrets:

- `DATABASE_URL_POOLED`: the same pooled Neon connection string the app uses.
- `BACKUP_PASSPHRASE`: at least 12 characters. Keep it in a password
  manager; without it the backups can't be opened.

To check it works, open **Actions → Weekly Board Backup → Run workflow**.
GitHub pauses scheduled workflows in a public repository after 60 days with
no commits; it emails you first, and **Enable workflow** on that page turns
it back on.

To restore, download the artifact, unzip it, then on your own machine (with
`DATABASE_URL_POOLED` in `.streamlit/secrets.toml`):

```
$ uv run --with cryptography python backup_board.py decrypt backup-2026-10-04.kbk
$ uv run python migrate_to_neon.py --from-file board.json --replace
```

`decrypt` asks for the passphrase and writes `board.json`; `--replace`
deletes the tasks in Neon and loads the backup in their place. Delete
`board.json` afterwards (it's ignored by git, but it is your board in plain
text).
