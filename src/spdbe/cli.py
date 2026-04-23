"""CLI interface for the SPD Berlin corpus pipeline."""

from __future__ import annotations

from pathlib import Path

import click


@click.group()
def main():
    """spdbe — SPD Berlin Antragskorpus pipeline."""
    pass


@main.command()
@click.option(
    "--input", "input_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default="corpus/berlin",
    help="Path to corpus directory",
)
@click.option(
    "--output", "output_path",
    type=click.Path(path_type=Path),
    default="data/derived/antraege.parquet",
    help="Output parquet path",
)
@click.option("--verbose", is_flag=True, help="Print progress")
@click.option(
    "--boilerplate-threshold",
    type=float,
    default=0.05,
    help="Sentence frequency threshold for boilerplate detection",
)
def ingest(input_dir: Path, output_path: Path, verbose: bool, boilerplate_threshold: float):
    """Ingest corpus into canonical parquet dataset."""
    from spdbe.pipeline import run_pipeline

    df = run_pipeline(
        md_dir=input_dir,
        output_path=output_path,
        boilerplate_threshold=boilerplate_threshold,
        verbose=verbose,
    )
    click.echo(f"Done: {len(df)} documents → {output_path}")


@main.command()
@click.option(
    "--parquet", "parquet_path",
    type=click.Path(exists=True, path_type=Path),
    default="data/derived/antraege.parquet",
    help="Parquet file to analyze",
)
def qc(parquet_path: Path):
    """Print quality control report for the corpus."""
    import pandas as pd

    df = pd.read_parquet(parquet_path)

    click.echo(f"Total documents: {len(df)}")
    click.echo(f"Date parse rate: {df['date_parse_ok'].mean():.1%}")
    click.echo(f"Missing text: {df['missing_text'].sum()}")
    click.echo(f"Tag suspect broad: {df['tag_suspect_broad'].sum()}")
    click.echo(f"Conversion artifacts: {df['conversion_artifacts_hint'].sum()}")
    click.echo(f"Avg word count: {df['word_count'].mean():.0f}")
    click.echo(f"Median word count: {df['word_count'].median():.0f}")
    click.echo()

    # Year distribution
    click.echo("Year distribution:")
    year_counts = df.groupby("year").size().sort_index()
    for year, count in year_counts.items():
        click.echo(f"  {year}: {count}")

    click.echo()

    # Submitter type distribution
    click.echo("Submitter types:")
    type_counts = df.groupby("submitter_type").size().sort_values(ascending=False)
    for stype, count in type_counts.items():
        click.echo(f"  {stype}: {count}")

    click.echo()

    # Status distribution
    click.echo("Status distribution:")
    status_counts = df.groupby("status_raw").size().sort_values(ascending=False)
    for status, count in status_counts.items():
        click.echo(f"  {status}: {count}")


try:
    from spdbe.haystack.cli import haystack
    main.add_command(haystack)
except ImportError:
    pass  # haystack optional deps not installed


if __name__ == "__main__":
    main()
