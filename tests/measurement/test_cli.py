"""Combined measurement command surface; future operations fail explicitly."""
import click
from click.testing import CliRunner
import pytest

from folio_insights.measurement.cli import cli, measurement_group


def test_validate_gold_and_command_surface():
    runner = CliRunner()
    result = runner.invoke(measurement_group, ["validate-gold"])
    assert result.exit_code == 0 and '"documents": 8' in result.output
    help_result = runner.invoke(measurement_group, ["--help"])
    for command in ("validate-gold", "run", "baseline", "compare", "annotations", "corpus", "readme"):
        assert command in help_result.output


def test_combined_parser_exposes_coordinator_and_corpus_commands():
    assert cli is measurement_group
    with click.Context(measurement_group) as context:
        assert measurement_group.list_commands(context) == [
            "annotations", "baseline", "compare", "corpus", "readme", "run", "validate-gold",
        ]
        for name, expected in (
            ("corpus", ["collect", "seal", "verify"]),
            ("annotations", ["export-tuning", "history"]),
        ):
            group = measurement_group.get_command(context, name)
            assert isinstance(group, click.Group)
            with click.Context(group, parent=context) as child_context:
                assert group.list_commands(child_context) == expected


@pytest.mark.parametrize("command", ["baseline", "compare", "readme"])
def test_later_unit_commands_fail_unavailable(command):
    result = CliRunner().invoke(measurement_group, [command])
    assert result.exit_code != 0 and "unavailable" in result.output.lower()


def test_run_requires_frozen_inputs_and_extractions():
    result = CliRunner().invoke(measurement_group, ["run"])
    assert result.exit_code != 0 and "Missing option" in result.output


def test_annotations_tuning_export_is_read_only(tmp_path):
    result = CliRunner().invoke(measurement_group, ["annotations", "export-tuning", "--db",
                                                 str(tmp_path / "absent.db")])
    assert result.exit_code == 0 and result.output.strip() == "[]"
    assert not (tmp_path / "absent.db").exists()
