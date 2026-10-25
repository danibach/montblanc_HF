"""Put a backup back (scripts/backup.py): an SQL file for the tables and the accounts, and the track files.

    cat hf-tracks-backup-YYYY-MM-DD.tar.gz.gpg.part-* > backup.tar.gz.gpg   # from the private backup repository
    gpg -d backup.tar.gz.gpg > backup.tar.gz && tar -xzf backup.tar.gz         # asks the passphrase
    python scripts/restore_backup.py backup                  # writes backup/restore.sql
    SUPABASE_URL=...  SUPABASE_SERVICE_KEY=...  python scripts/restore_backup.py backup --upload-files

Into a new or emptied Supabase project: run supabase/schema-v2.sql (and the migrations of the take-off register and
the routes when the backup has them), then restore.sql in the SQL Editor, then --upload-files. Rows that are still
there are left as they are (display names are put back), so running it twice does no harm.
restore.sql recreates the accounts directly in auth.users (id and e-mail): the passwordless sign-in works with them,
but Supabase does not document this way. Not yet tried on a real project: do it once on a test project.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# in the order the foreign keys need: owners first, the outings after the take-offs and routes they point to
ORDER = ("profiles", "takeoff_sites", "routes", "outings", "reports")
ON_CONFLICT = {"profiles": "(id) do update set display_name = excluded.display_name"}  # the sign-up trigger made it


def sql_json(rows: list) -> str:
    tag = f"j{secrets.token_hex(4)}"
    return f"${tag}${json.dumps(rows, ensure_ascii=False)}${tag}$"


def restore_sql(folder: Path) -> str:
    out = ["-- Restore of an H&F Tracks backup (scripts/restore_backup.py). Run in Supabase > SQL Editor, after",
           "-- supabase/schema-v2.sql. Existing rows are kept.", "begin;"]
    accounts = json.loads((folder / "accounts.json").read_text(encoding="utf-8"))
    if accounts:
        out.append(f"""insert into auth.users (instance_id, id, aud, role, email, email_confirmed_at, created_at, updated_at,
  raw_app_meta_data, raw_user_meta_data)
select '00000000-0000-0000-0000-000000000000', a.id, 'authenticated', 'authenticated', a.email, a.email_confirmed_at,
  a.created_at, now(), coalesce(a.app_metadata, '{{}}'::jsonb), coalesce(a.user_metadata, '{{}}'::jsonb)
from jsonb_to_recordset({sql_json(accounts)}::jsonb)
  as a(id uuid, email text, email_confirmed_at timestamptz, created_at timestamptz, app_metadata jsonb, user_metadata jsonb)
on conflict (id) do nothing;""")
    for table in ORDER:
        path = folder / "tables" / f"{table}.json"
        if not path.exists():
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not rows:
            continue
        conflict = ON_CONFLICT.get(table, "(id) do nothing")
        out.append(f"insert into public.{table} overriding system value\n"
                   f"select * from json_populate_recordset(null::public.{table}, {sql_json(rows)}::json)\n"
                   f"on conflict {conflict};")
    # the identity counters go on after the restored ids
    for table in ("reports", "takeoff_sites", "routes"):
        path = folder / "tables" / f"{table}.json"
        if path.exists() and json.loads(path.read_text(encoding="utf-8")):
            out.append(f"select setval(pg_get_serial_sequence('public.{table}', 'id'), "
                       f"coalesce((select max(id) from public.{table}), 1));")
    out.append("commit;")
    return "\n\n".join(out) + "\n"


def upload_files(folder: Path) -> int:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from process_pending import Api

    api = Api(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    root = folder / "files"
    count = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        name = path.relative_to(root).as_posix()
        # the file's own bytes (Api.request sends JSON): same folder and name as before, replaced if there
        req = urllib.request.Request(f"{api.url}/storage/v1/object/track-files/{urllib.parse.quote(name)}",
                                     data=path.read_bytes(), method="POST",
                                     headers=api.headers({"x-upsert": "true", "Content-Type": "application/octet-stream"}))
        with urllib.request.urlopen(req, timeout=120):
            count += 1
    return count


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    folder = Path(sys.argv[1])
    if "--upload-files" in sys.argv:
        print(f"track files uploaded: {upload_files(folder)}")
        return 0
    (folder / "restore.sql").write_text(restore_sql(folder), encoding="utf-8")
    print(f"written: {folder / 'restore.sql'} (run it in Supabase > SQL Editor)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
