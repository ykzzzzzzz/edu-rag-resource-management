import os
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

PASSWORD_FILE = Path(r"E:\scf-env\postgres-init-password.txt")
TEST_DB_NAME = "scf_test"
FRONTEND_ORIGIN = "http://localhost:5173"
DEMO_PASSWORD = "Passw0rd-test-01"


def _test_database_url() -> str:
    """测试库连接串。优先读取 TEST_DATABASE_URL；否则用 scf_admin 账号连接 scf_test。

    密码只在内存中使用，不输出。
    """
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    password = PASSWORD_FILE.read_text(encoding="utf-8").strip()
    return f"postgresql+psycopg://scf_admin:{quote(password, safe='')}@127.0.0.1:55432/{TEST_DB_NAME}"


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _test_database_url()
    # 安全检查：只允许在 scf_test 上执行清表和重建 schema
    if not url.rstrip("/").endswith(f"/{TEST_DB_NAME}"):
        raise RuntimeError(f"测试连接串必须指向 {TEST_DB_NAME}，拒绝运行")
    return url


@pytest.fixture(scope="session")
def migrated_engine(database_url: str):
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        try:
            connection = engine.connect()
        except OperationalError:
            # 驱动的原始回溯可能包含带密码的连接参数。
            pytest.fail(f"无法连接测试数据库 {TEST_DB_NAME}，请检查服务、连接配置和凭据。", pytrace=False)
        with connection, connection.begin():
            connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))

        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        cfg.attributes["database_url"] = database_url
        try:
            command.upgrade(cfg, "head")
        except OperationalError as exc:
            if exc.connection_invalidated or exc.statement is None:
                pytest.fail(f"迁移时无法连接测试数据库 {TEST_DB_NAME}。", pytrace=False)
            raise
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(migrated_engine):
    """每个用例前清空业务表，保证用例之间相互隔离。"""
    with migrated_engine.begin() as conn:
        conn.execute(text("TRUNCATE resource_reviews, resources, sessions, users, courses CASCADE"))
    yield


@pytest.fixture
def db_session_factory(migrated_engine):
    return sessionmaker(bind=migrated_engine, expire_on_commit=False)


@pytest.fixture
def storage_dir(tmp_path):
    """资源原件的临时存储目录。用例结束后由 pytest 的 tmp_path 机制清理，不会写入仓库。"""
    path = tmp_path / "uploads"
    path.mkdir()
    return path


@pytest.fixture
def app(database_url: str, monkeypatch, storage_dir):
    from app.config import Settings
    from app.main import create_app

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("RESOURCE_STORAGE_DIR", str(storage_dir))
    monkeypatch.setenv("QA_MODE", "demo")
    monkeypatch.setenv("FRONTEND_ORIGIN", f"{FRONTEND_ORIGIN},http://127.0.0.1:5173")
    application = create_app(Settings())
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app):
    """默认携带合法 Origin 的客户端。每个客户端持有独立 Cookie 罐。"""
    with TestClient(app, headers={"Origin": FRONTEND_ORIGIN}) as c:
        yield c


@pytest.fixture
def make_client(app):
    def _make() -> TestClient:
        return TestClient(app, headers={"Origin": FRONTEND_ORIGIN})

    return _make


@pytest.fixture
def seed_users(db_session_factory):
    """直接写入三种角色的账号（管理员两名以便测试），返回用户名到用户 ID 的映射。"""
    from app.models import User
    from app.security import hash_password

    specs = [
        ("admin01", "管理员甲", "admin"),
        ("admin02", "管理员乙", "admin"),
        ("teacher01", "教师甲", "teacher"),
        ("teacherx", "教师乙", "teacher"),
        ("student01", "学生甲", "student"),
    ]
    ids: dict[str, str] = {}
    with db_session_factory() as db:
        for username, display_name, role in specs:
            user = User(
                username=username,
                display_name=display_name,
                password_hash=hash_password(DEMO_PASSWORD),
                role=role,
                is_active=True,
            )
            db.add(user)
            db.flush()
            ids[username] = str(user.id)
        db.commit()
    return ids


@pytest.fixture
def login(make_client):
    def _login(username: str, password: str = DEMO_PASSWORD) -> TestClient:
        c = make_client()
        resp = c.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert resp.status_code == 200, resp.text
        return c

    return _login


@pytest.fixture
def admin_client(login, seed_users):
    return login("admin01")


@pytest.fixture
def teacher_client(login, seed_users):
    return login("teacher01")


@pytest.fixture
def student_client(login, seed_users):
    return login("student01")


@pytest.fixture
def teacher2_client(login, seed_users):
    return login("teacherx")


@pytest.fixture
def course(admin_client) -> dict:
    resp = admin_client.post("/api/v1/courses", json={"name": "数据库原理"})
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture
def course2(admin_client) -> dict:
    resp = admin_client.post("/api/v1/courses", json={"name": "计算机网络"})
    assert resp.status_code == 201
    return resp.json()


class Actors:
    """四个已登录的客户端：资源所有者教师、另一名教师、管理员、学生。"""

    def __init__(self, owner, other, admin, student):
        self.owner = owner
        self.other = other
        self.admin = admin
        self.student = student


@pytest.fixture
def actors(teacher_client, teacher2_client, admin_client, student_client) -> Actors:
    return Actors(teacher_client, teacher2_client, admin_client, student_client)
