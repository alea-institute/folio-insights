"""folio-insights: Extract structured advocacy knowledge from legal textbooks and map to FOLIO ontology."""

__version__ = "0.1.0"

__all__ = ["__version__"]


def main() -> None:
    """CLI entry point."""
    from folio_insights.cli import main as cli_main

    cli_main()
