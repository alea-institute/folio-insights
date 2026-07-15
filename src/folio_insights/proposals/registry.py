"""Proposed-class registry — Stage A (Collect).

Persistent, idempotent store of every ``proposed_class`` the pipeline emits.
Keyed by a content-addressed ``proposal_id`` derived from the normalized label
and a hash of the draft definition, so re-ingesting the same run is a no-op and
a new run appends / merges provenance without duplication.

Pure stdlib. Reads a run's ``proposed_classes.json`` (+ optional
``discovery.json`` for source spans) and upserts entries.
"""
from __future__ import annotations
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_NORM_RE = re.compile(r"[^a-z0-9]+")
_MAX_SUPPORTING = 8  # cap provenance excerpts per entry


def normalize_label(label: str) -> str:
    return _NORM_RE.sub(" ", (label or "").lower()).strip()


def _def_hash(definition: str) -> str:
    return hashlib.sha1((definition or "").encode("utf-8")).hexdigest()[:12]


def proposal_id(normalized: str, definition: str) -> str:
    h = hashlib.sha1(f"{normalized}|{_def_hash(definition)}".encode("utf-8")).hexdigest()
    return "PC-" + h[:12]


def draft_definition_from_spans(label: str, excerpts: list[str]) -> str:
    """Deterministic first-pass definition from supporting source text.

    The LLM-judge (Claude-side, $0) refines this later; kept deterministic here
    so registry state is reproducible and testable.
    """
    ex = next((e.strip() for e in excerpts if e and e.strip()), "")
    if ex:
        ex = re.sub(r"\s+", " ", ex)[:280]
        return f"Proposed class “{label}”. Surfaced from source: “{ex}”"
    return f"Proposed class “{label}” (no supporting excerpt captured)."


@dataclass
class ProposalRegistry:
    path: Path
    entries: dict[str, dict] = field(default_factory=dict)
    _norm_index: dict[str, str] = field(default_factory=dict)  # normalized_label -> proposal_id

    # ---- load / save -------------------------------------------------
    @classmethod
    def load(cls, path: str | Path) -> "ProposalRegistry":
        p = Path(path)
        reg = cls(path=p)
        if p.exists():
            data = json.loads(p.read_text())
            reg.entries = {e["proposal_id"]: e for e in data.get("proposals", [])}
            for e in reg.entries.values():  # backfill ledger for older registries
                e.setdefault("run_occurrences", {e.get("first_seen_run", "unknown"):
                                                 e.get("occurrences", 0)})
            reg._reindex()
        return reg

    def _reindex(self) -> None:
        self._norm_index = {e["normalized_label"]: pid for pid, e in self.entries.items()}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "proposed-class-registry/v1",
            "total_proposals": len(self.entries),
            "proposals": [self.entries[k] for k in sorted(self.entries)],
        }
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    # ---- ingest ------------------------------------------------------
    def ingest_run(
        self,
        proposed_classes: list[dict[str, Any]],
        *,
        run: str,
        book: str,
        chapter: str,
        spans_by_unit: dict[str, dict] | None = None,
    ) -> dict[str, int]:
        """Idempotent upsert of one run's proposed classes.

        Returns counts {new, updated, occurrences}. Re-running with identical
        inputs leaves the registry byte-identical.
        """
        spans_by_unit = spans_by_unit or {}
        # group this run's raw proposals by normalized label
        grouped: dict[str, list[dict]] = {}
        for pc in proposed_classes:
            grouped.setdefault(normalize_label(pc["proposed_label"]), []).append(pc)

        new = updated = occ = 0
        for norm, group in grouped.items():
            label = group[0]["proposed_label"]
            excerpts = [g.get("source_text", "") for g in group]
            draft = draft_definition_from_spans(label, excerpts)
            pid = self._norm_index.get(norm) or proposal_id(norm, draft)

            supporting_new = []
            for g in group:
                uid = g.get("source_unit_id", "")
                sp = spans_by_unit.get(uid, {})
                supporting_new.append({
                    "unit_id": uid,
                    "chapter": chapter,
                    "book": book,
                    "run": run,
                    "source_span": sp.get("span"),
                    "source_text_excerpt": re.sub(r"\s+", " ", g.get("source_text", ""))[:240],
                })

            if pid in self.entries:
                e = self.entries[pid]
                prev = e["run_occurrences"].get(run)
                # per-run ledger makes re-ingest idempotent regardless of the
                # supporting_units display cap.
                e["run_occurrences"][run] = len(group)
                e["occurrences"] = sum(e["run_occurrences"].values())
                # merge supporting spans (dedupe by unit_id+run), capped for display
                seen = {(s["unit_id"], s["run"]) for s in e["supporting_units"]}
                added = [s for s in supporting_new if (s["unit_id"], s["run"]) not in seen]
                if added:
                    e["supporting_units"] = (e["supporting_units"] + added)[:_MAX_SUPPORTING]
                for key, val in (("books", book), ("chapters", chapter), ("runs", run)):
                    if val not in e["provenance"][key]:
                        e["provenance"][key].append(val)
                if prev is None:  # genuinely new run for this proposal
                    e["last_seen_run"] = run
                    updated += 1
                    occ += len(group)
            else:
                entry = {
                    "proposal_id": pid,
                    "proposed_label": label,
                    "normalized_label": norm,
                    "draft_definition": draft,
                    "definition_hash": _def_hash(draft),
                    "occurrences": len(group),
                    "run_occurrences": {run: len(group)},
                    "supporting_units": supporting_new[:_MAX_SUPPORTING],
                    "provenance": {"books": [book], "chapters": [chapter], "runs": [run]},
                    "first_seen_run": run,
                    "last_seen_run": run,
                    "judge": None,
                    "decision": {"status": "pending", "note": "", "decided_at": None},
                }
                self.entries[pid] = entry
                self._norm_index[norm] = pid
                new += 1
                occ += len(group)
        return {"new": new, "updated": updated, "occurrences": occ}

    # ---- helpers -----------------------------------------------------
    def by_normalized(self, norm: str) -> dict | None:
        pid = self._norm_index.get(norm)
        return self.entries.get(pid) if pid else None

    def all_entries(self) -> list[dict]:
        return [self.entries[k] for k in sorted(self.entries)]


def load_run_proposals(output_dir: str | Path) -> tuple[list[dict], dict[str, dict]]:
    """Read a run's proposed_classes.json + span map from discovery.json."""
    out = Path(output_dir)
    pcs = json.loads((out / "proposed_classes.json").read_text())["proposed_classes"]
    spans: dict[str, dict] = {}
    disc = out / "discovery.json"
    if disc.exists():
        for u in json.loads(disc.read_text()).get("knowledge_units", []):
            sp = u.get("original_span") or {}
            spans[u["id"]] = {"span": [sp.get("start"), sp.get("end")]}
    return pcs, spans
