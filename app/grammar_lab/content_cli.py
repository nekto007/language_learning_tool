"""Deployment commands: validation/dry-run by default; apply always backs up."""

import json
from pathlib import Path

import click


def register_content_commands(app):
    @app.cli.command("grammar-guided-install")
    @click.option("--topic", "topics", multiple=True, help="A reviewed topic slug; may be repeated.")
    @click.option("--level", type=click.Choice(["A1", "A2", "B1", "B2", "C1"]))
    @click.option("--apply", is_flag=True, help="Apply the validated content in one transaction.")
    @click.option("--backup-dir", type=click.Path(file_okay=False, path_type=Path))
    def install(topics, level, apply, backup_dir):
        """Validate all 86 topics; show a plan unless --apply is passed."""
        from app.grammar_lab.content_catalog import expected_slugs
        from app.grammar_lab.content_install import install_catalog

        if topics and level:
            raise click.UsageError("Use --topic or --level, not both")
        slugs = list(topics) or ([s for s in expected_slugs() if s.startswith(level.lower() + "-")] if level else None)
        try:
            result = install_catalog(slugs=slugs, apply=apply, backup_dir=backup_dir)
        except ValueError as error:
            raise click.ClickException(str(error)) from error
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))

    @app.cli.command("grammar-guided-restore")
    @click.option("--backup", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
    @click.option("--apply", is_flag=True, help="Restore content, preserving all learner history.")
    def restore(backup, apply):
        """Inspect/restore a previous import; refuse to overwrite newer edits."""
        from app.grammar_lab.content_install import restore_catalog

        try:
            result = restore_catalog(backup, apply=apply)
        except ValueError as error:
            raise click.ClickException(str(error)) from error
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
