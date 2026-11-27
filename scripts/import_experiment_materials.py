"""通过正式资源接口导入本机实验资料并写出资料编号映射。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
MATERIAL_MANIFEST = ROOT / "data" / "samples" / "materials" / "manifest.json"
MIME_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
}
API = "/api/v1"


class ImportFailure(Exception):
    """可在终端显示的导入错误。"""


@dataclass(frozen=True)
class Material:
    id: str
    course: str
    title: str
    filename: str
    mime_type: str
    sha256: str
    data: bytes

    @property
    def description(self) -> str:
        return f"M5 实验资料编号：{self.id}"


def load_materials(manifest: Path) -> list[Material]:
    root = manifest.resolve().parent
    rows = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if not isinstance(rows, list) or not rows:
        raise ImportFailure("实验资料清单为空或格式无效。")
    materials = []
    seen_ids = set()
    seen_titles = set()
    seen_filenames = set()
    for row in rows:
        document_id = row["id"]
        course = row["course"]
        title = row["title"]
        format_ = row["format"]
        path = (root / row["relative_path"]).resolve()
        if (
            not re.fullmatch(r"[A-Z]+-\d+", document_id)
            or not path.is_relative_to(root)
            or path.suffix.lower() != f".{format_}"
            or format_ not in MIME_TYPES
        ):
            raise ImportFailure("实验资料清单含无效编号、文件路径或格式。")
        if document_id in seen_ids or (course, title) in seen_titles or (course, path.name) in seen_filenames:
            raise ImportFailure(f"{document_id} 的编号、课程标题或文件名重复。")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != row["size_bytes"] or digest != row["sha256"]:
            raise ImportFailure(f"{document_id} 与清单的文件大小或 SHA-256 不一致。")
        materials.append(Material(document_id, course, title, path.name, MIME_TYPES[format_], digest, data))
        seen_ids.add(document_id)
        seen_titles.add((course, title))
        seen_filenames.add((course, path.name))
    return materials


def _credentials(path: Path) -> dict[str, tuple[str, str]]:
    required = {"teacher01": "teacher", "admin": "admin"}
    credentials = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        fields = line.split("\t")
        if len(fields) == 3:
            username, role, password = fields
            if required.get(username) == role and password:
                credentials[role] = (username, password)
    if credentials.keys() != {"teacher", "admin"}:
        raise ImportFailure("实验账号文件必须包含 teacher01 和 admin 的本地登录凭据。")
    return credentials


def _request(client: httpx.Client, method: str, path: str, expected: int, label: str, **kwargs) -> httpx.Response:
    try:
        response = client.request(method, f"{API}{path}", **kwargs)
    except httpx.RequestError:
        raise ImportFailure(f"{label} 请求失败，请检查本地实验服务。") from None
    if response.status_code != expected:
        raise ImportFailure(f"{label}失败，HTTP {response.status_code}。")
    return response


def _list_resources(admin: httpx.Client) -> list[dict]:
    resources = []
    page = 1
    while True:
        payload = _request(admin, "GET", "/admin/resources", 200, "读取实验资源", params={
            "page": page, "page_size": 100,
        }).json()
        resources.extend(payload["items"])
        if len(resources) >= payload["total"]:
            return resources
        if not payload["items"]:
            raise ImportFailure("资源列表在读取时发生变化，请重试。")
        page += 1


def _existing_resources(admin, materials, courses, owner_id) -> dict[str, dict]:
    resources = _list_resources(admin)
    by_title = {(courses[item.course], item.title): item for item in materials}
    existing = {}
    for resource in resources:
        material = by_title.get((resource["course_id"], resource["title"]))
        if material is None or resource["description"] != material.description:
            raise ImportFailure("目标库含本批实验清单之外的资源，请确认使用独立实验库。")
        if material.id in existing or resource["owner_id"] != owner_id:
            raise ImportFailure(f"{material.id} 在目标库有重复资源或资源所有者不符。")
        if resource["original_filename"] != material.filename or resource["size_bytes"] != len(material.data):
            raise ImportFailure(f"{material.id} 在目标库的文件元信息与清单不一致。")
        if resource["review_status"] not in {"draft", "pending", "published"}:
            raise ImportFailure(f"{material.id} 在目标库已驳回或下架，请先在系统中处理。")
        stored = _request(admin, "GET", f"/resources/{resource['id']}/download", 200, f"核对 {material.id} 原件")
        if hashlib.sha256(stored.content).hexdigest() != material.sha256:
            raise ImportFailure(f"{material.id} 在目标库的原件 SHA-256 不一致。")
        existing[material.id] = resource
    return existing


def import_materials(teacher: httpx.Client, admin: httpx.Client, materials: list[Material], owner_id: str) -> dict[str, str]:
    courses = {row["name"]: row["id"] for row in _request(teacher, "GET", "/courses", 200, "读取课程").json()["items"]}
    if any(material.course not in courses for material in materials):
        raise ImportFailure("实验库缺少清单所需的课程，请先初始化课程。")
    existing = _existing_resources(admin, materials, courses, owner_id)

    mapping = {}
    for item in materials:
        resource = existing.get(item.id)
        if resource is None:
            resource = _request(
                teacher, "POST", "/resources", 201, f"上传 {item.id}",
                data={"course_id": courses[item.course], "title": item.title, "description": item.description},
                files={"file": (item.filename, item.data, item.mime_type)},
            ).json()
        rid = resource["id"]
        if resource["review_status"] == "draft":
            resource = _request(teacher, "POST", f"/resources/{rid}/submit", 200, f"送审 {item.id}").json()
        if resource["review_status"] == "pending":
            resource = _request(
                admin, "POST", f"/admin/resources/{rid}/review", 200, f"审核 {item.id}", json={"action": "approve"},
            ).json()
        if resource["review_status"] != "published":
            raise ImportFailure(f"{item.id} 的发布状态异常。")
        mapping[item.id] = rid
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="独立实验后端的本机地址，不含 /api/v1")
    parser.add_argument("--origin", default="http://localhost:5173", help="实验后端允许的访问来源")
    parser.add_argument("--accounts-file", required=True, type=Path, help="实验库演示账号文件")
    parser.add_argument("--manifest", default=MATERIAL_MANIFEST, type=Path, help="正式资料清单路径")
    parser.add_argument("--out", required=True, type=Path, help="资源编号映射输出路径")
    args = parser.parse_args()
    endpoint = urlsplit(args.base_url)
    if (
        endpoint.scheme not in {"http", "https"}
        or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}
        or endpoint.path not in {"", "/"}
        or endpoint.username is not None or endpoint.password is not None
        or endpoint.query or endpoint.fragment
    ):
        parser.error("--base-url 必须是本机实验服务根地址。")

    client_options = {"base_url": args.base_url, "headers": {"Origin": args.origin}, "timeout": 60,
                      "follow_redirects": False, "trust_env": False}
    try:
        materials = load_materials(args.manifest)
        credentials = _credentials(args.accounts_file)
        with httpx.Client(**client_options) as teacher, httpx.Client(**client_options) as admin:
            identities = {}
            for role, client in (("teacher", teacher), ("admin", admin)):
                username, password = credentials[role]
                identity = _request(client, "POST", "/auth/login", 200, f"登录 {role}", json={
                    "username": username, "password": password,
                }).json()
                if identity["role"] != role or identity["username"] != username:
                    raise ImportFailure(f"{role} 登录身份与实验账号文件不一致。")
                identities[role] = identity["id"]
            mapping = import_materials(teacher, admin, materials, identities["teacher"])
        args.out.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.out.with_suffix(args.out.suffix + ".tmp")
        temporary.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(args.out)
    except ImportFailure as error:
        parser.exit(1, f"{error}\n")
    except (OSError, KeyError, ValueError, TypeError):
        parser.exit(1, "无法读取清单、账号或接口响应，或无法写出编号映射。\n")
    print(f"已确认发布 {len(mapping)} 份实验资料，编号映射已写入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
