"""CLI entry point for codebase-graph."""

import click


@click.group()
@click.version_option()
def cli():
    """Code navigation & context compression for agents."""
    pass


@cli.command()
def stats():
    """Show index statistics."""
    click.echo("No index found. Run 'cg index' first.")
