"""幂等地创建演示账号和示例课程。

用法（在仓库根目录）：
    E:\\scf-env\\venv\\Scripts\\python.exe scripts\\seed.py

规则：
- 已存在的账号和课程保持原样，不重复创建，也不重置密码。
- 新建账号的随机演示密码追加写入 data/local/demo-accounts.txt（该目录已被 Git 忽略）。
- 终端只输出创建与跳过的数量，不输出密码。
"""

import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.db import make_engine  # noqa: E402
from app.models import Course, User  # noqa: E402
from app.security import hash_password  # noqa: E402

DEMO_ACCOUNTS = [
    ("admin", "演示管理员", "admin"),
    ("teacher01", "演示教师", "teacher"),
    ("student01", "演示学生", "student"),
]

SAMPLE_COURSES = [
    ("数据库原理", "事务、并发控制与查询处理"),
    ("计算机网络", "分层模型、传输与路由"),
    ("Python 程序设计", "语法基础、数据结构与标准库"),
]

CREDENTIALS_FILE = REPO_ROOT / "data" / "local" / "demo-accounts.txt"


def seed(settings: Settings | None = None, *, credentials_file: Path = CREDENTIALS_FILE) -> None:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    created_accounts: list[tuple[str, str, str]] = []
    skipped_accounts = 0
    created_courses = 0
    skipped_courses = 0

    with Session() as db:
        for username, display_name, role in DEMO_ACCOUNTS:
            exists = db.execute(select(User.id).where(User.username == username)).first()
            if exists:
                skipped_accounts += 1
                continue
            password = secrets.token_urlsafe(12)
            db.add(
                User(
                    username=username,
                    display_name=display_name,
                    password_hash=hash_password(password),
                    role=role,
                    is_active=True,
                )
            )
            created_accounts.append((username, role, password))

        for name, description in SAMPLE_COURSES:
            exists = db.execute(
                select(Course.id).where(func.lower(Course.name) == name.lower())
            ).first()
            if exists:
                skipped_courses += 1
                continue
            db.add(Course(name=name, description=description))
            created_courses += 1

        db.commit()

    if created_accounts:
        credentials_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"{username}\t{role}\t{password}" for username, role, password in created_accounts]
        with credentials_file.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    engine.dispose()
    print(f"账号：新建 {len(created_accounts)}，已存在跳过 {skipped_accounts}")
    if created_accounts:
        print(f"演示密码已写入 {credentials_file.relative_to(REPO_ROOT)}（Git 忽略）")
    print(f"课程：新建 {created_courses}，已存在跳过 {skipped_courses}")


if __name__ == "__main__":
    seed()
