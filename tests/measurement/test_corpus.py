"""Acquisition and sealing use in-memory HTTP fixtures, never a live source."""
from __future__ import annotations

import hashlib
import json
from datetime import date

import httpx
import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from folio_insights.measurement.corpus import (
    AcquisitionPolicy, CorpusError, DocumentRequest, HttpFetcher, Rights,
    collect, load_manifest, load_policy, seal, verify,
)
from folio_insights.measurement.cli import cli


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def policy() -> AcquisitionPolicy:
    return AcquisitionPolicy.model_validate({
        "format": 1, "sources": [{
            "source_id": "official", "publisher": "Fixture court",
            "url_prefixes": ["https://court.example/opinions/"],
            "access_method": "direct-download", "auth_env": None,
            "auth_style": "none", "rate_limits": {"minimum_interval_seconds": 1},
            "robots_url": "https://court.example/robots.txt",
            "terms_url": "https://court.example/terms", "rights_basis": "Document-specific edicts",
            "substitute_forum_label": None,
        }],
    })


def rights(basis: str = "government-edicts") -> dict:
    return {"basis": basis, "supporting_url": "https://court.example/rights",
            "checked_date": "2026-10-26", "retained_evaluation_allowed": True,
            "original_retention_allowed": True,
            "exclusions": ["Publisher headnotes and third-party material"]}


def requests(genre: str = "opinions") -> list[DocumentRequest]:
    return [DocumentRequest.model_validate({
        "document_id": f"doc-{i}", "source_id": "official", "group_id": f"case-{i}",
        "url": f"https://court.example/opinions/{i}", "title": f"Decision {i}",
        "jurisdiction": "federal", "genre": genre,
        "subgenre": ("statute" if i < 4 else "regulation") if genre == "statutes-regulations" else "opinion",
        "forum": "Fixture federal court", "case_section": f"Case {i}",
        "document_date": "2026-01-01", "extraction_method": "html-xpath-v1",
        "selector": "//article", "span": {"start": 0, "end": len(text(i))},
        "rights": rights(),
    }) for i in range(8)]


def text(i: int) -> str:
    return (f"Decision {i}. 🦉 " + "The court requires proof of every element. " * 24).rstrip()


class FixtureServer:
    def __init__(self):
        self.calls = []
        self.version = 1
        self.status = 200
        self.headers = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        i = int(request.url.path.rsplit("/", 1)[1])
        body = f"<html><aside>Excluded headnote</aside><article>{text(i)}</article><!--{self.version}--></html>"
        return httpx.Response(self.status, content=body.encode(), headers=self.headers)


@pytest.fixture
def acquisition(tmp_path):
    server = FixtureServer()
    now = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    client = httpx.Client(transport=httpx.MockTransport(server))
    fetcher = HttpFetcher(client, user_agent="Folio research (contact@example.test)",
                          clock=lambda: now[0], sleep=sleep)
    yield server, fetcher, sleeps
    client.close()


def test_official_edicts_admitted_private_brief_refused(tmp_path, acquisition):
    server, fetcher, _ = acquisition
    admitted = collect(requests(), policy(), tmp_path / "opinions", fetcher)
    assert verify(admitted, tmp_path / "opinions").complete
    items = requests("briefs")
    bad = items[-1].model_dump(mode="json")
    bad.update(subgenre="private-brief")
    bad["rights"].update(basis="permission", retained_evaluation_allowed=False)
    for i, item in enumerate(items):
        row = item.model_dump(mode="json")
        row["rights"].update(basis="permission")
        items[i] = DocumentRequest.model_validate(row)
    items[-1] = DocumentRequest.model_validate(bad)
    manifest = collect(items, policy(), tmp_path / "briefs", fetcher)
    assert len(manifest.documents) == 7
    assert len(server.calls) == 15  # refusal precedes fetching or retaining bytes
    assert manifest.gaps[0].document_id == "doc-7"
    result = verify(manifest, tmp_path / "briefs")
    assert not result.complete
    assert any("eight" in error for error in result.errors)
    assert any("rights" in error for error in result.errors)
    with pytest.raises(CorpusError, match="incomplete"):
        seal(manifest, tmp_path / "briefs", tmp_path / "tuning")


@pytest.mark.parametrize("basis", ["government-edicts", "federal-work", "license", "permission"])
def test_rights_basis_must_apply_to_the_document(tmp_path, acquisition, basis):
    _, fetcher, _ = acquisition
    item = requests()[0].model_dump(mode="json")
    item.update(genre="briefs", subgenre="private-brief", official_text=False,
                federal_employee_work=False)
    item["rights"].update(basis=basis)
    manifest = collect([DocumentRequest.model_validate(item)], policy(), tmp_path, fetcher)
    assert bool(manifest.documents) == (basis in {"license", "permission"})


def test_changed_raw_bytes_new_snapshot_and_exact_unicode_offsets(tmp_path, acquisition):
    server, fetcher, _ = acquisition
    first = collect(requests(), policy(), tmp_path / "first", fetcher)
    server.version = 2
    second = collect(requests(), policy(), tmp_path / "second", fetcher)
    a, b = first.documents[0], second.documents[0]
    assert a.snapshot_id != b.snapshot_id
    assert a.raw_sha256 != b.raw_sha256
    assert a.normalized_sha256 == b.normalized_sha256
    canonical = (tmp_path / "first" / "text" / f"{a.normalized_sha256}.txt").read_text()
    assert a.request.span.source_slice(canonical) == text(0)
    assert a.span_sha256 == digest(text(0).encode())
    assert verify(first, tmp_path / "first").complete


@pytest.mark.parametrize("fault", ["missing", "group", "duplicate-content", "related"])
def test_eight_document_groups_are_independent(tmp_path, acquisition, fault):
    _, fetcher, _ = acquisition
    items = requests()
    if fault == "missing":
        items.pop()
    else:
        change = items[-1].model_dump(mode="json")
        if fault == "group":
            change["group_id"] = items[0].group_id
        elif fault == "related":
            change["related_group_ids"] = [items[0].group_id]
        else:
            change["url"] = items[0].url
        items[-1] = DocumentRequest.model_validate(change)
    manifest = collect(items, policy(), tmp_path, fetcher)
    assert not verify(manifest, tmp_path).complete


def test_split_reproducible_and_statute_rule_mix(tmp_path, acquisition):
    _, fetcher, _ = acquisition
    a = collect(requests("statutes-regulations"), policy(), tmp_path / "a", fetcher, seed=11)
    b = collect(list(reversed(requests("statutes-regulations"))), policy(), tmp_path / "b", fetcher, seed=11)
    assert {d.request.document_id: d.partition for d in a.documents} == {
        d.request.document_id: d.partition for d in b.documents}
    assert [d.partition for d in a.documents].count("held-out") == 2
    assert {d.request.subgenre for d in a.documents if d.partition == "held-out"} == {"statute", "regulation"}
    assert verify(a, tmp_path / "a").complete
    data = a.model_dump(mode="json")
    data["documents"][0]["request"]["subgenre"] = "regulation"
    assert any("four" in e for e in verify(type(a).model_validate(data), tmp_path / "a").errors)


@pytest.mark.parametrize("fault", ["split", "raw", "canonical", "offset", "proof", "gold"])
def test_offline_verify_detects_tampering(tmp_path, acquisition, fault):
    server, fetcher, _ = acquisition
    manifest = collect(requests(), policy(), tmp_path, fetcher)
    data = manifest.model_dump(mode="json")
    doc = data["documents"][0]
    if fault == "split":
        for row in data["documents"]:
            row["partition"] = "tuning"
    elif fault == "raw":
        (tmp_path / "raw" / f"{doc['raw_sha256']}.bin").write_bytes(b"changed")
    elif fault == "canonical":
        (tmp_path / "text" / f"{doc['normalized_sha256']}.txt").write_text("changed")
    elif fault == "offset":
        doc["request"]["span"]["end"] -= 1
    elif fault == "proof":
        doc["request"]["rights"]["retained_evaluation_allowed"] = False
    else:
        doc["propositions"] = [{"item_id": "p", "kind": "rule", "text": "An atomic claim",
                                "span": {"start": 0, "end": 99999},
                                "tags": [{"label": "Obligation", "branch": "Deontic Specification"}]}]
    # No network is needed, even if a transport is unavailable after collection.
    calls = len(server.calls)
    assert not verify(type(manifest).model_validate(data), tmp_path).complete
    assert len(server.calls) == calls


def test_seal_distributes_only_tuning_and_stores_text_once(tmp_path, acquisition):
    _, fetcher, _ = acquisition
    root, tuning = tmp_path / "evaluator", tmp_path / "tuning"
    manifest = collect(requests(), policy(), root, fetcher)
    heldout = [d for d in manifest.documents if d.partition == "held-out"]
    data = manifest.model_dump(mode="json")
    for d in data["documents"]:
        d["judge_rationale"] = f"private-review-{d['request']['document_id']}"
    manifest = type(manifest).model_validate(data)
    seal(manifest, root, tuning)
    exported = json.loads((tuning / "manifest.json").read_text())
    assert len(exported["documents"]) == 6
    assert exported["score_label"] == "judge agreement, unanchored"
    serialized = "\n".join(p.read_text() for p in tuning.rglob("*") if p.is_file())
    for d in heldout:
        assert d.request.url not in serialized
        assert d.request.document_id not in serialized
        assert text(int(d.request.document_id.rsplit("-", 1)[1])) not in serialized
    assert "private-review" not in serialized
    assert len(list((tuning / "text").glob("*.txt"))) == 6
    assert not (tuning / "raw").exists()
    assert (root / "sealed.json").exists()
    with pytest.raises(CorpusError, match="exist"):
        seal(manifest, root, tuning)


def test_rate_limit_bounds_access_and_auth_is_read_only_at_fetch(tmp_path, acquisition, monkeypatch):
    server, fetcher, sleeps = acquisition
    data = policy().model_dump(mode="json")
    source = data["sources"][0]
    source.update(auth_env="COURT_FIXTURE_TOKEN", auth_style="token")
    source["rate_limits"].update(per_minute=2)
    auth_policy = AcquisitionPolicy.model_validate(data)
    monkeypatch.setenv("COURT_FIXTURE_TOKEN", "fixture-credential")
    collect(requests()[:3], auth_policy, tmp_path, fetcher)
    assert sum(sleeps) >= 60
    assert all(r.headers["Authorization"] == "Token fixture-credential" for r in server.calls)
    assert "fixture-credential" not in (tmp_path / "manifest.json").read_text()
    assert "COURT_FIXTURE_TOKEN" in (tmp_path / "manifest.json").read_text()


@pytest.mark.parametrize("status", [403, 429, 302])
def test_access_denial_and_retry_after_leave_gaps(tmp_path, acquisition, status):
    server, fetcher, sleeps = acquisition
    server.status = status
    server.headers = {"Retry-After": "120", "Location": "https://other.example/"}
    manifest = collect(requests()[:2], policy(), tmp_path, fetcher)
    assert not manifest.documents and len(manifest.gaps) == 2
    assert not list((tmp_path / "raw").glob("*"))
    if status == 429:
        assert sum(sleeps) >= 120


def test_blocked_policy_and_missing_auth_do_not_fetch(tmp_path, acquisition, monkeypatch):
    server, fetcher, _ = acquisition
    data = policy().model_dump(mode="json")
    data["sources"][0]["access_status"] = "pending-review"
    assert collect(requests(), AcquisitionPolicy.model_validate(data), tmp_path / "blocked", fetcher).gaps
    data["sources"][0].update(access_status="permitted", auth_env="UNSET_FIXTURE_TOKEN", auth_style="bearer")
    monkeypatch.delenv("UNSET_FIXTURE_TOKEN", raising=False)
    assert collect(requests(), AcquisitionPolicy.model_validate(data), tmp_path / "auth", fetcher).gaps
    assert not server.calls


def test_policy_records_access_rights_and_substitute_forum():
    loaded = load_policy()
    assert loaded.sources
    assert any(s.auth_env == "COURTLISTENER_TOKEN" for s in loaded.sources)
    assert any(s.substitute_forum_label for s in loaded.sources)
    for source in loaded.sources:
        assert source.access_method and source.rate_limits.minimum_interval_seconds > 0
        assert source.robots_url and source.terms_url and source.rights_basis
    with pytest.raises(ValidationError):
        Rights.model_validate({**rights(), "supporting_url": ""})
    assert Rights.model_validate(rights()).checked_date == date(2026, 10, 26)


def test_cli_collect_verify_seal_offline(tmp_path, acquisition):
    _, fetcher, _ = acquisition
    root = tmp_path / "evaluator"
    manifest = collect(requests(), policy(), root, fetcher)
    assert load_manifest(root / "manifest.json") == manifest
    runner = CliRunner()
    result = runner.invoke(cli, ["corpus", "verify", "--evaluator-root", str(root),
                                 "--jurisdiction", "federal", "--genre", "opinions", "--require-documents", "8"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(cli, ["corpus", "seal", "--evaluator-root", str(root),
                                 "--tuning-output", str(tmp_path / "tuning")])
    assert result.exit_code == 0, result.output
    assert "collect" in runner.invoke(cli, ["corpus", "--help"]).output


def test_draft_gold_uses_offsets_and_cannot_anchor_itself(tmp_path, acquisition):
    from folio_insights.measurement.schema import GoldProposition

    _, fetcher, _ = acquisition
    seen = []

    def draft(source):
        seen.append(source)
        return [GoldProposition.model_validate({
            "item_id": "rule", "kind": "rule", "text": "Proof of all elements is required.",
            "span": {"start": 0, "end": len(source.text)},
            "tags": [{"label": "Obligation", "branch": "Deontic Specification"}],
        })]

    manifest = collect(requests(), policy(), tmp_path, fetcher, draft_gold=draft)
    assert len(seen) == 8
    assert all(not s.synthetic for s in seen)
    assert verify(manifest, tmp_path).complete
    assert all(d.gold_status == "draft" and len(d.propositions) == 1 for d in manifest.documents)
    assert manifest.score_label == "judge agreement, unanchored"
    serialized = manifest.model_dump(mode="json")
    assert serialized["documents"][0]["propositions"][0]["span"] == {
        "start": 0, "end": len(text(0))}


@pytest.mark.parametrize("method,selector,body", [
    ("utf8-v1", None, lambda s: s.encode()),
    ("xml-xpath-v1", "//article", lambda s: f"<root><article>{s}</article></root>".encode()),
    ("json-field-v1", "plain_text", lambda s: json.dumps({"plain_text": s}).encode()),
])
def test_recorded_text_xml_and_api_formats(tmp_path, method, selector, body):
    item = requests()[0].model_copy(update={"extraction_method": method, "selector": selector})
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body(text(0))))) as client:
        manifest = collect([item], policy(), tmp_path, HttpFetcher(client, user_agent="Fixture contact"))
    assert len(manifest.documents) == 1
    doc = manifest.documents[0]
    assert (tmp_path / "text" / f"{doc.normalized_sha256}.txt").read_text() == text(0)


@pytest.mark.parametrize("fault", ["bytes", "challenge", "outside-policy", "original-rights"])
def test_unusable_acquisitions_do_not_retain_bytes(tmp_path, acquisition, fault):
    server, fetcher, _ = acquisition
    item = requests()[0].model_dump(mode="json")
    source_policy = policy()
    if fault == "bytes":
        source_policy = source_policy.model_copy(update={"max_download_bytes": 1})
    elif fault == "outside-policy":
        item["url"] = "https://other.example/opinions/0"
    elif fault == "original-rights":
        item["rights"]["original_retention_allowed"] = False
    if fault == "challenge":
        transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"<title>Just a moment</title>"))
        with httpx.Client(transport=transport) as client:
            manifest = collect([DocumentRequest.model_validate(item)], source_policy, tmp_path,
                               HttpFetcher(client, user_agent="Fixture contact"))
    else:
        manifest = collect([DocumentRequest.model_validate(item)], source_policy, tmp_path, fetcher)
    assert not manifest.documents and len(manifest.gaps) == 1
    assert not list((tmp_path / "raw").glob("*"))
    if fault in {"outside-policy", "original-rights"}:
        assert not server.calls


def test_cli_collect_uses_recorded_transport(tmp_path, acquisition, monkeypatch):
    server, _, _ = acquisition
    input_path, policy_path = tmp_path / "requests.json", tmp_path / "policy.json"
    input_path.write_text(json.dumps([requests()[0].model_dump(mode="json")]))
    policy_path.write_text(policy().model_dump_json())
    client_factory = httpx.Client
    monkeypatch.setattr("folio_insights.measurement.cli.httpx.Client",
                        lambda: client_factory(transport=httpx.MockTransport(server)))
    result = CliRunner().invoke(cli, ["corpus", "collect", "--requests", str(input_path),
                                     "--policy", str(policy_path), "--user-agent", "Fixture contact",
                                     "--evaluator-root", str(tmp_path / "evaluator")])
    assert result.exit_code == 1  # acquired successfully; eight-document cell is incomplete
    assert '"documents":1' in result.output
    assert len(server.calls) == 1
    assert load_manifest(tmp_path / "evaluator" / "manifest.json").documents


def test_tuning_package_does_not_copy_policy_urls_for_heldout_documents(tmp_path, acquisition):
    _, fetcher, _ = acquisition
    data = policy().model_dump(mode="json")
    data["sources"][0]["url_prefixes"] = [r.url for r in requests()]
    root, tuning = tmp_path / "evaluator", tmp_path / "tuning"
    manifest = collect(requests(), AcquisitionPolicy.model_validate(data), root, fetcher)
    seal(manifest, root, tuning)
    serialized = (tuning / "manifest.json").read_text()
    for doc in manifest.documents:
        if doc.partition == "held-out":
            assert doc.request.url not in serialized


def test_nonzero_offsets_survive_tuning_export_with_original_coordinates(tmp_path):
    prefix = "🦉 Préface. "
    items = []
    for item in requests():
        items.append(item.model_copy(update={"extraction_method": "utf8-v1", "selector": None,
                     "span": item.span.model_copy(update={"start": len(prefix),
                                                           "end": len(prefix) + item.span.end})}))

    def serve(request):
        i = int(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(200, content=(prefix + text(i)).encode())

    root, tuning = tmp_path / "evaluator", tmp_path / "tuning"
    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        manifest = collect(items, policy(), root,
                           HttpFetcher(client, user_agent="Fixture contact", sleep=lambda _: None))
    assert verify(manifest, root).complete
    seal(manifest, root, tuning)
    payload = json.loads((tuning / "manifest.json").read_text())
    for doc in payload["documents"]:
        assert doc["origin_span"]["start"] == len(prefix)
        assert doc["request"]["span"]["start"] == 0
        stored = (tuning / "text" / f"{doc['text_sha256']}.txt").read_text()
        assert stored.startswith("Decision") and prefix not in stored


@pytest.mark.parametrize("url", ["https://court.example/opinions/../blocked/0",
                                "https://court.example/opinions/0?api-key=credential"])
def test_source_urls_cannot_embed_credentials_or_escape_allowed_paths(url):
    row = requests()[0].model_dump(mode="json")
    row["url"] = url
    with pytest.raises(ValidationError):
        DocumentRequest.model_validate(row)


def test_plan_verification_command_resolves_default_cell_directory(tmp_path, acquisition, monkeypatch):
    _, fetcher, _ = acquisition
    root = tmp_path / "output/measurement/sealed/federal/opinions"
    collect(requests(), policy(), root, fetcher)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["corpus", "verify", "--jurisdiction", "federal",
                                     "--genre", "opinions", "--require-documents", "8"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("auth_style", ["none", "bearer", "token", "query-key"])
def test_source_query_survives_fetch_without_persisting_auth(tmp_path, acquisition, monkeypatch, auth_style):
    server, fetcher, _ = acquisition
    data = policy().model_dump(mode="json")
    if auth_style != "none":
        data["sources"][0].update(auth_env="COURT_FIXTURE_TOKEN", auth_style=auth_style)
    monkeypatch.setenv("COURT_FIXTURE_TOKEN", "fixture credential&+")
    item = requests()[0].model_copy(update={
        "url": requests()[0].url + "?version=2026&part=5&part=6&label=a%20b&empty="})
    manifest = collect([item], AcquisitionPolicy.model_validate(data), tmp_path, fetcher)
    assert len(manifest.documents) == 1
    expected_url = item.url
    if auth_style == "query-key":
        expected_url += "&key=fixture+credential%26%2B"
    assert str(server.calls[0].url) == expected_url
    assert manifest.documents[0].request.url == item.url
    serialized = (tmp_path / "manifest.json").read_text()
    assert item.url in serialized
    assert "fixture credential" not in serialized and "key=" not in serialized


@pytest.mark.parametrize("suffix", ["", "\r\nTrailing material outside the selection."])
def test_tuning_export_preserves_crlf_bytes_and_selection_digest(tmp_path, suffix):
    prefix = "🦉 Préface.\r\n"
    selected = {i: text(i).replace(". ", ".\r\n") for i in range(8)}
    items = [item.model_copy(update={
        "extraction_method": "utf8-v1", "selector": None,
        "span": item.span.model_copy(update={"start": len(prefix),
                                             "end": len(prefix) + len(selected[i])}),
    }) for i, item in enumerate(requests())]

    def serve(request):
        i = int(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(200, content=(prefix + selected[i] + suffix).encode("utf-8"))

    root, tuning = tmp_path / "evaluator", tmp_path / "tuning"
    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        manifest = collect(items, policy(), root,
                           HttpFetcher(client, user_agent="Fixture contact", sleep=lambda _: None))
    assert verify(manifest, root).complete
    seal(manifest, root, tuning)
    payload = json.loads((tuning / "manifest.json").read_bytes())
    for doc in payload["documents"]:
        i = int(doc["request"]["document_id"].rsplit("-", 1)[1])
        exported = (tuning / "text" / f"{doc['text_sha256']}.txt").read_bytes()
        assert exported == selected[i].encode("utf-8")
        assert digest(exported) == doc["text_sha256"] == doc["span_sha256"]
        assert doc["origin_span"] == {"start": len(prefix), "end": len(prefix) + len(selected[i])}
        assert doc["request"]["span"] == {"start": 0, "end": len(selected[i])}


@pytest.mark.parametrize("raw", [b"[]", b"null", b'"scalar"', b"42", b"true"])
@pytest.mark.parametrize("phase", ["collect", "verify"])
def test_non_object_json_is_a_document_gap(tmp_path, raw, phase):
    items = [item.model_copy(update={"extraction_method": "json-field-v1", "selector": "plain_text"})
             for item in requests()]
    calls = []

    def serve(request):
        calls.append(request)
        i = int(request.url.path.rsplit("/", 1)[1])
        body = raw if phase == "collect" and i == 0 else json.dumps({"plain_text": text(i)}).encode()
        return httpx.Response(200, content=body)

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        manifest = collect(items, policy(), tmp_path,
                           HttpFetcher(client, user_agent="Fixture contact", sleep=lambda _: None))
    assert len(calls) == 8
    if phase == "collect":
        assert len(manifest.documents) == 7
        assert len(manifest.gaps) == 1
        assert manifest.gaps[0].document_id == "doc-0"
        assert manifest.gaps[0].reason == "JSON response is not an object"
    else:
        assert verify(manifest, tmp_path).complete
        # Keep the raw digest valid so verification reaches extraction of the recorded fixture.
        (tmp_path / "raw" / f"{digest(raw)}.bin").write_bytes(raw)
        doc = manifest.documents[0].model_copy(update={"raw_sha256": digest(raw)})
        manifest = manifest.model_copy(update={"documents": (doc, *manifest.documents[1:])})
    result = verify(manifest, tmp_path)
    assert not result.complete
    assert "doc-0: JSON response is not an object" in result.errors
    assert not any(error.startswith("doc-1:") for error in result.errors)
