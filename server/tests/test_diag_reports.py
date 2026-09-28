"""Rapports de diagnostic : envoi public limité, zip vérifié, accès admin seulement, purge."""
import io
import time
import zipfile

from app import db, diag_reports
from conftest import bearer


def make_zip(files=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in (files or {"dodotopia.log": b"ligne\n" * 10, "systeme.json": b"{}"}).items():
            zf.writestr(name, data)
    return buf.getvalue()


def send(client, data, token=None, **fields):
    return client.post("/api/diag-reports", files={"file": ("rapport.zip", data, "application/zip")},
                       data={"note": "la cuisine ne clique pas", "version": "2.1.0", "os": "Windows 11", **fields},
                       headers=bearer(token) if token else {})


def test_envoi_sans_compte_puis_lecture_admin(client, admin_token, user_token):
    r = send(client, make_zip())
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    assert len(code) == 8 and set(code) <= set(diag_reports.CODE_ALPHABET)

    # pas d'accès sans être admin
    assert client.get("/api/admin/diag-reports").status_code in (401, 403)
    assert client.get("/api/admin/diag-reports", headers=bearer(user_token)).status_code == 403

    lst = client.get("/api/admin/diag-reports", headers=bearer(admin_token)).json()
    item = next(i for i in lst["items"] if i["code"] == code)
    assert item["note"] == "la cuisine ne clique pas" and item["files"] == 2 and item["user_id"] is None
    det = client.get(f"/api/admin/diag-reports/{code.lower()}/files", headers=bearer(admin_token)).json()
    assert sorted(f["name"] for f in det["files"]) == ["dodotopia.log", "systeme.json"]
    dl = client.get(f"/api/admin/diag-reports/{code}", headers=bearer(admin_token))
    assert dl.status_code == 200 and zipfile.is_zipfile(io.BytesIO(dl.content))

    assert client.delete(f"/api/admin/diag-reports/{code}", headers=bearer(admin_token)).json()["ok"]
    assert client.get(f"/api/admin/diag-reports/{code}", headers=bearer(admin_token)).status_code == 404


def test_envoi_connecte_rattache_le_compte(client, user_token, admin_token):
    code = send(client, make_zip(), user_token).json()["code"]
    item = next(i for i in client.get("/api/admin/diag-reports", headers=bearer(admin_token)).json()["items"]
                if i["code"] == code)
    assert item["user_id"] is not None and item["username"]


def test_zip_refuses(client):
    assert send(client, b"pas un zip").status_code == 422
    assert send(client, make_zip({"../evil.txt": b"x"})).status_code == 422
    assert send(client, make_zip({f"f{i}.log": b"x" for i in range(70)})).status_code == 422
    big = make_zip({"zero.bin": b"\0" * (diag_reports.MAX_UNCOMPRESSED + 1)})
    assert send(client, big).status_code == 422


def test_taille_maximale(client):
    settings = client.app.state.settings
    too_big = b"PK" + b"\0" * (settings.MAX_DIAG_REPORT_BYTES + 10)
    assert send(client, too_big).status_code == 413


def test_purge_des_vieux_rapports(client):
    code = send(client, make_zip()).json()["code"]
    settings = client.app.state.settings
    path = diag_reports.report_file(settings, code)
    assert path.is_file()
    conn = db.connect(settings)
    try:
        assert diag_reports.purge(settings, conn) == 0
        assert diag_reports.purge(settings, conn, now=time.time() + settings.DIAG_REPORT_TTL_DAYS * 86400 + 60) >= 1
        assert conn.execute("SELECT 1 FROM diag_reports WHERE code=?", (code,)).fetchone() is None
    finally:
        conn.close()
    assert not path.exists()
