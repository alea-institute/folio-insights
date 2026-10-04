"""Nightly TTL dump job (Phase 13 U4; STORAGE-05, exit criterion 4).

``run_ttl_dump(corpus_root, dump_repo)`` writes a Turtle dump of every corpus
under a storage root into a dedicated Git repository and records a local
commit there:

    <dump_repo>/tbox.ttl
    <dump_repo>/corpora/<percent-encoded corpus>/abox.ttl
    <dump_repo>/corpora/<percent-encoded corpus>/governance.ttl
    <dump_repo>/corpora/<percent-encoded corpus>/manifest.json

The files come from the export adapters (``storage.exports``), so they carry
the signed records and are parsed back and compared before the commit; the
output is deterministic (sorted statements, stable blank-node labels, no
timestamps in files), so an unchanged corpus produces no new commit.

Entry points: this function and ``folio-insights storage dump`` (CLI). The
job only commits locally. Scheduling it (a systemd timer, cron, or an Arq job
later) and publishing the repository (any push) are deliberately NOT done
here: they belong to the operator / orchestrator.

The dump repository must be its own Git work tree (its top level), never a
subdirectory of another repository such as this source checkout, and never
inside the storage root or the served output directory.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from pyoxigraph import NamedNode, RdfFormat, Store

from folio_insights.storage.errors import StorageError
from folio_insights.storage.exports import (
    _graph_file,
    _served_output_dir,
    build_export_dataset,
)
from folio_insights.storage.journal import JOURNAL_FILENAME
from folio_insights.storage.projection import TBOX_GRAPH, corpus_graph, governance_graph

DUMP_AUTHOR_NAME = "folio-insights dump job"
DUMP_AUTHOR_EMAIL = "dump-job@folio-insights.invalid"


class DumpError(StorageError):
    """The dump could not be written or committed."""


@dataclass(frozen=True)
class DumpResult:
    repo: Path
    corpora: dict[str, int]  # corpus -> journal head (watermark) dumped
    files: list[str]
    commit: str | None  # None when nothing changed
    changed: bool


def corpus_dirname(corpus: str) -> str:
    return quote(corpus, safe="") or "_"


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise DumpError(f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout.strip()


def _check_repo(repo: Path, corpus_root: Path, *, init: bool) -> None:
    resolved = repo.resolve()
    root = corpus_root.resolve()
    if resolved == root or root in resolved.parents or resolved in root.parents:
        raise DumpError("the dump repository must not overlap the storage root")
    served = _served_output_dir()
    if served is not None and (resolved == served or served in resolved.parents):
        raise DumpError("the dump repository must not be inside the served output directory")
    if not repo.exists():
        if not init:
            raise DumpError(f"dump repository {repo} does not exist (pass init=True)")
        repo.mkdir(parents=True, mode=0o700)
        _git(repo, "init", "--quiet")
        return
    probe = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False,
    )
    if probe.returncode != 0:
        if not init:
            raise DumpError(f"{repo} is not a Git repository (pass init=True)")
        _git(repo, "init", "--quiet")
        return
    if Path(probe.stdout.strip()).resolve() != resolved:
        raise DumpError(
            f"{repo} is inside the Git repository {probe.stdout.strip()}; the dump "
            "repository must be its own work tree"
        )


async def _corpora(corpus_root: Path) -> list[str]:
    import aiosqlite

    journal = corpus_root / JOURNAL_FILENAME
    if not journal.exists():
        raise DumpError(f"no journal at {journal}")
    async with aiosqlite.connect(f"file:{journal}?mode=ro", uri=True) as conn:
        rows = await conn.execute_fetchall("SELECT DISTINCT corpus FROM journal ORDER BY corpus")
    return [str(r[0]) for r in rows]


async def run_ttl_dump(
    corpus_root: str | os.PathLike[str],
    dump_repo: str | os.PathLike[str],
    *,
    corpora: list[str] | None = None,
    init: bool = False,
    author_name: str = DUMP_AUTHOR_NAME,
    author_email: str = DUMP_AUTHOR_EMAIL,
    now: datetime | None = None,
) -> DumpResult:
    """Dump every (or the named) corpus as Turtle and commit locally."""
    from folio_insights.storage.context import CorpusStorageContext, StorageConfig

    root = Path(corpus_root)
    repo = Path(dump_repo)
    _check_repo(repo, root, init=init)
    names = sorted(corpora) if corpora else await _corpora(root)
    known = set(await _corpora(root))
    unknown = [c for c in names if c not in known]
    if unknown:
        raise DumpError(f"no journaled corpus named {unknown}")

    written: list[str] = []
    heads: dict[str, int] = {}
    tbox_written = False
    for corpus in names:
        ctx = await CorpusStorageContext.open(root, corpus, config=StorageConfig(event_verifier=None))
        try:
            dataset = await build_export_dataset(ctx)
        finally:
            await ctx.close()
        rel_dir = f"corpora/{corpus_dirname(corpus)}"
        entries = [
            _graph_file(repo, f"{rel_dir}/abox.ttl", dataset.graph(dataset.abox),
                        corpus_graph(corpus), f"{corpus} abox dump"),
            _graph_file(repo, f"{rel_dir}/governance.ttl", dataset.graph(dataset.governance),
                        governance_graph(corpus), f"{corpus} governance dump"),
        ]
        if not tbox_written:
            entries.append(
                _graph_file(repo, "tbox.ttl", dataset.graph(TBOX_GRAPH), TBOX_GRAPH, "tbox dump")
            )
            tbox_written = True
        manifest = {
            "corpus": corpus,
            "journal_head": dataset.watermark,
            "watermark_payload_sha256": dataset.watermark_payload_sha256,
            "files": [e for e in entries if e["path"].startswith(rel_dir)],
            "full_shacl": "deferred-to-phase-11",
        }
        manifest_path = repo / rel_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        written.extend(e["path"] for e in entries)
        written.append(manifest_path.relative_to(repo).as_posix())
        heads[corpus] = dataset.watermark

    _git(repo, "add", "--", *written)
    staged = subprocess.run(
        ["git", "-C", str(repo), "diff", "--cached", "--quiet"], check=False
    ).returncode
    if staged == 0:
        return DumpResult(repo=repo, corpora=heads, files=written, commit=None, changed=False)
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = "\n".join(f"{c}: journal head {h}" for c, h in heads.items())
    env = dict(os.environ)
    env.update(
        GIT_AUTHOR_NAME=author_name,
        GIT_AUTHOR_EMAIL=author_email,
        GIT_COMMITTER_NAME=author_name,
        GIT_COMMITTER_EMAIL=author_email,
    )
    _git(repo, "commit", "--quiet", "-m", f"dump: {len(heads)} corpora at {stamp}", "-m", body,
         env=env)
    commit = _git(repo, "rev-parse", "HEAD")
    return DumpResult(repo=repo, corpora=heads, files=written, commit=commit, changed=True)


def restore_ttl_dump(
    dump_dir: str | os.PathLike[str], destination: str | os.PathLike[str]
) -> dict[str, int]:
    """Load a TTL dump into a NEW pyoxigraph store at ``destination``.

    Each file goes into the named graph its manifest records (the TBox into
    the TBox graph), so the restored store answers the same ``GRAPH`` queries
    as the projection did at the dumped watermark. This restores the RDF
    view only; the authoritative journal is restored from a snapshot
    (``storage.backup``). Returns statements loaded per graph.
    """
    src = Path(dump_dir)
    dest = Path(destination)
    if dest.exists():
        raise DumpError(f"restore destination {dest} already exists; use a new path")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}.restoring-{uuid.uuid4().hex}"
    loaded: dict[str, int] = {}
    try:
        store = Store(str(tmp))
        try:
            tbox = src / "tbox.ttl"
            if tbox.exists():
                store.load(path=str(tbox), format=RdfFormat.TURTLE, to_graph=TBOX_GRAPH)
                loaded[TBOX_GRAPH.value] = _count(store, TBOX_GRAPH)
            for manifest_path in sorted((src / "corpora").glob("*/manifest.json")):
                manifest = json.loads(manifest_path.read_text())
                for entry in manifest["files"]:
                    graph = NamedNode(entry["graph"])
                    store.load(
                        path=str(src / entry["path"]), format=RdfFormat.TURTLE, to_graph=graph
                    )
                    count = _count(store, graph)
                    if count != entry["statements"]:
                        raise DumpError(
                            f"{entry['path']}: loaded {count} statements, manifest says "
                            f"{entry['statements']}"
                        )
                    loaded[graph.value] = count
            store.flush()
        finally:
            del store
        os.rename(tmp, dest)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return loaded


def _count(store: Store, graph: NamedNode) -> int:
    return sum(1 for _ in store.quads_for_pattern(None, None, None, graph))


__all__ = [
    "DUMP_AUTHOR_EMAIL",
    "DUMP_AUTHOR_NAME",
    "DumpError",
    "DumpResult",
    "corpus_dirname",
    "restore_ttl_dump",
    "run_ttl_dump",
]
