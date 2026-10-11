# 🎈 Kanbanner App

A simple Streamlit app for Kanban Boards

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

Before the board will open, logins and storage need to be set up in your
Streamlit secrets. See [docs/admin.md](docs/admin.md) for that, and for weekly backups
and restoring them.
