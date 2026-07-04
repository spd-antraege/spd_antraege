"""CLI commands for Haystack pipelines."""

from __future__ import annotations

from pathlib import Path

import click

from spdbe.haystack.document_store import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_ES_HOST,
    DEFAULT_INDEX,
)


@click.group()
def haystack():
    """Haystack pipeline commands."""
    pass


@haystack.command()
@click.option("--input", "input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path), default="corpus/berlin")
@click.option("--es-host", default=DEFAULT_ES_HOST)
@click.option("--index", "index_name", default=DEFAULT_INDEX)
@click.option("--model", "embedding_model", default=DEFAULT_EMBEDDING_MODEL)
@click.option("--boilerplate-index", "bp_path", type=click.Path(), default=None)
@click.option("--landesverband", default="berlin")
@click.option("--verbose", is_flag=True)
def index(input_dir, es_host, index_name, embedding_model, bp_path, landesverband, verbose):
    """Index corpus into Elasticsearch."""
    from spdbe.haystack.pipelines.indexing import run_indexing

    result = run_indexing(
        md_dir=input_dir,
        es_host=es_host,
        index_name=index_name,
        embedding_model=embedding_model,
        boilerplate_index_path=bp_path,
        landesverband=landesverband,
        verbose=verbose,
    )
    written = result.get("writer", {}).get("documents_written", 0)
    click.echo(f"Indexed {written} documents into {index_name}")


@haystack.command()
@click.argument("query")
@click.option("--es-host", default=DEFAULT_ES_HOST)
@click.option("--index", "index_name", default=DEFAULT_INDEX)
@click.option("--top-k", type=int, default=10)
@click.option("--landesverband", default=None)
@click.option("--year-min", type=int, default=None)
@click.option("--year-max", type=int, default=None)
@click.option("--mode", type=click.Choice(["hybrid", "bm25", "vector"]), default="hybrid")
def search(query, es_host, index_name, top_k, landesverband, year_min, year_max, mode):
    """Search the corpus."""
    from spdbe.haystack.pipelines.search import run_search

    results = run_search(
        query=query,
        es_host=es_host,
        index_name=index_name,
        top_k=top_k,
        landesverband=landesverband,
        year_min=year_min,
        year_max=year_max,
        mode=mode,
    )

    if not results:
        click.echo("No results found.")
        return

    for r in results:
        year = r.get("year", "?")
        click.echo(f"  {r['score']:.4f}  [{r.get('landesverband', '?')}]  {r['kuerzel']:30s}  ({year})  {r['title'][:50]}")


@haystack.command("index-parquet")
@click.argument("parquet_path", type=click.Path(exists=True, path_type=Path))
@click.option("--es-host", default=DEFAULT_ES_HOST)
@click.option("--index", "index_name", default=DEFAULT_INDEX)
@click.option("--model", "embedding_model", default=DEFAULT_EMBEDDING_MODEL)
@click.option("--verbose", is_flag=True)
def index_parquet(parquet_path, es_host, index_name, embedding_model, verbose):
    """Index pre-normalized parquet data into Elasticsearch."""
    from spdbe.haystack.pipelines.indexing import run_indexing_from_parquet

    result = run_indexing_from_parquet(
        parquet_path=parquet_path,
        es_host=es_host,
        index_name=index_name,
        embedding_model=embedding_model,
        verbose=verbose,
    )
    written = result.get("writer", {}).get("documents_written", 0)
    click.echo(f"Indexed {written} documents into {index_name}")


@haystack.command("index-derived")
@click.option(
    "--input",
    "derived_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default="data/derived",
    help="Directory containing */antraege.parquet files",
)
@click.option("--es-host", default=DEFAULT_ES_HOST)
@click.option("--index", "index_name", default=DEFAULT_INDEX)
@click.option("--model", "embedding_model", default=DEFAULT_EMBEDDING_MODEL)
@click.option("--verbose", is_flag=True)
def index_derived(derived_dir, es_host, index_name, embedding_model, verbose):
    """Index all derived state parquet files into Elasticsearch."""
    from spdbe.haystack.pipelines.indexing import run_indexing_from_derived_parquets

    result = run_indexing_from_derived_parquets(
        derived_dir=derived_dir,
        es_host=es_host,
        index_name=index_name,
        embedding_model=embedding_model,
        verbose=verbose,
    )
    loader = result.get("loader", {})
    written = result.get("writer", {}).get("documents_written", 0)
    click.echo(
        f"Indexed {written} documents into {index_name} "
        f"from {loader.get('parquet_files', 0)} parquet files"
    )


@haystack.command()
@click.argument("query")
@click.option("--es-host", default=DEFAULT_ES_HOST)
@click.option("--index", "index_name", default=DEFAULT_INDEX)
@click.option("--llm-model", default="claude-sonnet-4-5-20250929")
@click.option("--top-k", type=int, default=5)
@click.option("--landesverband", default=None)
def rag(query, es_host, index_name, llm_model, top_k, landesverband):
    """Ask a question (RAG: retrieval + generation)."""
    from spdbe.haystack.pipelines.rag import run_rag

    result = run_rag(
        query=query,
        es_host=es_host,
        index_name=index_name,
        llm_model=llm_model,
        top_k=top_k,
        landesverband=landesverband,
    )

    click.echo(f"\nFrage: {result['query']}\n")
    click.echo(result["answer"])
    click.echo(f"\nQuellen ({len(result['sources'])}):")
    for s in result["sources"]:
        click.echo(f"  {s['kuerzel']} ({s.get('year', '?')}) — {s['title'][:60]}")


@haystack.command("build-boilerplate")
@click.option("--input", "input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path), default="corpus/berlin")
@click.option("--output", "output_path", type=click.Path(path_type=Path), default="data/derived/boilerplate_index.json")
@click.option("--threshold", type=float, default=0.05)
def build_boilerplate(input_dir, output_path, threshold):
    """Pre-compute boilerplate index for a corpus."""
    from spdbe.haystack.components.motion_normalizer import save_boilerplate_index

    count = save_boilerplate_index(input_dir, output_path, threshold=threshold)
    click.echo(f"Saved {count} boilerplate phrases to {output_path}")


@haystack.command("export-yaml")
@click.option("--pipeline", "pipeline_name", type=click.Choice(["indexing", "search", "rag", "extraction"]), required=True)
@click.option("--output", "output_path", type=click.Path(path_type=Path), default=None)
@click.option("--es-host", default=DEFAULT_ES_HOST)
@click.option("--index", "index_name", default=DEFAULT_INDEX)
def export_yaml(pipeline_name, output_path, es_host, index_name):
    """Export a pipeline as YAML (for deepset showcase)."""
    if pipeline_name == "indexing":
        from spdbe.haystack.pipelines.indexing import build_indexing_pipeline
        pipe = build_indexing_pipeline(es_host=es_host, index_name=index_name)
    elif pipeline_name == "search":
        from spdbe.haystack.pipelines.search import build_search_pipeline
        pipe = build_search_pipeline(es_host=es_host, index_name=index_name)
    elif pipeline_name == "rag":
        from spdbe.haystack.pipelines.rag import build_rag_pipeline
        pipe = build_rag_pipeline(es_host=es_host, index_name=index_name)
    elif pipeline_name == "extraction":
        from spdbe.haystack.pipelines.extraction import build_extraction_pipeline
        pipe = build_extraction_pipeline(es_host=es_host, index_name=index_name)

    yaml_str = pipe.dumps()

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(yaml_str)
        click.echo(f"Exported {pipeline_name} pipeline to {output_path}")
    else:
        click.echo(yaml_str)
