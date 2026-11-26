"""Claim and index published resources. Run separately from the web API."""

import argparse
import logging
import multiprocessing
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.db import make_engine
from app.embeddings import EmbeddingModelError, chunk_config_id, embedding_model_id, load_sentence_transformer
from app.index_documents import Fragment, IndexingError, split_document
from app.models import Resource, ResourceChunk
from app.uploads import stored_path

log = logging.getLogger(__name__)
TIMEOUT_REASON = "索引任务超时，请重试"


@dataclass(frozen=True)
class Attempt:
    resource_id: uuid.UUID
    token: uuid.UUID
    lease_until: datetime
    storage_key: str
    mime_type: str


def _clear_attempt(resource: Resource, status: str, error: str | None = None) -> None:
    resource.index_status = status
    resource.index_error = error
    resource.index_attempt_id = None
    resource.index_lease_until = None


def claim(session_factory, timeout: float) -> Attempt | None:
    with session_factory.begin() as db:
        now = db.scalar(select(func.clock_timestamp()))
        db.execute(
            update(Resource)
            .where(
                Resource.review_status == "published",
                Resource.index_status == "processing",
                Resource.index_lease_until <= now,
            )
            .values(index_status="failed", index_error=TIMEOUT_REASON, index_attempt_id=None, index_lease_until=None)
        )
        resource = db.scalar(
            select(Resource)
            .where(Resource.review_status == "published", Resource.index_status == "queued")
            .order_by(Resource.published_at, Resource.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if resource is None:
            return None
        resource.index_status = "processing"
        resource.index_error = None
        resource.index_attempt_id = uuid.uuid4()
        resource.index_lease_until = db.scalar(select(func.clock_timestamp())) + timedelta(seconds=timeout)
        return Attempt(resource.id, resource.index_attempt_id, resource.index_lease_until, resource.storage_key, resource.mime_type)


def finish(session_factory, settings, attempt: Attempt, records, error: str | None = None) -> bool:
    with session_factory.begin() as db:
        resource = db.scalar(select(Resource).where(Resource.id == attempt.resource_id).with_for_update())
        if (
            resource is None
            or resource.review_status != "published"
            or resource.index_status != "processing"
            or resource.index_attempt_id != attempt.token
        ):
            return False
        if db.scalar(select(func.clock_timestamp())) >= attempt.lease_until:
            error = TIMEOUT_REASON
        if error is not None:
            _clear_attempt(resource, "failed", error)
            return False

        model = embedding_model_id(settings)
        config = chunk_config_id(settings)
        db.execute(delete(ResourceChunk).where(
            ResourceChunk.resource_id == resource.id,
            ResourceChunk.embedding_model == model,
            ResourceChunk.chunk_config == config,
        ))
        db.add_all([
            ResourceChunk(resource_id=resource.id, chunk_index=i, content=chunk.content, locator=chunk.locator,
                          embedding=vector, embedding_model=model, chunk_config=config)
            for i, (chunk, vector) in enumerate(records)
        ])
        db.flush()
        if db.scalar(select(func.clock_timestamp())) >= attempt.lease_until:
            # Roll back the replacement if writing it exhausted the lease.
            raise IndexingError(TIMEOUT_REASON)
        _clear_attempt(resource, "ready")
        return True


def _model(settings):
    try:
        return load_sentence_transformer(settings)
    except EmbeddingModelError as exc:
        raise IndexingError(str(exc)) from None


def _process_documents(connection, options):
    import numpy as np

    settings = Settings.model_construct(**options)
    model = None
    with connection:
        while True:
            try:
                path, mime_type = connection.recv()
            except EOFError:
                return
            try:
                if model is None:
                    model = _model(settings)
                fragments = split_document(path, mime_type, settings, model.tokenizer, model.max_seq_length)
                embeddings = model.encode([chunk.content for chunk in fragments], normalize_embeddings=True,
                                          batch_size=16, show_progress_bar=False)
                if embeddings.shape != (len(fragments), 512) or not np.isfinite(embeddings).all():
                    raise IndexingError("嵌入模型返回了无效向量")
            except IndexingError as exc:
                connection.send((str(exc), [], None))
            except Exception as exc:
                log.warning("文档处理失败 (%s)", type(exc).__name__)
                connection.send(("文档处理失败，请检查原件后重试", [], None))
            else:
                connection.send((None, fragments, embeddings))


class DocumentProcessor:
    """Keep one model warm in a child process that can be stopped on timeout."""

    def __init__(self, settings: Settings):
        self.options = settings.model_dump(exclude={"database_url", "llm_api_key"})
        self.context = multiprocessing.get_context("spawn")
        self.connection = None
        self.process = None

    def run(self, path, mime_type, timeout):
        started = time.monotonic()
        try:
            if self.process is None:
                self.connection, child = self.context.Pipe()
                self.process = self.context.Process(target=_process_documents, args=(child, self.options), daemon=True)
                try:
                    self.process.start()
                finally:
                    child.close()
            self.connection.send((path, mime_type))
            if not self.connection.poll(max(0, timeout - (time.monotonic() - started))):
                raise IndexingError(TIMEOUT_REASON)
            error, fragments, embeddings = self.connection.recv()
        except IndexingError:
            self.close()
            raise
        except (EOFError, OSError):
            self.close()
            raise IndexingError("文档处理进程退出，请重试") from None
        if error:
            raise IndexingError(error)
        return list(zip(fragments, embeddings, strict=True))

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        if self.process is not None:
            if self.process.pid is not None:
                if self.process.is_alive():
                    self.process.terminate()
                self.process.join(timeout=2)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join()
            self.process.close()
            self.process = None


def run_once(session_factory, settings: Settings, processor: DocumentProcessor) -> bool:
    started = time.monotonic()
    attempt = claim(session_factory, settings.index_timeout_seconds)
    if attempt is None:
        return False
    try:
        remaining = settings.index_timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            raise IndexingError(TIMEOUT_REASON)
        path = stored_path(settings.resource_storage_dir, attempt.storage_key)
        records: list[tuple[Fragment, list[float]]] = processor.run(path, attempt.mime_type, remaining)
        if not records:
            raise IndexingError("未提取到可用文本")
        if finish(session_factory, settings, attempt, records):
            log.info("资源 %s 索引完成，片段 %d", attempt.resource_id, len(records))
    except IndexingError as exc:
        log.warning("资源 %s 索引失败：%s", attempt.resource_id, exc)
        finish(session_factory, settings, attempt, [], str(exc))
    except SQLAlchemyError as exc:
        log.warning("资源 %s 写入索引失败 (%s)", attempt.resource_id, type(exc).__name__)
        finish(session_factory, settings, attempt, [], "写入索引失败，请重试")
    return True


def main():
    parser = argparse.ArgumentParser(description="处理教学资源索引队列")
    parser.add_argument("--once", action="store_true", help="最多处理一项任务后退出")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    engine = make_engine(settings.database_url)
    factory = sessionmaker(bind=engine)
    processor = DocumentProcessor(settings)
    try:
        while True:
            try:
                busy = run_once(factory, settings, processor)
            except SQLAlchemyError as exc:
                log.error("索引数据库暂不可用 (%s)", type(exc).__name__)
                if args.once:
                    return 1
                busy = False
            if args.once:
                return 0
            if not busy:
                time.sleep(settings.index_poll_seconds)
    except KeyboardInterrupt:
        return 0
    finally:
        processor.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
