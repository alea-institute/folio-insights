"""Corpus registry: tracks processed files via SHA-256 content hash.

Ensures files are not re-processed on subsequent pipeline runs unless
their content has changed.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from folio_insights.models.corpus import CorpusDocument, CorpusManifest

logger = logging.getLogger(__name__)


def _compute_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of file contents."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


class CorpusRegistry:
    """Tracks processed files by content hash within a named corpus.

    Persists state as a JSON manifest so that re-runs skip unchanged files.
    """

    def __init__(self, corpus_name: str = "default") -> None:
        self._manifest = CorpusManifest(
            name=corpus_name,
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        self._hash_index: dict[str, CorpusDocument] = {}

    @property
    def manifest(self) -> CorpusManifest:
        return self._manifest

    def needs_processing(self, file_path: Path) -> bool:
        """Check whether a file needs (re-)processing.

        Returns True if the file has not been processed or its content
        has changed since last processing.
        """
        file_path = Path(file_path).resolve()
        current_hash = _compute_hash(file_path)
        key = str(file_path)

        if key in self._hash_index:
            return self._hash_index[key].content_hash != current_hash
        return True

    def mark_processed(
        self, file_path: Path, format_name: str, unit_count: int = 0
    ) -> CorpusDocument:
        """Record a file as successfully processed.

        Args:
            file_path: Path to the processed file.
            format_name: Detected format (e.g. "markdown", "pdf").
            unit_count: Number of knowledge units extracted.

        Returns:
            The CorpusDocument entry.
        """
        file_path = Path(file_path).resolve()
        content_hash = _compute_hash(file_path)
        now = datetime.now(timezone.utc).isoformat()

        doc = CorpusDocument(
            file_path=str(file_path),
            content_hash=content_hash,
            format=format_name,
            processed_at=now,
            unit_count=unit_count,
        )

        key = str(file_path)
        if key in self._hash_index:
            # Update existing entry
            idx = next(
                i
                for i, d in enumerate(self._manifest.documents)
                if d.file_path == key
            )
            self._manifest.documents[idx] = doc
        else:
            self._manifest.documents.append(doc)

        self._hash_index[key] = doc
        self._manifest.updated_at = now
        return doc

    def save(self, output_dir: Path) -> Path:
        """Persist the corpus manifest as JSON.

        Returns the path to the written manifest file.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / f"corpus-{self._manifest.name}.json"

        data = self._manifest.model_dump()
        with open(manifest_path, "w") as f:
            json.dump(data, f, indent=2)

        logger.info("Saved corpus manifest: %s", manifest_path)
        return manifest_path

    @classmethod
    def load(cls, output_dir: Path, corpus_name: str = "default") -> CorpusRegistry:
        """Load a corpus registry from a previously saved manifest.

        Args:
            output_dir: Directory containing the manifest JSON.
            corpus_name: Name of the corpus to load.

        Returns:
            A CorpusRegistry with the loaded state.
        """
        manifest_path = Path(output_dir) / f"corpus-{corpus_name}.json"

        registry = cls(corpus_name)
        if not manifest_path.exists():
            logger.info("No existing manifest at %s, starting fresh", manifest_path)
            return registry

        with open(manifest_path) as f:
            data = json.load(f)

        registry._manifest = CorpusManifest(**data)
        registry._hash_index = {
            doc.file_path: doc for doc in registry._manifest.documents
        }
        logger.info(
            "Loaded corpus manifest: %s (%d documents)",
            manifest_path,
            len(registry._manifest.documents),
        )
        return registry
