"""Initialize and run the local, isolated M5 experiment environment."""

import argparse
import secrets
import sys
from pathlib import Path

import psycopg
import uvicorn
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path[:0] = [str(BACKEND), str(ROOT)]

from app.config import Settings
from app.db import make_engine
from app.index_worker import DocumentProcessor, run_once
from app.main import create_app
from scripts.seed import seed

HOST = "127.0.0.1"
POSTGRES_PORT = 55432
API_PORT = 8015
DATABASE = "scf_experiment"
ROLE = "scf_experiment_app"
LOCAL = ROOT / "data" / "local" / "experiment"
APP_PASSWORD = LOCAL / "db-password.txt"
ADMIN_PASSWORD = Path(r"E:\scf-env\postgres-init-password.txt")
MODEL_CACHE = Path(r"E:\scf-env\hf-cache")


def _connect_admin(database: str):
    return psycopg.connect(
        host=HOST, port=POSTGRES_PORT, user="scf_admin", dbname=database,
        password=ADMIN_PASSWORD.read_text(encoding="utf-8").strip(), autocommit=True,
    )


def _initialize_database() -> str:
    LOCAL.mkdir(parents=True, exist_ok=True)
    with _connect_admin("postgres") as admin:
        owner = admin.execute(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s", (DATABASE,)
        ).fetchone()
        if owner and owner[0] != ROLE:
            raise RuntimeError("实验库已存在，但所有者与实验账号不一致")
        role = admin.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolcanlogin FROM pg_roles WHERE rolname = %s", (ROLE,)
        ).fetchone()
        if role and (role != (False, False, False, True) or not APP_PASSWORD.is_file()):
            raise RuntimeError("实验数据库账号或本地凭据不符合预期")
        if not APP_PASSWORD.exists():
            with APP_PASSWORD.open("x", encoding="utf-8") as handle:
                handle.write(secrets.token_hex(32))
        password = APP_PASSWORD.read_text(encoding="utf-8").strip()
        if role is None:
            admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(ROLE), sql.Literal(password)))
        if owner is None:
            admin.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(DATABASE), sql.Identifier(ROLE)))
    with _connect_admin(DATABASE) as admin:
        admin.execute("CREATE EXTENSION IF NOT EXISTS vector")
    return password


def _settings(password: str, cache: Path) -> Settings:
    if not password:
        raise RuntimeError("实验库密码文件为空")
    url = URL.create("postgresql+psycopg", ROLE, password, HOST, POSTGRES_PORT, DATABASE)
    return Settings(
        _env_file=None, database_url=url.render_as_string(hide_password=False),
        qa_mode="demo", llm_api_key="", resource_storage_dir=LOCAL / "uploads", hf_home=cache,
        frontend_origin=f"http://{HOST}:{API_PORT}", session_cookie_secure=False,
    )


def _migrate_and_seed(settings: Settings) -> None:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.attributes["database_url"] = settings.database_url
    command.upgrade(cfg, "head")
    seed(settings, credentials_file=LOCAL / "demo-accounts.txt")


def _index(settings: Settings) -> None:
    engine = make_engine(settings.database_url)
    factory = sessionmaker(bind=engine)
    processor = DocumentProcessor(settings)
    try:
        processed = 0
        while run_once(factory, settings, processor):
            processed += 1
        print(f"本次处理 {processed} 项实验资料索引任务")
    finally:
        processor.close()
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "serve", "index"))
    parser.add_argument("--hf-home", type=Path, default=MODEL_CACHE)
    args = parser.parse_args()
    try:
        password = (
            _initialize_database() if args.action == "init" else APP_PASSWORD.read_text(encoding="utf-8").strip()
        )
        settings = _settings(password, args.hf_home)
        if args.action == "init":
            _migrate_and_seed(settings)
        elif args.action == "serve":
            uvicorn.run(create_app(settings), host=HOST, port=API_PORT)
        else:
            _index(settings)
        return 0
    except (OSError, psycopg.Error, SQLAlchemyError) as exc:
        print(f"实验环境操作失败（{type(exc).__name__}）。请检查本机数据库和凭据文件。", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
