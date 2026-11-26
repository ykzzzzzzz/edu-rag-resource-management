from tests.conftest import DEMO_PASSWORD

API = "/api/v1/admin/users"


def _create(client, username="newuser01", role="student", display_name="新用户", password="Strong-pass-1"):
    return client.post(
        API,
        json={"username": username, "display_name": display_name, "password": password, "role": role},
    )


def test_admin_creates_user_and_new_user_can_login(admin_client, make_client):
    resp = _create(admin_client, username="teacher02", role="teacher", password="Strong-pass-1")
    assert resp.status_code == 201
    assert resp.json()["role"] == "teacher"
    assert "password" not in resp.json() and "password_hash" not in resp.json()

    login = make_client().post("/api/v1/auth/login", json={"username": "teacher02", "password": "Strong-pass-1"})
    assert login.status_code == 200


def test_duplicate_username_returns_409(admin_client, seed_users):
    resp = _create(admin_client, username="student01")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "username_taken"


def test_admin_can_list_and_filter_users(admin_client):
    _create(admin_client, username="stu02", role="student")
    resp = admin_client.get(API, params={"role": "student"})
    assert resp.status_code == 200
    usernames = {u["username"] for u in resp.json()["items"]}
    assert "stu02" in usernames and "student01" in usernames
    assert all(u["role"] == "student" for u in resp.json()["items"])


def test_disable_user_revokes_existing_session_immediately(admin_client, login, seed_users):
    student = login("student01")
    assert student.get("/api/v1/auth/me").status_code == 200

    resp = admin_client.patch(f"{API}/{seed_users['student01']}", json={"is_active": False})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    assert student.get("/api/v1/auth/me").status_code == 401


def test_admin_cannot_disable_self(admin_client, seed_users):
    resp = admin_client.patch(f"{API}/{seed_users['admin01']}", json={"is_active": False})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "cannot_disable_self"


def test_last_enabled_admin_cannot_change_own_role(admin_client, seed_users, db_session_factory):
    # 把第二个管理员停用，使 admin01 成为最后一个启用的管理员
    resp = admin_client.patch(f"{API}/{seed_users['admin02']}", json={"is_active": False})
    assert resp.status_code == 200

    resp = admin_client.patch(f"{API}/{seed_users['admin01']}", json={"role": "teacher"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "last_admin"


def test_last_enabled_admin_cannot_be_disabled_by_other_admin_path(admin_client, seed_users):
    # admin02 被降级为教师后，admin01 是唯一启用的管理员，不能再被降级
    assert admin_client.patch(f"{API}/{seed_users['admin02']}", json={"role": "teacher"}).status_code == 200
    resp = admin_client.patch(f"{API}/{seed_users['admin01']}", json={"role": "student"})
    assert resp.status_code == 409


def test_admin_can_demote_self_when_another_enabled_admin_exists(admin_client, seed_users):
    resp = admin_client.patch(f"{API}/{seed_users['admin01']}", json={"role": "teacher"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "teacher"


def test_reset_password_revokes_all_sessions_and_new_password_works(admin_client, login, make_client, seed_users):
    s1 = login("student01")
    s2 = login("student01")
    assert s1.get("/api/v1/auth/me").status_code == 200

    resp = admin_client.post(
        f"{API}/{seed_users['student01']}/reset-password", json={"new_password": "Brand-new-pass-2"}
    )
    assert resp.status_code == 204

    assert s1.get("/api/v1/auth/me").status_code == 401
    assert s2.get("/api/v1/auth/me").status_code == 401

    assert make_client().post(
        "/api/v1/auth/login", json={"username": "student01", "password": DEMO_PASSWORD}
    ).status_code == 401
    assert make_client().post(
        "/api/v1/auth/login", json={"username": "student01", "password": "Brand-new-pass-2"}
    ).status_code == 200


def test_non_admin_cannot_access_admin_routes(teacher_client, student_client, seed_users):
    for c in (teacher_client, student_client):
        assert c.get(API).status_code == 403
        assert _create(c, username="hacker01").status_code == 403
        assert c.patch(f"{API}/{seed_users['student01']}", json={"is_active": False}).status_code == 403
        assert c.post(
            f"{API}/{seed_users['student01']}/reset-password", json={"new_password": "Hack-pass-123"}
        ).status_code == 403


def test_anonymous_admin_access_returns_401(make_client):
    assert make_client().get(API).status_code == 401


def test_admin_patch_unknown_user_returns_404(admin_client):
    resp = admin_client.patch(f"{API}/00000000-0000-4000-8000-000000000999", json={"is_active": False})
    assert resp.status_code == 404
