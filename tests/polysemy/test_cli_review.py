"""Wave-0 placeholder for `folio-insights polysemy review` CLI. Impl lands in 01-05."""
import pytest

pytestmark = pytest.mark.polysemy_spike


@pytest.mark.xfail(reason="Wave-0 scaffold; impl in 01-05", strict=False)
def test_no_auto_apply_path() -> None:
    """CLI has no auto-apply path (§16 R2 no-auto-apply anti-feature;
    every disposition requires a keystroke per D-3 CLI-only lock)."""
    raise NotImplementedError("Wave-0 placeholder")


@pytest.mark.xfail(reason="Wave-0 scaffold; impl in 01-05", strict=False)
def test_accept_reject_modify_paths() -> None:
    """CliRunner + scripted stdin exercises accept / reject / modify paths;
    each emits a disposition record to dispositions.jsonl."""
    raise NotImplementedError("Wave-0 placeholder")
