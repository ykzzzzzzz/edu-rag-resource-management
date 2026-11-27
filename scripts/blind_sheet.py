"""Create blinded M5 scoring sheets and restore judgments after independent scoring.

Input JSONL rows require question_id, group (baseline or rag), mode (cloud),
status (answered or insufficient_evidence), and a nonempty answer. RAG rows
also require citation_numbers, using the QA output's integer [n] convention.
"""

import argparse
import csv
import json
import random
import re
import secrets
import sys
from pathlib import Path

TEST = Path(__file__).resolve().parents[1] / "evaluation" / "test.jsonl"
GROUPS = ("baseline", "rag")
STATUSES = {"answered", "insufficient_evidence"}
FIELDS = ("blind_id", "question_id", "course", "question", "answerable", "gold_answer", "answer", "judgment", "note")
CITATION = re.compile(r"\[(\d+)\]")


def read_jsonl(path):
    records = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        qid = row["question_id"]
        if not isinstance(qid, str) or not qid or qid in records:
            raise ValueError(f"{path.name} 中题号无效或重复：{qid}")
        records[qid] = row
    return records


def make_blind_answer(row, group, qid):
    if row.get("mode") != "cloud" or row.get("group") != group:
        raise ValueError(f"{group} 的 {qid} 组别或云端模式无效")
    if row.get("status") not in STATUSES or any(row.get(k) for k in ("error", "error_code", "transport_error")):
        raise ValueError(f"{group} 的 {qid} 尚无有效运行结果")
    answer = row.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError(f"{group} 的 {qid} 回答为空")
    if group == "rag":
        numbers = row.get("citation_numbers")
        if (
            not isinstance(numbers, list)
            or any(type(n) is not int or n < 1 for n in numbers)
            or bool(numbers) != (row["status"] == "answered")
        ):
            raise ValueError(f"{group} 的 {qid} 引用编号无效")
        citations = set(numbers)
        if not citations.issubset(int(n) for n in CITATION.findall(answer)):
            raise ValueError(f"{group} 的 {qid} 缺少标注的引用编号")
        answer = CITATION.sub(lambda marker: "" if int(marker[1]) in citations else marker[0], answer)
        if not answer.strip():
            raise ValueError(f"{group} 的 {qid} 去除引用后没有回答文本")
    return answer


def spreadsheet_text(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def build_sheet(questions, answers, question_ids, seed, role):
    slots = [(qid, group) for qid in question_ids for group in GROUPS]
    random.Random(f"{seed}:{role}:order").shuffle(slots)
    rows = []
    identities = {}
    for index, (qid, group) in enumerate(slots, 1):
        blind_id = f"{role.upper()}-{index:03}"
        q = questions[qid]
        identities[blind_id] = {"question_id": qid, "group": group}
        rows.append({
            "blind_id": blind_id,
            "question_id": qid,
            "course": q["course"],
            "question": q["question"],
            "answerable": int(q["answerable"]),
            "gold_answer": q["gold_answer"],
            "answer": answers[group][qid],
            "judgment": "",
            "note": "",
        })
    return rows, identities


def create(questions_path, baseline, rag, output, seed):
    if seed is None:
        seed = secrets.randbits(128)
    questions = read_jsonl(questions_path)
    if len(questions) != 60 or sum(q["answerable"] is True for q in questions.values()) != 45 or sum(
        q["answerable"] is False for q in questions.values()
    ) != 15:
        raise ValueError("测试集必须有 45 道可答题与 15 道无答案题")
    question_ids = sorted(questions)
    answers = {}
    for group, path in zip(GROUPS, (baseline, rag), strict=True):
        records = read_jsonl(path)
        if records.keys() != questions.keys():
            missing = sorted(questions.keys() - records.keys())
            extra = sorted(records.keys() - questions.keys())
            raise ValueError(f"{group} 题号与测试集不一致。缺少 {missing}，多出 {extra}")
        answers[group] = {qid: make_blind_answer(records[qid], group, qid) for qid in question_ids}

    second_ids = random.Random(f"{seed}:second:sample").sample(question_ids, 20)
    sheets = {
        "primary": build_sheet(questions, answers, question_ids, seed, "p"),
        "second": build_sheet(questions, answers, second_ids, seed, "s"),
    }
    output.mkdir(parents=True)
    for rater, (rows, _) in sheets.items():
        with (output / f"{rater}.csv").open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows({key: spreadsheet_text(value) for key, value in row.items()} for row in rows)
    mapping = {"seed": seed, **{rater: identities for rater, (_, identities) in sheets.items()}}
    write_json(output / "private_mapping.json", mapping)


def write_json(path, data):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def restore_sheet(path, identities):
    restored = {}
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not {"blind_id", "question_id", "judgment", "note"}.issubset(reader.fieldnames):
            raise ValueError(f"{path.name} 缺少必要评分列")
        for row in reader:
            blind_id = row["blind_id"]
            identity = identities.get(blind_id)
            if blind_id in seen or identity is None or row["question_id"] != identity["question_id"]:
                raise ValueError(f"{path.name} 匿名编号重复、未知或与题号不符：{blind_id}")
            judgment = (row["judgment"] or "").strip()
            if judgment not in {"0", "1"}:
                raise ValueError(f"{path.name} 的 {blind_id} 判定必须为 0 或 1")
            key = (identity["question_id"], identity["group"])
            if key in restored:
                raise ValueError(f"{path.name} 映射含重复题号与组别")
            restored[key] = {**identity, "judgment": int(judgment), "note": row["note"] or ""}
            seen.add(blind_id)
    if seen != identities.keys():
        raise ValueError(f"{path.name} 缺少匿名编号：{sorted(identities.keys() - seen)}")
    return restored


def restore(mapping_path, primary_path, second_path, output):
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    primary = restore_sheet(primary_path, mapping["primary"])
    second = restore_sheet(second_path, mapping["second"])
    for ratings, count in ((primary, 60), (second, 20)):
        ids = {qid for qid, _ in ratings}
        if len(ids) != count or set(ratings) != {(qid, group) for qid in ids for group in GROUPS}:
            raise ValueError("映射必须覆盖每题的两组回答")
    if not second.keys() <= primary.keys():
        raise ValueError("第二评分表含主评分表之外的回答")
    disagreements = [
        {
            "question_id": qid,
            "group": group,
            "primary_judgment": primary[qid, group]["judgment"],
            "second_judgment": second[qid, group]["judgment"],
        }
        for qid, group in sorted(second)
        if primary[qid, group]["judgment"] != second[qid, group]["judgment"]
    ]
    agreed = len(second) - len(disagreements)
    write_json(output, {
        "primary": [primary[key] for key in sorted(primary)],
        "second": [second[key] for key in sorted(second)],
        "agreement": {
            "agreed_count": agreed,
            "total_count": len(second),
            "rate": agreed / len(second),
            "disagreements": disagreements,
        },
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    issue = commands.add_parser("create", help="生成两份匿名评分表与私有映射")
    issue.add_argument("--baseline", type=Path, required=True)
    issue.add_argument("--rag", type=Path, required=True)
    issue.add_argument("--output-dir", type=Path, required=True)
    issue.add_argument("--seed", type=int, help="复用已记录的随机种子；默认生成并保存在私有映射中")
    collect = commands.add_parser("restore", help="还原双人评分并统计一致率")
    collect.add_argument("--mapping", type=Path, required=True)
    collect.add_argument("--primary", type=Path, required=True)
    collect.add_argument("--second", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "create":
            create(TEST, args.baseline, args.rag, args.output_dir, args.seed)
        else:
            restore(args.mapping, args.primary, args.second, args.output)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"盲评处理失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
