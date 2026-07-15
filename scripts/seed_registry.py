"""Seed / update the proposed-class registry from one or more pipeline runs.

Idempotent: re-running is a no-op; new runs append. Then runs deterministic
dedupe (FOLIO lexicon + within-registry merges). Judging retrieval/floor and
the Claude-side verdicts are applied by scripts/judge_proposals.py + the judge
worklist flow.

Usage:
  python scripts/seed_registry.py \
    --registry data/governance/proposed_class_registry.json \
    --owl <FOLIO.owl> --lexicon-cache <lexicon.json> \
    --run output/uat_ta_ch01_v5:Trial Advocacy 7e:1 \
    --run output/uat_ta_ch02_v5:Trial Advocacy 7e:2 \
    --run output/uat_ta_ch03_v5:Trial Advocacy 7e:3
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from folio_insights.proposals.registry import ProposalRegistry, load_run_proposals  # noqa
from folio_insights.proposals.lexicon import FolioLexicon  # noqa
from folio_insights.proposals.dedupe import DeterministicDeduper  # noqa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", required=True)
    ap.add_argument("--owl", required=True)
    ap.add_argument("--lexicon-cache", required=True)
    ap.add_argument("--run", action="append", required=True,
                    help="output_dir:book:chapter")
    args = ap.parse_args()

    reg = ProposalRegistry.load(args.registry)
    ingest_stats = []
    for spec in args.run:
        # split from the right twice so book names may contain ':' -> avoided by fixed order
        out_dir, book, chapter = spec.rsplit(":", 2)
        run_name = Path(out_dir).name
        pcs, spans = load_run_proposals(out_dir)
        st = reg.ingest_run(pcs, run=run_name, book=book, chapter=chapter,
                            spans_by_unit=spans)
        ingest_stats.append({"run": run_name, **st})

    lex = FolioLexicon.load_or_build(str(Path(args.owl).expanduser()), args.lexicon_cache)
    ded = DeterministicDeduper(lex)
    dd = ded.judge_registry(reg.all_entries())
    reg.save()

    print(json.dumps({
        "total_proposals": len(reg.entries),
        "ingest": ingest_stats,
        "deterministic_dedupe": dd,
        "survivors": len(ded.survivors(reg.all_entries())),
    }, indent=2))


if __name__ == "__main__":
    main()
