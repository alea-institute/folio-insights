"""Append-only measurement/reviewer annotations, separate from proposal approvals.

CLI/API callers supply authenticated authors and source/partition metadata from
their trusted run context, never from a model's or HTTP client's annotation body.
Only the authenticated human identity ``damien`` can verify an anchor. Adapters
must map Damien's authenticated operator identity to that canonical identity;
loopback access alone does not identify him.

History and anchor reads are evaluator operations: they may contain held-out
reasons. Tuning workers receive only export_tuning() results, never this database.
Source support is referenced by snapshot digest and code-point offsets only.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

import aiosqlite
from pydantic import Field, field_validator, model_validator

from folio_insights.measurement.schema import Genre, MeasurementModel, Nonempty, Sha256
from folio_insights.persistence.review_db import apply_schema, ensure_annotation_schema


class AnnotationAuthor(MeasurementModel):
    kind: Literal["judge", "human"]
    identity: Nonempty


class AnnotationInput(MeasurementModel):
    idempotency_key: Nonempty
    source_id: Nonempty
    source_sha256: Sha256
    genre: Genre
    run_id: Nonempty
    item_id: Nonempty
    tag_id: Nonempty | None = None
    partition: Literal["tuning", "evaluation-candidate", "held-out", "retired"]
    split_id: Nonempty | None = None
    action: Literal["judge-verdict", "correction", "adjudicate", "promote", "confirm-drop",
                    "highlight-add", "confirm-tag", "reject-tag", "add-tag"]
    verdict: Literal["correct", "wrong", "uncertain"]
    reason: Nonempty
    supersedes_annotation_id: Nonempty | None = None
    span_start: int | None = Field(default=None, ge=0)
    span_end: int | None = Field(default=None, gt=0)

    @field_validator("verdict", mode="before")
    @classmethod
    def legacy_weak(cls, value):
        return "uncertain" if value == "weak" else value

    @model_validator(mode="after")
    def check_context(self):
        if self.partition in {"held-out", "retired"} and self.split_id is None:
            raise ValueError("held-out and retired annotations require a split_id")
        if (self.span_start is None) != (self.span_end is None):
            raise ValueError("both span offsets are required")
        if self.span_start is not None and self.span_end <= self.span_start:
            raise ValueError("span end must follow start")
        return self


class Annotation(AnnotationInput):
    annotation_id: Nonempty
    author_kind: Literal["judge", "human"]
    author_identity: Nonempty
    created_at: Nonempty


class SplitRetirement(MeasurementModel):
    split_id: Nonempty
    author_kind: Literal["human"]
    author_identity: Nonempty
    reason: Nonempty
    created_at: Nonempty


class TuningAnnotation(MeasurementModel):
    annotation: Annotation
    partition: Literal["tuning", "retired"]
    retirement: SplitRetirement | None = None


class AnchorVerificationInput(MeasurementModel):
    idempotency_key: Nonempty
    genre: Genre
    anchor_set_id: Nonempty
    anchor_sha256: Sha256
    gold_revision: Nonempty
    annotation_ids: tuple[Nonempty, ...] = Field(min_length=1)
    reason: Nonempty


class AnchorVerification(AnchorVerificationInput):
    verification_id: Nonempty
    author_kind: Literal["human"]
    author_identity: Literal["damien"]
    created_at: Nonempty


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _anchor(row) -> AnchorVerification:
    values = dict(row)
    values["annotation_ids"] = json.loads(values["annotation_ids"])
    return AnchorVerification.model_validate(values)


async def _insert(db, table: str, values: dict) -> None:
    # Table and column names come only from this module's fixed models.
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    await db.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                     tuple(values.values()))


def _check_retry(existing, requested: dict, generated: set[str]) -> None:
    actual = existing.model_dump(mode="json", exclude=generated)
    if actual != requested:
        raise ValueError("idempotency key already identifies a different annotation operation")


class AnnotationStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    @asynccontextmanager
    async def _write(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not self.db_path.exists()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if new_file:
                await apply_schema(db, new_file=True)
            await ensure_annotation_schema(db)
            await db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    @asynccontextmanager
    async def _read(self):
        if not self.db_path.is_file():
            yield None
            return
        async with aiosqlite.connect(
            f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True
        ) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='annotations'")
            yield db if await cursor.fetchone() else None

    async def append(self, request: AnnotationInput, *, author: AnnotationAuthor) -> Annotation:
        values = {**request.model_dump(mode="json"), "author_kind": author.kind,
                  "author_identity": author.identity}
        async with self._write() as db:
            cursor = await db.execute("SELECT * FROM annotations WHERE idempotency_key=?",
                                      (request.idempotency_key,))
            if row := await cursor.fetchone():
                existing = Annotation.model_validate(dict(row))
                _check_retry(existing, values, {"annotation_id", "created_at"})
                return existing
            if request.partition == "retired":
                cursor = await db.execute(
                    "SELECT 1 FROM annotation_split_retirements WHERE split_id=?",
                    (request.split_id,))
                if not await cursor.fetchone():
                    raise ValueError("retired annotation requires a recorded split retirement")
            if request.supersedes_annotation_id:
                cursor = await db.execute("SELECT * FROM annotations WHERE annotation_id=?",
                                          (request.supersedes_annotation_id,))
                previous = await cursor.fetchone()
                if previous is None:
                    raise ValueError("superseded annotation does not exist")
                target = ("source_id", "source_sha256", "genre", "run_id", "item_id", "tag_id",
                          "partition", "split_id")
                if any(previous[key] != values[key] for key in target):
                    raise ValueError("superseding annotation must identify the same target")
                cursor = await db.execute(
                    "SELECT 1 FROM annotations WHERE supersedes_annotation_id=?",
                    (request.supersedes_annotation_id,))
                if await cursor.fetchone():
                    raise ValueError("annotation has already been superseded")
            record = Annotation(**values, annotation_id=uuid4().hex, created_at=_now())
            await _insert(db, "annotations", record.model_dump(mode="json"))
            return record

    async def history(self, *, source_id: str | None = None, run_id: str | None = None,
                      item_id: str | None = None, tag_id: str | None = None) -> list[Annotation]:
        filters = {key: value for key, value in {
            "source_id": source_id, "run_id": run_id, "item_id": item_id, "tag_id": tag_id,
        }.items() if value is not None}
        where = " WHERE " + " AND ".join(f"{key}=?" for key in filters) if filters else ""
        async with self._read() as db:
            if db is None:
                return []
            cursor = await db.execute("SELECT * FROM annotations" + where + " ORDER BY rowid",
                                      tuple(filters.values()))
            return [Annotation.model_validate(dict(row)) for row in await cursor.fetchall()]

    async def retire_split(self, split_id: str, *, author: AnnotationAuthor,
                           reason: str) -> SplitRetirement:
        """Record operator exposure before releasing a split's annotations for tuning.

        The split ID itself is the retry key. U6 must consult this record before
        accepting any future evaluation against that split.
        """
        if author.kind != "human":
            raise PermissionError("only an authenticated human operator may retire a split")
        record = SplitRetirement(split_id=split_id, author_kind=author.kind,
                                 author_identity=author.identity, reason=reason, created_at=_now())
        async with self._write() as db:
            cursor = await db.execute("SELECT * FROM annotation_split_retirements WHERE split_id=?",
                                      (record.split_id,))
            if row := await cursor.fetchone():
                existing = SplitRetirement.model_validate(dict(row))
                _check_retry(existing, record.model_dump(mode="json", exclude={"created_at"}),
                             {"created_at"})
                return existing
            await _insert(db, "annotation_split_retirements", record.model_dump(mode="json"))
            return record

    async def export_tuning(self) -> list[TuningAnnotation]:
        """Filter in SQL: no active held-out reason is loaded into a tuning export."""
        async with self._read() as db:
            if db is None:
                return []
            cursor = await db.execute(
                "SELECT a.* FROM annotations AS a WHERE a.partition='tuning' OR "
                "(a.partition IN ('held-out', 'retired') AND EXISTS ("
                "SELECT 1 FROM annotation_split_retirements AS r WHERE r.split_id=a.split_id)) "
                "ORDER BY a.rowid")
            result = []
            for row in await cursor.fetchall():
                annotation = Annotation.model_validate(dict(row))
                retirement = None
                if annotation.partition != "tuning":
                    cursor = await db.execute(
                        "SELECT * FROM annotation_split_retirements WHERE split_id=?",
                        (annotation.split_id,))
                    retirement = SplitRetirement.model_validate(dict(await cursor.fetchone()))
                result.append(TuningAnnotation(
                    annotation=annotation, partition="retired" if retirement else "tuning",
                    retirement=retirement))
            return result

    async def verify_anchor(self, request: AnchorVerificationInput, *,
                            author: AnnotationAuthor) -> AnchorVerification:
        if author.kind != "human" or author.identity != "damien":
            raise PermissionError("only authenticated Damien may verify a human anchor")
        values = {**request.model_dump(mode="json"), "author_kind": author.kind,
                  "author_identity": author.identity}
        async with self._write() as db:
            cursor = await db.execute("SELECT * FROM anchor_verifications WHERE idempotency_key=?",
                                      (request.idempotency_key,))
            if row := await cursor.fetchone():
                existing = _anchor(row)
                _check_retry(existing, values, {"verification_id", "created_at"})
                return existing
            for annotation_id in request.annotation_ids:
                cursor = await db.execute("SELECT genre FROM annotations WHERE annotation_id=?",
                                          (annotation_id,))
                row = await cursor.fetchone()
                if row is None or row["genre"] != request.genre:
                    raise ValueError("anchor must reference existing annotations of the same genre")
            record = AnchorVerification(**values, verification_id=uuid4().hex, created_at=_now())
            stored = record.model_dump(mode="json")
            stored["annotation_ids"] = json.dumps(stored["annotation_ids"])
            await _insert(db, "anchor_verifications", stored)
            return record

    async def anchor_history(self, *, genre: Genre | None = None) -> list[AnchorVerification]:
        async with self._read() as db:
            if db is None:
                return []
            where = " WHERE genre=?" if genre else ""
            cursor = await db.execute("SELECT * FROM anchor_verifications" + where +
                                      " ORDER BY rowid", (genre,) if genre else ())
            return [_anchor(row) for row in await cursor.fetchall()]
