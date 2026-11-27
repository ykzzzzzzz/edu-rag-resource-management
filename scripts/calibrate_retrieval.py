"""Calibrate the offline retrieval gate against the M5 validation set."""

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

from app.db import make_engine
from app.embeddings import (
    EmbeddingModelError,
    QueryEmbedder,
    chunk_config_id,
    embedding_model_id,
    load_sentence_transformer,
)
from app.models import Course, Resource, ResourceChunk
from app.qa_service import retrieve
from scripts.setup_experiment import APP_PASSWORD, LOCAL, MODEL_CACHE, _settings

VALIDATION = ROOT / "evaluation" / "validation.jsonl"
RESOURCE_MAP = LOCAL / "resource_map.json"
OUTPUT = ROOT / "evaluation" / "results" / "retrieval_calibration.json"
TOP_K = (3, 5, 8)
THRESHOLDS = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)
SELECTION_RULE = (
    "Maximize the mean of gated Hit@K and unanswerable evidence refusal rate. "
    "Break ties by higher gated Hit@K, higher gated MRR, smaller K, then lower threshold."
)


def load_validation(data):
    questions = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    answerable = sum(q["answerable"] is True for q in questions)
    unanswerable = sum(q["answerable"] is False for q in questions)
    ids = {q["question_id"] for q in questions if q["question_id"].startswith("VAL-")}
    if len(questions) != 24 or len(ids) != 24 or (answerable, unanswerable) != (18, 6):
        raise ValueError("验证集必须含 24 道唯一的 VAL 题，其中 18 道可答、6 道无答案")
    for q in questions:
        if bool(q["gold_sources"]) != q["answerable"]:
            raise ValueError(f"{q['question_id']} 的答案类型与金标准来源不一致")
    return questions


def locations_overlap(first, second):
    return (
        first["type"] == second["type"]
        and max(first["start"], second["start"]) <= min(first["end"], second["end"])
    )


def index_inventory(db, settings, resource_map, questions):
    stmt = (
        select(ResourceChunk.resource_id, Course.id, Course.name, ResourceChunk.locator)
        .join(Resource, Resource.id == ResourceChunk.resource_id)
        .join(Course, Course.id == Resource.course_id)
        .where(
            Resource.review_status == "published",
            Resource.index_status == "ready",
            ResourceChunk.embedding_model == embedding_model_id(settings),
            ResourceChunk.chunk_config == chunk_config_id(settings),
        )
    )
    rows = db.execute(stmt).all()
    locations = {}
    courses = {}
    for resource_id, course_id, course_name, locator in rows:
        locations.setdefault((course_name, resource_id), []).append(locator)
        courses[course_name] = course_id
    if len(set(resource_map.values())) != 24 or set(resource_map.values()) != {row[0] for row in rows}:
        raise ValueError("当前索引的可检索资料与 24 份实验资料映射不一致")
    for q in questions:
        if q["course"] not in courses:
            raise ValueError(f"{q['question_id']} 对应课程没有实验索引")
        for source in q["gold_sources"]:
            key = (q["course"], resource_map[source["doc_id"]])
            if not any(locations_overlap(loc, source["locator"]) for loc in locations.get(key, ())):
                raise ValueError(f"{q['question_id']} 的金标准位置不在当前实验索引")
    return courses, len(rows)


def record_hits(q, hits, doc_ids):
    return {
        "question_id": q["question_id"],
        "course": q["course"],
        "answerable": q["answerable"],
        "gold_sources": q["gold_sources"],
        "hits": [
            {
                "rank": hit.rank,
                "chunk_id": str(hit.chunk_id),
                "doc_id": doc_ids[hit.resource_id],
                "locator": hit.locator,
                "similarity": hit.similarity,
                "gold_match": any(
                    source["doc_id"] == doc_ids[hit.resource_id]
                    and locations_overlap(hit.locator, source["locator"])
                    for source in q["gold_sources"]
                ),
            }
            for hit in hits
        ],
    }


def reciprocal_rank(hits):
    return next((1 / hit["rank"] for hit in hits if hit["gold_match"]), 0.0)


def measure(records, top_k, min_similarity):
    answerable = unanswerable = raw_matches = matches = refused = false_refusals = 0
    raw_rr = rr = 0.0
    for row in records:
        hits = row["hits"][:top_k]
        qualified = [hit for hit in hits if hit["similarity"] >= min_similarity]
        if row["answerable"]:
            answerable += 1
            raw_rank = reciprocal_rank(hits)
            rank = reciprocal_rank(qualified)
            raw_matches += bool(raw_rank)
            matches += bool(rank)
            raw_rr += raw_rank
            rr += rank
            false_refusals += not qualified
        else:
            unanswerable += 1
            refused += not qualified

    hit_rate = matches / answerable
    refusal_rate = refused / unanswerable
    return {
        "top_k": top_k,
        "min_similarity": min_similarity,
        "answerable": answerable,
        "unanswerable": unanswerable,
        "raw_hit_count": raw_matches,
        "raw_hit_at_k": raw_matches / answerable,
        "raw_mrr": raw_rr / answerable,
        "hit_count": matches,
        "hit_at_k": hit_rate,
        "mrr": rr / answerable,
        "unanswerable_evidence_refusal_count": refused,
        "unanswerable_evidence_refusal_rate": refusal_rate,
        "false_evidence_refusal_count": false_refusals,
        "false_evidence_refusal_rate": false_refusals / answerable,
        "selection_score": (matches * unanswerable + refused * answerable) / (2 * answerable * unanswerable),
    }


def selection_key(result):
    return (
        result["selection_score"],
        result["hit_at_k"],
        result["mrr"],
        -result["top_k"],
        -result["min_similarity"],
    )


def calibrate(cache):
    data = VALIDATION.read_bytes().replace(b"\r\n", b"\n")
    questions = load_validation(data)
    resource_map_data = RESOURCE_MAP.read_bytes().replace(b"\r\n", b"\n")
    resource_map = {doc_id: uuid.UUID(rid) for doc_id, rid in json.loads(resource_map_data).items()}
    settings = _settings(APP_PASSWORD.read_text(encoding="utf-8").strip(), cache)
    settings = settings.model_copy(update={"retrieval_top_k": max(TOP_K)})
    doc_ids = {rid: doc_id for doc_id, rid in resource_map.items()}
    records = []
    engine = make_engine(settings.database_url)
    try:
        with Session(engine) as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            courses, chunk_count = index_inventory(db, settings, resource_map, questions)
            embedder = QueryEmbedder(load_sentence_transformer(settings), settings.embedding_query_instruction)
            for q in questions:
                hits = retrieve(db, settings, embedder.embed(q["question"]), courses[q["course"]])
                records.append(record_hits(q, hits, doc_ids))
    finally:
        engine.dispose()

    comparisons = [measure(records, k, threshold) for k in TOP_K for threshold in THRESHOLDS]
    return {
        "dataset": VALIDATION.relative_to(ROOT).as_posix(),
        "dataset_sha256": hashlib.sha256(data).hexdigest(),
        "resource_map_sha256": hashlib.sha256(resource_map_data).hexdigest(),
        "resource_count": len(resource_map),
        "chunk_count": chunk_count,
        "embedding_model": embedding_model_id(settings),
        "embedding_query_instruction": settings.embedding_query_instruction,
        "chunk_config": chunk_config_id(settings),
        "selection_rule": SELECTION_RULE,
        "selected": max(comparisons, key=selection_key),
        "comparisons": comparisons,
        "questions": records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hf-home", type=Path, default=MODEL_CACHE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    try:
        result = calibrate(args.hf_home)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(result, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
    except SQLAlchemyError as exc:
        print(f"读取实验索引失败（{type(exc).__name__}）", file=sys.stderr)
        return 1
    except (EmbeddingModelError, OSError, ValueError, KeyError) as exc:
        print(f"校准失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result["selected"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
