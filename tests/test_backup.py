"""scripts/backup.py and scripts/restore_backup.py against a pretend Supabase."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import backup  # noqa: E402
import restore_backup  # noqa: E402

OUTINGS = [{"id": f"o{i}", "user_id": "u1", "title": f"Outing {i}"} for i in range(backup.PAGE + 3)]
FILES = {"": [{"name": "u1", "id": None}, {"name": "u2", "id": None}],
         "u1/": [{"name": "a.gpx", "id": "f1"}], "u2/": [{"name": "b.fit", "id": "f2"}, {"name": "c.igc", "id": "f3"}]}


class FakeApi:
    def request(self, method, path, body=None, extra=None):
        if path.startswith("/rest/v1/outings"):
            offset = int(path.split("offset=")[1])
            return None, json.dumps(OUTINGS[offset:offset + backup.PAGE]).encode()
        if path.startswith("/rest/v1/profiles"):
            return None, json.dumps([{"id": "u1", "display_name": "Sarah"}]).encode()
        if path.startswith("/rest/v1/"):  # reports empty; take-off register and routes not there yet
            if "reports" in path:
                return None, b"[]"
            raise RuntimeError(f"GET {path} -> 404: relation does not exist")
        if path.startswith("/auth/v1/admin/users"):
            return None, json.dumps({"users": [{"id": "u1", "email": "s@example.com", "created_at": "2026-01-01T00:00:00Z"}]}).encode()
        if path.startswith("/storage/v1/object/list/"):
            return None, json.dumps(FILES[body["prefix"]]).encode()
        raise AssertionError(path)

    def download(self, path):
        return f"bytes of {path}".encode()


def test_backup_copies_tables_accounts_and_files(tmp_path):
    m = backup.backup(FakeApi(), tmp_path)
    assert m["tables"] == {"profiles": 1, "outings": backup.PAGE + 3, "reports": 0}  # all pages; missing tables skipped
    assert m["accounts"] == 1 and m["files"] == 3 and not m["files_not_copied"]
    assert (tmp_path / "files" / "u2" / "c.igc").read_bytes() == b"bytes of u2/c.igc"
    assert len(json.loads((tmp_path / "tables" / "outings.json").read_text(encoding="utf-8"))) == backup.PAGE + 3


def test_restore_sql_in_foreign_key_order(tmp_path):
    backup.backup(FakeApi(), tmp_path)
    sql = restore_backup.restore_sql(tmp_path)
    assert sql.index("insert into auth.users") < sql.index("public.profiles") < sql.index("public.outings")
    assert "on conflict (id) do update set display_name" in sql  # the sign-up trigger made the profile already
    assert "public.reports" not in sql  # no row: nothing to insert
    assert sql.strip().startswith("--") and sql.strip().endswith("commit;")
    assert "Outing 502" in sql
