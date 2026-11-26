API = "/api/v1/courses"


def test_admin_creates_course_visible_to_all_roles(admin_client, teacher_client, student_client):
    resp = admin_client.post(API, json={"name": "数据库原理", "description": "事务与并发"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "数据库原理"

    for c in (admin_client, teacher_client, student_client):
        names = [item["name"] for item in c.get(API).json()["items"]]
        assert "数据库原理" in names


def test_duplicate_course_name_returns_409(admin_client):
    assert admin_client.post(API, json={"name": "计算机网络"}).status_code == 201
    resp = admin_client.post(API, json={"name": "计算机网络"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "course_name_taken"


def test_duplicate_course_name_is_case_insensitive(admin_client):
    assert admin_client.post(API, json={"name": "Python 程序设计"}).status_code == 201
    assert admin_client.post(API, json={"name": "python 程序设计"}).status_code == 409


def test_rename_course_to_existing_name_returns_409(admin_client):
    admin_client.post(API, json={"name": "数据库原理"})
    other = admin_client.post(API, json={"name": "计算机网络"}).json()
    resp = admin_client.patch(f"{API}/{other['id']}", json={"name": "数据库原理"})
    assert resp.status_code == 409


def test_admin_renames_course(admin_client):
    course = admin_client.post(API, json={"name": "旧名称"}).json()
    resp = admin_client.patch(f"{API}/{course['id']}", json={"name": "新名称"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "新名称"


def test_non_admin_cannot_create_or_rename_course(teacher_client, student_client, admin_client):
    course = admin_client.post(API, json={"name": "数据库原理"}).json()
    for c in (teacher_client, student_client):
        assert c.post(API, json={"name": "越权课程"}).status_code == 403
        assert c.patch(f"{API}/{course['id']}", json={"name": "改名"}).status_code == 403


def test_anonymous_cannot_list_courses(make_client):
    assert make_client().get(API).status_code == 401


def test_blank_course_name_is_rejected(admin_client):
    assert admin_client.post(API, json={"name": "   "}).status_code == 422
