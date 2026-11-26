from sqlalchemy import text

from tests.conftest import DEMO_PASSWORD

API = "/api/v1"


def test_three_roles_can_login_and_read_me(login, seed_users):
    for username, role in [("student01", "student"), ("teacher01", "teacher"), ("admin01", "admin")]:
        c = login(username)
        resp = c.get(f"{API}/auth/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == username
        assert body["role"] == role
        assert body["id"] == seed_users[username]
        assert set(body) == {"id", "username", "display_name", "role"}


def test_login_sets_httponly_samesite_cookie(make_client, seed_users):
    c = make_client()
    resp = c.post(f"{API}/auth/login", json={"username": "student01", "password": DEMO_PASSWORD})
    assert resp.status_code == 200
    set_cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "max-age=28800" in set_cookie  # 8 小时


def test_wrong_password_returns_401(make_client, seed_users):
    c = make_client()
    resp = c.post(f"{API}/auth/login", json={"username": "student01", "password": "wrong-password"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"


def test_unknown_user_and_wrong_password_return_same_message(make_client, seed_users):
    c = make_client()
    unknown = c.post(f"{API}/auth/login", json={"username": "nobody01", "password": DEMO_PASSWORD})
    wrong = c.post(f"{API}/auth/login", json={"username": "student01", "password": "wrong-password"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]


def test_disabled_user_cannot_login(make_client, seed_users, db_session_factory):
    from app.models import User

    with db_session_factory() as db:
        db.query(User).filter(User.username == "student01").update({"is_active": False})
        db.commit()
    resp = make_client().post(f"{API}/auth/login", json={"username": "student01", "password": DEMO_PASSWORD})
    assert resp.status_code == 401


def test_error_body_has_code_message_and_request_id(make_client):
    resp = make_client().post(f"{API}/auth/login", json={"username": "x", "password": "y"})
    assert resp.status_code == 401
    error = resp.json()["error"]
    assert set(error) == {"code", "message", "request_id"}
    assert error["request_id"]


def test_me_without_session_returns_401(make_client):
    assert make_client().get(f"{API}/auth/me").status_code == 401


def test_logout_revokes_session(login, seed_users):
    c = login("student01")
    assert c.get(f"{API}/auth/me").status_code == 200

    resp = c.post(f"{API}/auth/logout")
    assert resp.status_code == 204
    assert c.get(f"{API}/auth/me").status_code == 401


def test_session_token_stored_only_as_hash(login, seed_users, migrated_engine):
    c = login("student01")
    token = c.cookies.get("scf_session")
    assert token
    with migrated_engine.connect() as conn:
        stored = conn.execute(text("SELECT token_hash FROM sessions")).scalars().all()
    assert token not in stored
    assert len(stored) == 1 and len(stored[0]) == 64


def test_mode_endpoint(client):
    resp = client.get(f"{API}/system/mode")
    assert resp.status_code == 200
    assert resp.json() == {"qa_mode": "demo"}


def test_healthz_without_prefix(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["database"] == "ok"


def test_cross_origin_write_is_rejected(make_client, seed_users):
    c = make_client()
    resp = c.post(
        f"{API}/auth/login",
        json={"username": "student01", "password": DEMO_PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "origin_mismatch"


def test_write_without_origin_is_rejected(make_client, seed_users):
    c = make_client()
    c.headers.pop("Origin")
    resp = c.post(f"{API}/auth/login", json={"username": "student01", "password": DEMO_PASSWORD})
    assert resp.status_code == 403


def test_get_without_origin_is_allowed(client):
    # 只校验修改类请求，读取请求不要求 Origin
    resp = client.get(f"{API}/system/mode", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 200
