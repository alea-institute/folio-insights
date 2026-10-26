"""Authored, append-only annotations and evaluator-safe tuning exports (U3)."""
from __future__ import annotations

import asyncio
import json
import sqlite3

import aiosqlite
import pytest
from pydantic import ValidationError

from folio_insights.measurement.annotations import (
    AnchorVerificationInput,
    AnnotationAuthor,
    AnnotationInput,
    AnnotationStore,
)
from folio_insights.persistence.review_db import SCHEMA_SQL, ensure_annotation_schema

JUDGE = AnnotationAuthor(kind="judge", identity="codex:model-test")
HUMAN = AnnotationAuthor(kind="human", identity="lawyer-alice")
DAMIEN = AnnotationAuthor(kind="human", identity="damien")


def annotation(key="verdict-1", **changes):
    return AnnotationInput.model_validate({
        "idempotency_key": key,
        "source_id": "source-1",
        "source_sha256": "a" * 64,
        "genre": "opinions",
        "run_id": "run-1",
        "item_id": "prop-1",
        "tag_id": "concept-1",
        "partition": "tuning",
        "action": "judge-verdict",
        "verdict": "wrong",
        "reason": "The source does not support this tag.",
        **changes,
    })


def assert_append_only(path, table):
    with sqlite3.connect(path) as db:
        assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0
        for operation in (f"UPDATE {table} SET reason='changed'", f"DELETE FROM {table}"):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                db.execute(operation)


async def test_populated_legacy_database_is_migrated_additively(tmp_path):
    path = tmp_path / "review.db"
    with sqlite3.connect(path) as db:
        # These are deliberately old schemas, without the new tables or signature columns.
        db.executescript(
            "CREATE TABLE task_decisions (id INTEGER PRIMARY KEY, task_id TEXT, "
            "label TEXT, status TEXT, reviewer_note TEXT);"
            "CREATE TABLE proposed_class_decisions (id INTEGER PRIMARY KEY, "
            "concept_label TEXT, status TEXT, reviewer_note TEXT);"
            "INSERT INTO task_decisions VALUES (7, 'task-1', 'Reviewed', 'approved', 'keep');"
            "INSERT INTO proposed_class_decisions VALUES (9, 'Proposal', 'rejected', 'original');"
        )
        before = list(db.iterdump())
    store = AnnotationStore(path)
    assert await store.history() == []
    with sqlite3.connect(path) as db:
        assert list(db.iterdump()) == before  # A history read does not migrate.
    saved = await store.append(annotation(), author=JUDGE)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM task_decisions").fetchall() == [
            (7, "task-1", "Reviewed", "approved", "keep")]
        assert db.execute("SELECT * FROM proposed_class_decisions").fetchall() == [
            (9, "Proposal", "rejected", "original")]
        assert db.execute("SELECT annotation_id FROM annotations").fetchone() == (
            saved.annotation_id,)
        assert db.execute("SELECT type FROM sqlite_master WHERE name='tag_verdicts'").fetchone() == (
            "view",)


async def test_superseding_correction_and_retry_preserve_history(tmp_path):
    path = tmp_path / "review.db"
    store = AnnotationStore(path)
    original = await store.append(annotation(), author=JUDGE)
    correction_input = annotation(
        "human-1", action="correction", verdict="correct", reason="The duty applies here.",
        supersedes_annotation_id=original.annotation_id)
    correction = await store.append(correction_input, author=HUMAN)
    assert await store.append(correction_input, author=HUMAN) == correction
    reopened = AnnotationStore(path)
    assert await reopened.history(run_id="run-1", item_id="prop-1") == [original, correction]
    assert original.author_kind == "judge" and original.author_identity == JUDGE.identity
    assert original.verdict == "wrong" and original.reason == annotation().reason
    assert correction.author_identity == HUMAN.identity and correction.verdict == "correct"
    assert correction.supersedes_annotation_id == original.annotation_id
    assert original.created_at and correction.created_at
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT verdict, author_identity FROM tag_verdicts").fetchall() == [
            ("correct", HUMAN.identity)]
        with pytest.raises(sqlite3.OperationalError):
            db.execute("INSERT INTO tag_verdicts (verdict) VALUES ('wrong')")
    assert_append_only(path, "annotations")


async def test_concurrent_retries_and_migrations_are_idempotent(tmp_path):
    path = tmp_path / "review.db"
    async with aiosqlite.connect(path) as first, aiosqlite.connect(path) as second:
        await asyncio.gather(ensure_annotation_schema(first), ensure_annotation_schema(second))
        assert not first.in_transaction and not second.in_transaction
    left, right = await asyncio.gather(
        AnnotationStore(path).append(annotation(), author=JUDGE),
        AnnotationStore(path).append(annotation(), author=JUDGE))
    assert left == right
    assert await AnnotationStore(path).history() == [left]


async def test_idempotency_key_cannot_hide_changed_reason_or_author(tmp_path):
    store = AnnotationStore(tmp_path / "review.db")
    original = await store.append(annotation(), author=JUDGE)
    with pytest.raises(ValueError, match="idempotency"):
        await store.append(annotation(reason="Changed"), author=JUDGE)
    with pytest.raises(ValueError, match="idempotency"):
        await store.append(annotation(), author=HUMAN)
    assert await store.history() == [original]


async def test_correction_must_reference_same_target_and_current_history(tmp_path):
    store = AnnotationStore(tmp_path / "review.db")
    original = await store.append(annotation(), author=JUDGE)
    for changes in ({"item_id": "other"}, {"tag_id": "other"},
                    {"source_sha256": "b" * 64}, {"run_id": "other"},
                    {"partition": "held-out", "split_id": "secret"}):
        with pytest.raises(ValueError, match="target"):
            await store.append(annotation("bad", supersedes_annotation_id=original.annotation_id,
                                          **changes), author=HUMAN)
    with pytest.raises(ValueError, match="superseded"):
        await store.append(annotation("bad", supersedes_annotation_id="missing"), author=HUMAN)
    await store.append(annotation("correction", supersedes_annotation_id=original.annotation_id),
                       author=HUMAN)
    with pytest.raises(ValueError, match="superseded"):
        await store.append(annotation("fork", supersedes_annotation_id=original.annotation_id),
                           author=HUMAN)


async def test_tuning_export_excludes_active_held_out_and_releases_retired_split(tmp_path):
    store = AnnotationStore(tmp_path / "review.db")
    tuning = await store.append(annotation(), author=JUDGE)
    held_out = await store.append(annotation(
        "held", item_id="secret-item", partition="held-out", split_id="split-1",
        reason="SECRET RATIONALE"), author=JUDGE)
    await store.append(annotation("active", partition="held-out", split_id="split-2",
                                  reason="STILL SECRET"), author=JUDGE)
    await store.append(annotation("candidate", partition="evaluation-candidate", split_id="future",
                                  reason="NOT TUNING"), author=JUDGE)
    exported = await store.export_tuning()
    assert [entry.annotation for entry in exported] == [tuning]
    assert "SECRET" not in json.dumps([entry.model_dump(mode="json") for entry in exported])
    with pytest.raises(PermissionError):
        await store.retire_split("split-1", author=JUDGE, reason="exposed")
    retirement = await store.retire_split("split-1", author=HUMAN, reason="Operator exposed split")
    assert await store.retire_split("split-1", author=HUMAN,
                                    reason="Operator exposed split") == retirement
    exported = await AnnotationStore(store.db_path).export_tuning()
    assert [entry.annotation for entry in exported] == [tuning, held_out]
    assert exported[-1].partition == "retired"
    assert exported[-1].retirement == retirement
    assert retirement.author_identity == HUMAN.identity
    assert_append_only(store.db_path, "annotation_split_retirements")
    assert "STILL SECRET" not in json.dumps([entry.model_dump(mode="json") for entry in exported])
    assert (await store.history(item_id="secret-item"))[0].partition == "held-out"


async def test_retired_input_requires_recorded_retirement(tmp_path):
    store = AnnotationStore(tmp_path / "review.db")
    with pytest.raises(ValueError, match="retirement"):
        await store.append(annotation(partition="retired", split_id="old"), author=HUMAN)
    await store.retire_split("old", author=HUMAN, reason="Old split exposed")
    saved = await store.append(annotation(partition="retired", split_id="old"), author=HUMAN)
    assert (await store.export_tuning())[0].annotation == saved


async def test_anchor_verification_requires_damien_and_retains_provenance(tmp_path):
    store = AnnotationStore(tmp_path / "review.db")
    saved = await store.append(annotation(), author=JUDGE)
    request = AnchorVerificationInput(
        idempotency_key="anchor-1", genre="opinions", anchor_set_id="anchor-opinions-v1",
        anchor_sha256="c" * 64, gold_revision="gold-v1",
        annotation_ids=(saved.annotation_id,), reason="Checked against the source.")
    assert await store.anchor_history() == []
    for author in (JUDGE, HUMAN, AnnotationAuthor(kind="judge", identity="damien")):
        with pytest.raises(PermissionError, match="Damien"):
            await store.verify_anchor(request, author=author)
    verified = await store.verify_anchor(request, author=DAMIEN)
    assert await store.verify_anchor(request, author=DAMIEN) == verified
    assert verified.author_identity == "damien" and verified.author_kind == "human"
    assert verified.annotation_ids == (saved.annotation_id,)
    assert verified.gold_revision == "gold-v1" and verified.anchor_sha256 == "c" * 64
    assert await AnnotationStore(store.db_path).anchor_history(genre="opinions") == [verified]
    assert await store.anchor_history(genre="briefs") == []
    assert_append_only(store.db_path, "anchor_verifications")
    with pytest.raises(ValueError, match="idempotency"):
        await store.verify_anchor(request.model_copy(update={"reason": "Changed"}), author=DAMIEN)


async def test_anchor_references_existing_annotations_of_its_genre(tmp_path):
    store = AnnotationStore(tmp_path / "review.db")
    saved = await store.append(annotation(), author=JUDGE)
    for ids, genre in ((("missing",), "opinions"), ((saved.annotation_id,), "briefs")):
        request = AnchorVerificationInput(
            idempotency_key="bad", genre=genre, anchor_set_id="anchor", anchor_sha256="c" * 64,
            gold_revision="v1", annotation_ids=ids, reason="Checked")
        with pytest.raises(ValueError, match="annotation"):
            await store.verify_anchor(request, author=DAMIEN)
    assert await store.anchor_history() == []


@pytest.mark.parametrize("action", ["promote", "confirm-drop", "highlight-add",
                                       "confirm-tag", "reject-tag", "add-tag", "adjudicate"])
async def test_reviewer_actions_use_shared_store(tmp_path, action):
    store = AnnotationStore(tmp_path / "review.db")
    saved = await store.append(annotation(action=action, span_start=2, span_end=9), author=HUMAN)
    assert (await store.history(source_id="source-1")) == [saved]
    assert saved.action == action and (saved.span_start, saved.span_end) == (2, 9)


async def test_legacy_weak_is_explicitly_uncertain(tmp_path):
    store = AnnotationStore(tmp_path / "review.db")
    saved = await store.append(annotation(verdict="weak"), author=HUMAN)
    assert saved.verdict == "uncertain"
    with sqlite3.connect(store.db_path) as db:
        assert db.execute("SELECT verdict FROM tag_verdicts").fetchone() == ("uncertain",)


@pytest.mark.parametrize("changes", [
    {"partition": "held-out"}, {"partition": "retired"}, {"reason": " "},
    {"source_sha256": "invalid"}, {"span_start": 3}, {"span_start": 3, "span_end": 2},
    {"span_start": -1, "span_end": 2}, {"verdict": "maybe"}, {"author_identity": "spoof"},
    {"damien_verified": True}, {"quote": "duplicate source"},
])
def test_annotation_contract_rejects_invalid_or_caller_authored_provenance(changes):
    with pytest.raises(ValidationError):
        annotation(**changes)


async def test_missing_database_reads_do_not_create_it(tmp_path):
    path = tmp_path / "missing" / "review.db"
    store = AnnotationStore(path)
    assert await store.history() == []
    assert await store.export_tuning() == []
    assert await store.anchor_history() == []
    assert not path.exists()


async def test_new_review_schema_contains_annotation_view(tmp_path):
    async with aiosqlite.connect(tmp_path / "review.db") as db:
        await db.executescript(SCHEMA_SQL)
        cursor = await db.execute("SELECT * FROM tag_verdicts")
        assert await cursor.fetchall() == []
