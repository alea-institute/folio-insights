"""Signed authority covers every field emitted by a complete fork."""
import pytest

from folio_insights.polysemy.dispositions import append_disposition
from folio_insights.polysemy.distinguo import ForkNotReleased, emit_distinguo_fork_ttl
from tests.polysemy.test_review_fixes import _disposition, _fork

pytestmark = pytest.mark.usefixtures("registered_polysemy_reviewer")


@pytest.mark.parametrize(("field", "value"), [
    ("grouping_iri", "urn:test:another-group"),
    ("created_at_iso", "2026-10-21T12:00:00+00:00"),
    ("framework_iri", "urn:test:another-framework"),
    ("framework_label", "Different synthetic framework"),
    ("jurisdiction", "xx.synthetic"),
])
def test_signed_fork_cannot_release_changed_emission_fields(tmp_path, field, value):
    fork = _fork()
    record = _disposition(fork.to_proposed_fork())
    log = tmp_path / "dispositions.jsonl"
    append_disposition(record, log)
    assert "fi:distinguishes" in emit_distinguo_fork_ttl(fork, record, dispositions_path=log)
    if field in {"grouping_iri", "created_at_iso"}:
        altered = fork.model_copy(update={field: value})
    else:
        sense = fork.senses[0].model_copy(update={field: value})
        altered = fork.model_copy(update={"senses": (sense, *fork.senses[1:])})
    with pytest.raises(ForkNotReleased, match="not this fork"):
        emit_distinguo_fork_ttl(altered, record, dispositions_path=log)


def test_signed_descriptive_projection_without_complete_binding_cannot_release(tmp_path):
    fork = _fork()
    proposed = fork.to_proposed_fork().model_copy(update={"fork_sha256": None})
    record = _disposition(proposed)
    log = tmp_path / "dispositions.jsonl"
    append_disposition(record, log)
    with pytest.raises(ForkNotReleased):
        emit_distinguo_fork_ttl(fork, record, dispositions_path=log)
