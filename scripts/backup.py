"""Copy the whole platform into one folder: the tables, the accounts and the original track files.

    SUPABASE_URL=...  SUPABASE_SERVICE_KEY=...  python scripts/backup.py <folder>

Run by GitHub Actions (.github/workflows/backup.yml) every Monday and when asked: the folder is then packed,
encrypted with the BACKUP_PASSPHRASE secret and kept 90 days as the run's artifact. The free Supabase plan keeps no
backup of its own. Only the standard library is needed. What lands in the folder:

* ``tables/<name>.json``: every row of each table (outings with their traces, profiles, reports; the take-off
  register and the routes once they exist). Restored with ``scripts/restore_backup.py``.
* ``accounts.json``: the accounts (id, e-mail, dates) from Supabase Auth, so that the outings find their owners.
* ``files/<user id>/<file>``: the original track files of the private storage, as uploaded.
* ``manifest.json``: what was copied, when, with counts and sizes.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

TABLES = ("profiles", "outings", "reports", "takeoff_sites", "routes")  # every table of supabase/schema-v2.sql
ORDER = {"takeoff_sites": "id", "routes": "id"}  # a stable order for the pages (the others: created_at)
BUCKET = "track-files"
PAGE = 500


def rows(api, table: str) -> list | None:
    """Every row of a table, page by page; None when the table does not exist (yet)."""
    out, offset = [], 0
    while True:
        try:
            _, raw = api.request("GET", f"/rest/v1/{table}?select=*&order={ORDER.get(table, 'created_at')}.asc"
                                        f"&limit={PAGE}&offset={offset}")
        except RuntimeError as exc:
            if "-> 404" in str(exc) or "PGRST205" in str(exc) or "does not exist" in str(exc):
                return None
            raise
        page = json.loads(raw)
        out += page
        if len(page) < PAGE:
            return out
        offset += PAGE


def accounts(api) -> list:
    """The accounts of Supabase Auth (admin API, service key): what the outings need to find their owners."""
    out, page = [], 1
    while True:
        _, raw = api.request("GET", f"/auth/v1/admin/users?page={page}&per_page=1000")
        users = json.loads(raw).get("users", [])
        out += [{k: u.get(k) for k in ("id", "email", "created_at", "last_sign_in_at", "email_confirmed_at",
                                         "app_metadata", "user_metadata")} for u in users]
        if len(users) < 1000:
            return out
        page += 1


def stored_files(api, prefix: str = "") -> list[str]:
    """Paths of every file of the private bucket (one folder per person)."""
    paths, offset = [], 0
    while True:
        _, raw = api.request("POST", f"/storage/v1/object/list/{BUCKET}",
                             {"prefix": prefix, "limit": 1000, "offset": offset, "sortBy": {"column": "name", "order": "asc"}})
        items = json.loads(raw)
        for it in items:
            path = f"{prefix}{it['name']}"
            if it.get("id") is None:  # a folder
                paths += stored_files(api, path + "/")
            else:
                paths.append(path)
        if len(items) < 1000:
            return paths
        offset += 1000


def backup(api, folder: Path) -> dict:
    (folder / "tables").mkdir(parents=True, exist_ok=True)
    manifest = {"made_at": dt.datetime.now(dt.timezone.utc).isoformat(), "tables": {}, "files": 0, "file_bytes": 0}
    for table in TABLES:
        data = rows(api, table)
        if data is None:
            print(f"table {table}: not there, skipped")
            continue
        (folder / "tables" / f"{table}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        manifest["tables"][table] = len(data)
        print(f"table {table}: {len(data)} rows")
    users = accounts(api)
    (folder / "accounts.json").write_text(json.dumps(users, ensure_ascii=False), encoding="utf-8")
    manifest["accounts"] = len(users)
    print(f"accounts: {len(users)}")
    missing = []
    for path in stored_files(api):
        try:
            data = api.download(path)
        except RuntimeError as exc:
            missing.append(path)
            print(f"  file not copied: {path}: {exc}")
            continue
        target = folder / "files" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest["files"] += 1
        manifest["file_bytes"] += len(data)
    manifest["files_not_copied"] = missing
    print(f"files: {manifest['files']} ({manifest['file_bytes'] / 1e6:.1f} MB), not copied: {len(missing)}")
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def main() -> int:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from process_pending import Api

    if len(sys.argv) != 2:
        print(__doc__.splitlines()[2].strip(), file=sys.stderr)
        return 2
    url, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("SUPABASE_URL and SUPABASE_SERVICE_KEY are required", file=sys.stderr)
        return 1
    manifest = backup(Api(url, key), Path(sys.argv[1]))
    if manifest["files_not_copied"]:  # the backup is still kept: a warning on the run, the list in manifest.json
        print(f"::warning::{len(manifest['files_not_copied'])} track files could not be copied (see manifest.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
