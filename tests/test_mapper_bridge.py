"""Unit tests for the tabular MapperBridge: the folio-mapper path and the CSV fallback.

The bridge is KEPT (see docs/bridge-retirement-2026-10-09.md). These tests pin both
of its paths without needing a folio-mapper checkout: the mapper path is exercised
through a stub ``file_parser`` module that honors folio-mapper's ``parse_file``
contract (``parse_file(content, filename).items`` of objects with ``.text`` and
``.index``).
"""

from __future__ import annotations

import types
import zipfile
from pathlib import Path

import pytest

from folio_insights.services.bridge import mapper_bridge
from folio_insights.services.bridge.mapper_bridge import MapperBridge


@pytest.fixture
def no_mapper(monkeypatch):
    """Force the 'folio-mapper checkout absent' state."""
    monkeypatch.setattr(mapper_bridge, "_mapper_checked", True)
    monkeypatch.setattr(mapper_bridge, "_mapper_path", None)


@pytest.fixture
def stub_mapper(monkeypatch, tmp_path):
    """Pretend folio-mapper is present and its file_parser loads as a stub module."""
    monkeypatch.setattr(mapper_bridge, "_mapper_checked", True)
    monkeypatch.setattr(mapper_bridge, "_mapper_path", str(tmp_path))
    calls: list[tuple[bytes, str]] = []

    def parse_file(content: bytes, filename: str):
        calls.append((content, filename))
        rows = [r for r in content.decode("utf-8").splitlines() if r.strip()]
        items = [
            types.SimpleNamespace(text=r.split(",")[0].strip(), index=i)
            for i, r in enumerate(rows[1:])  # mapper drops a detected header row
        ]
        return types.SimpleNamespace(items=items)

    module = types.SimpleNamespace(parse_file=parse_file)
    monkeypatch.setattr(mapper_bridge, "_load_mapper_file_parser", lambda: module)
    return calls


def _write(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.write_text(text, encoding=encoding)
    return path


# ---- CSV fallback -----------------------------------------------------------------------


def test_fallback_csv_joins_non_empty_cells(no_mapper, tmp_path):
    f = _write(tmp_path / "t.csv", "Name,Desc\nAlpha,one\nBeta, two \n")
    assert MapperBridge().parse_tabular(f) == [
        {"text": "Name | Desc", "index": 0},
        {"text": "Alpha | one", "index": 1},
        {"text": "Beta | two", "index": 2},
    ]


def test_fallback_tsv_uses_tab_delimiter(no_mapper, tmp_path):
    f = _write(tmp_path / "t.tsv", "Rule\tSource\nHearsay, generally\tFRE 802\n")
    assert MapperBridge().parse_tabular(f) == [
        {"text": "Rule | Source", "index": 0},
        {"text": "Hearsay, generally | FRE 802", "index": 1},
    ]


def test_fallback_skips_blank_rows_and_cells_and_keeps_row_index(no_mapper, tmp_path):
    f = _write(tmp_path / "t.csv", "a,,b\n,,\n\n ,c, \n")
    assert MapperBridge().parse_tabular(f) == [
        {"text": "a | b", "index": 0},
        {"text": "c", "index": 3},
    ]


def test_fallback_strips_utf8_bom_and_keeps_unicode(no_mapper, tmp_path):
    f = _write(tmp_path / "t.csv", "Café,“quoted”\n", encoding="utf-8-sig")
    assert (tmp_path / "t.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    assert MapperBridge().parse_tabular(f) == [{"text": "Café | “quoted”", "index": 0}]


def test_fallback_cannot_read_xlsx_and_returns_no_rows(no_mapper, tmp_path):
    """.xlsx is the kept-on-bridge format: the stdlib fallback yields nothing for it."""
    f = tmp_path / "t.xlsx"
    with zipfile.ZipFile(f, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/worksheets/sheet1.xml", "<worksheet>" + "<row/>" * 500 + "</worksheet>")
    assert MapperBridge().parse_tabular(f) == []


def test_missing_file_raises(no_mapper, tmp_path):
    with pytest.raises(FileNotFoundError):
        MapperBridge().parse_tabular(tmp_path / "absent.csv")


def test_absent_checkout_reports_unavailable(monkeypatch, tmp_path):
    from folio_insights.config import get_settings

    monkeypatch.setattr(mapper_bridge, "_mapper_checked", False)
    monkeypatch.setattr(mapper_bridge, "_mapper_path", None)
    monkeypatch.setattr(get_settings(), "folio_mapper_path", tmp_path / "nope")
    assert MapperBridge()._mapper_available is False


# ---- folio-mapper path ------------------------------------------------------------------


def test_mapper_path_maps_items_to_text_and_index(stub_mapper, tmp_path):
    f = _write(tmp_path / "t.csv", "Name,Desc\nAlpha,one\nBeta,two\n")
    bridge = MapperBridge()
    assert bridge._mapper_available is True
    assert bridge.parse_tabular(f) == [
        {"text": "Alpha", "index": 0},
        {"text": "Beta", "index": 1},
    ]
    assert stub_mapper == [(f.read_bytes(), "t.csv")]


def test_mapper_load_failure_falls_back_to_csv(monkeypatch, tmp_path):
    monkeypatch.setattr(mapper_bridge, "_mapper_checked", True)
    monkeypatch.setattr(mapper_bridge, "_mapper_path", str(tmp_path))
    monkeypatch.setattr(mapper_bridge, "_load_mapper_file_parser", lambda: None)
    f = _write(tmp_path / "t.csv", "x,y\n")
    assert MapperBridge().parse_tabular(f) == [{"text": "x | y", "index": 0}]


def test_mapper_parse_error_falls_back_to_csv(monkeypatch, tmp_path):
    monkeypatch.setattr(mapper_bridge, "_mapper_checked", True)
    monkeypatch.setattr(mapper_bridge, "_mapper_path", str(tmp_path))

    def boom(content, filename):
        raise ValueError("synthetic parse failure")

    monkeypatch.setattr(
        mapper_bridge, "_load_mapper_file_parser", lambda: types.SimpleNamespace(parse_file=boom)
    )
    f = _write(tmp_path / "t.csv", "x,y\n")
    assert MapperBridge().parse_tabular(f) == [{"text": "x | y", "index": 0}]


def test_real_mapper_file_parser_without_openpyxl_falls_back(monkeypatch, tmp_path):
    """A mapper checkout whose file_parser cannot import (as with folio-mapper's, which
    needs openpyxl + its own ``app`` package) degrades to the CSV fallback, not an error."""
    services = tmp_path / "app" / "services"
    services.mkdir(parents=True)
    (services / "file_parser.py").write_text(
        "import a_module_that_does_not_exist_xyz\n", encoding="utf-8"
    )
    monkeypatch.setattr(mapper_bridge, "_mapper_checked", True)
    monkeypatch.setattr(mapper_bridge, "_mapper_path", str(tmp_path))
    assert mapper_bridge._load_mapper_file_parser() is None
    f = _write(tmp_path / "t.csv", "x,y\n")
    assert MapperBridge().parse_tabular(f) == [{"text": "x | y", "index": 0}]
