"""Where the board is saved: JSONBin (one JSON document) or Neon Postgres
(one row per task).

Pick the backend in Streamlit secrets:

    STORAGE = "jsonbin"      # default: JSONBIN_BIN_ID / JSONBIN_API_KEY
    STORAGE = "neon"         # DATABASE_URL_POOLED (or DATABASE_URL)

A board is {"backlog": [...], "doing": [...], "review": [...], "archive": [...]}
and every task carries an "id". The app changes tasks only through a store's
add / update / move / delete / archive_all methods, so both backends behave
the same way.
"""

import threading
import uuid
from datetime import date
from pathlib import Path

import requests

COLUMNS = ("backlog", "doing", "review")
STATUSES = (*COLUMNS, "archive")
SCHEMA = (Path(__file__).with_name("schema.sql")).read_text()


class StoreError(Exception):
    """The board couldn't be loaded or saved."""


def empty_board():
    return {status: [] for status in STATUSES}


def clean_tags(tags):
    # Trim, drop blanks and case-insensitive duplicates, keep the given order.
    # Square brackets would break the badge markdown, so they're removed.
    cleaned, seen = [], set()
    for tag in tags:
        tag = tag.replace("[", "").replace("]", "").strip()
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            cleaned.append(tag)
    return cleaned


def make_task(title, description="", due=None, created=None, tags=(), id=None):
    # Dates are stored as ISO strings so the board stays plain JSON
    return {
        "id": id or str(uuid.uuid4()),
        "title": title,
        "description": description,
        "due": due.isoformat() if due else None,
        "created": date.today().isoformat() if created is None else created,
        "tags": clean_tags(tags),
    }


def normalize_task(task):
    # Older boards stored each task as a bare string, without ids or tags
    if isinstance(task, str):
        return make_task(task, created="")
    normalized = {
        "id": task.get("id") or str(uuid.uuid4()),
        "title": task.get("title", ""),
        "description": task.get("description", ""),
        "due": task.get("due"),
        "created": task.get("created") or "",
        "tags": clean_tags(task.get("tags", [])),
    }
    if task.get("archived"):
        normalized["archived"] = task["archived"]
    return normalized


def normalize_board(data):
    # Boards saved before the archive existed have no "archive" list
    if not isinstance(data, dict) or not all(k in data for k in COLUMNS):
        return empty_board()
    return {k: [normalize_task(t) for t in data.get(k) or []] for k in STATUSES}


def get_store(secrets):
    if secrets.get("STORAGE", "jsonbin") == "neon":
        url = secrets.get("DATABASE_URL_POOLED") or secrets.get("DATABASE_URL")
        if not url:
            raise StoreError(
                "Missing DATABASE_URL_POOLED in Streamlit Secrets for Neon Storage."
            )
        return NeonStore(url)
    bin_id = secrets.get("JSONBIN_BIN_ID", "")
    api_key = secrets.get("JSONBIN_API_KEY", "")
    if not bin_id or not api_key:
        raise StoreError(
            "Missing JSONBIN_BIN_ID / JSONBIN_API_KEY in Streamlit Secrets."
        )
    return JsonBinStore(bin_id, api_key)


class JsonBinStore:
    """The whole board is one JSON document; every change saves all of it."""

    # Loading costs an API call, so the app keeps the board between reruns
    reload_each_run = False

    def __init__(self, bin_id, api_key):
        self.url = f"https://api.jsonbin.io/v3/b/{bin_id}"
        self.headers = {"X-Master-Key": api_key, "Content-Type": "application/json"}

    def load(self):
        try:
            resp = requests.get(f"{self.url}/latest", headers=self.headers, timeout=10)
            resp.raise_for_status()
            return normalize_board(resp.json().get("record", {}))
        except (requests.RequestException, ValueError) as e:
            raise StoreError("Couldn't Reach JSONBin.") from e

    def _save(self, board):
        try:
            resp = requests.put(self.url, headers=self.headers, json=board, timeout=10)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise StoreError(
                "Couldn't Save to JSONBin — Your Change May Not Persist."
            ) from e

    @staticmethod
    def _find(board, task_id):
        for status, tasks in board.items():
            for i, task in enumerate(tasks):
                if task["id"] == task_id:
                    return status, i
        return None, None

    def add(self, board, task):
        board["backlog"].append(task)
        self._save(board)

    def update(self, board, task_id, task, status):
        current, i = self._find(board, task_id)
        if current is None:
            return
        if status == current:
            board[current][i] = task
        else:
            board[current].pop(i)
            board[status].append(task)
        self._save(board)

    def move(self, board, task_id, target, today):
        current, i = self._find(board, task_id)
        if current is None:
            return
        task = board[current].pop(i)
        if target == "archive":
            task["archived"] = today.isoformat()
        else:
            task.pop("archived", None)
        board[target].append(task)
        self._save(board)

    def delete(self, board, task_id):
        current, i = self._find(board, task_id)
        if current is None:
            return
        board[current].pop(i)
        self._save(board)

    def archive_all(self, board, today):
        for task in board["review"]:
            task["archived"] = today.isoformat()
        board["archive"].extend(board["review"])
        board["review"] = []
        self._save(board)


class NeonStore:
    """One row per task in a Postgres "tasks" table; each change touches only
    the rows it affects, so edits from different devices don't overwrite each
    other. The board is reloaded on every rerun to pick up those edits."""

    reload_each_run = True

    # A task moved into a column goes to the end of it
    _NEXT_POSITION = (
        "(select coalesce(max(position), 0) + 1 from tasks where status = %(status)s)"
    )

    def __init__(self, url):
        self.url = url
        self._conn = None
        self._lock = threading.Lock()

    def _connect(self):
        import psycopg

        # prepare_threshold=None keeps it compatible with the pooled endpoint
        conn = psycopg.connect(
            self.url, autocommit=True, connect_timeout=15, prepare_threshold=None
        )
        conn.execute(SCHEMA)
        return conn

    def _run(self, sql, params=None, fetch=False):
        # One connection is kept open, since each new one costs several round
        # trips to the database. Neon closes it when the database sleeps, so a
        # broken connection is replaced and the statement tried once more.
        import psycopg

        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._conn is None or self._conn.closed:
                        self._conn = self._connect()
                    cur = self._conn.execute(sql, params)
                    return cur.fetchall() if fetch else None
                except psycopg.OperationalError as e:
                    if self._conn is not None:
                        self._conn.close()
                    self._conn = None
                    if attempt == 2:
                        raise StoreError("Couldn't Reach the Neon Database.") from e
                except psycopg.Error as e:
                    raise StoreError("Couldn't Save to the Neon Database.") from e

    def load(self):
        rows = self._run(
            "select id, title, description, due, created, tags, status, archived"
            " from tasks order by position, created, id",
            fetch=True,
        )
        board = empty_board()
        for id_, title, description, due, created, tags, status, archived in rows:
            task = {
                "id": str(id_),
                "title": title,
                "description": description,
                "due": due.isoformat() if due else None,
                "created": created.isoformat() if created else "",
                "tags": list(tags),
            }
            if archived:
                task["archived"] = archived.isoformat()
            board.setdefault(status, []).append(task)
        return board

    def add(self, board, task):
        self._run(
            "insert into tasks (id, title, description, due, created, tags, status,"
            " position) values (%(id)s, %(title)s, %(description)s, %(due)s,"
            f" %(created)s, %(tags)s, %(status)s, {self._NEXT_POSITION})",
            {**task, "created": task["created"] or None, "status": "backlog"},
        )

    def update(self, board, task_id, task, status):
        # Set expressions see the row's old values, so "status" below is the
        # column the task is leaving
        self._run(
            "update tasks set title = %(title)s, description = %(description)s,"
            " due = %(due)s, tags = %(tags)s,"
            " position = case when status = %(status)s then position"
            f" else {self._NEXT_POSITION} end,"
            " status = %(status)s, updated_at = now() where id = %(id)s",
            {**task, "id": task_id, "status": status},
        )

    def move(self, board, task_id, target, today):
        self._run(
            f"update tasks set status = %(status)s, position = {self._NEXT_POSITION},"
            " archived = %(archived)s, updated_at = now() where id = %(id)s",
            {
                "id": task_id,
                "status": target,
                "archived": today if target == "archive" else None,
            },
        )

    def delete(self, board, task_id):
        self._run("delete from tasks where id = %(id)s", {"id": task_id})

    def archive_all(self, board, today):
        self._run(
            "with base as (select coalesce(max(position), 0) as p from tasks"
            " where status = 'archive'),"
            " ordered as (select id, row_number() over (order by position, id) as rn"
            " from tasks where status = 'review')"
            " update tasks t set status = 'archive', archived = %(today)s,"
            " position = base.p + ordered.rn, updated_at = now()"
            " from ordered, base where t.id = ordered.id",
            {"today": today},
        )
