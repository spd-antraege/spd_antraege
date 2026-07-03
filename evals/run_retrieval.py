"""Run retrieval quality evals for SPD Antraege search.

This eval scores retrieval only. It does not call answer generation.

Usage:
    python -m evals.run_retrieval
    python -m evals.run_retrieval --backend api --base-url https://spd-antraege.de
    python -m evals.run_retrieval --backend local-haystack --es-host http://localhost:9200
    python -m evals.run_retrieval --backend local-federated --data-dir data --modes bm25
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, parse, request

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_CASES_PATH = ROOT / "evals" / "retrieval_questions.yaml"
DEFAULT_REPORT_DIR = ROOT / "evals" / "reports"
DEFAULT_MODES = ("bm25", "vector", "hybrid", "hybrid_with_filters")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open() as f:
        data = yaml.safe_load(f)

    cases = data.get("cases", [])
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"No cases found in {path}")
    for case in cases:
        if "id" not in case or "query" not in case:
            raise ValueError(f"Invalid case without id/query: {case}")
    return cases


def _filters_for_mode(case: dict[str, Any], mode: str) -> dict[str, Any]:
    if mode != "hybrid_with_filters":
        return {}
    return dict(case.get("filters") or {})


def _api_search(
    case: dict[str, Any],
    mode: str,
    top_k: int,
    base_url: str,
    timeout: float,
) -> list[dict[str, Any]]:
    actual_mode = "hybrid" if mode == "hybrid_with_filters" else mode
    filters = _filters_for_mode(case, mode)
    params: dict[str, Any] = {
        "q": case["query"],
        "top_k": top_k,
        "mode": actual_mode,
    }

    for key in ("landesverband", "year_min", "year_max"):
        if key in filters and filters[key] is not None:
            params[key] = filters[key]

    url = f"{base_url.rstrip('/')}/api/search?{parse.urlencode(params)}"
    req = request.Request(url, headers={"accept": "application/json"})
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:300]}") from exc


def _local_haystack_search(
    case: dict[str, Any],
    mode: str,
    top_k: int,
    es_host: str,
    index_name: str,
) -> list[dict[str, Any]]:
    from spdbe.haystack.pipelines.search import run_search

    actual_mode = "hybrid" if mode == "hybrid_with_filters" else mode
    filters = _filters_for_mode(case, mode)
    return run_search(
        query=case["query"],
        es_host=es_host,
        index_name=index_name,
        top_k=top_k,
        landesverband=filters.get("landesverband"),
        year_min=filters.get("year_min"),
        year_max=filters.get("year_max"),
        submitter_type=filters.get("submitter_type"),
        mode=actual_mode,
    )


def _local_federated_search(
    case: dict[str, Any],
    mode: str,
    top_k: int,
    data_dir: Path,
) -> list[dict[str, Any]]:
    from spdbe.search import FederatedSearch

    if mode != "bm25":
        raise RuntimeError(
            "local-federated is BM25-only for offline evals. "
            "Use --backend api or --backend local-haystack for vector and hybrid modes."
        )

    actual_mode = "hybrid" if mode == "hybrid_with_filters" else mode
    filters = _filters_for_mode(case, mode)
    search_filters = {
        key: filters[key]
        for key in ("year_min", "year_max", "submitter_type")
        if key in filters and filters[key] is not None
    }
    state = filters.get("landesverband") or "all"
    fs = _local_federated_search._cache.setdefault(str(data_dir), FederatedSearch(data_dir))
    return fs.search(
        case["query"],
        states=state,
        top_k=top_k,
        filters=search_filters or None,
        mode=actual_mode,
    )


_local_federated_search._cache = {}  # type: ignore[attr-defined]


def run_search(
    case: dict[str, Any],
    mode: str,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    if args.backend == "api":
        return _api_search(case, mode, args.top_k, args.base_url, args.timeout)
    if args.backend == "local-haystack":
        return _local_haystack_search(case, mode, args.top_k, args.es_host, args.index)
    if args.backend == "local-federated":
        return _local_federated_search(case, mode, args.top_k, Path(args.data_dir))
    raise ValueError(f"Unknown backend: {args.backend}")


def dedupe_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped = []
    for result in results:
        key = _norm(result.get("kuerzel") or result.get("doc_id"))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def is_relevant(result: dict[str, Any], case: dict[str, Any]) -> bool:
    if case.get("should_find", True) is False:
        return False

    expected = case.get("expected") or {}
    result_kuerzel = _norm(result.get("kuerzel"))
    expected_kuerzel = {_norm(k) for k in expected.get("kuerzel_any", [])}
    if result_kuerzel and result_kuerzel in expected_kuerzel:
        return True

    if expected.get("landesverband") and _norm(result.get("landesverband")) != _norm(expected["landesverband"]):
        return False

    if "year" in expected and expected["year"] is not None:
        if result.get("year") != expected["year"]:
            return False

    if expected.get("status_contains"):
        if _norm(expected["status_contains"]) not in _norm(result.get("status")):
            return False

    terms = [_norm(t) for t in expected.get("terms_any", []) if _norm(t)]
    if terms:
        text = _norm(" ".join([
            str(result.get("kuerzel", "")),
            str(result.get("title", "")),
            str(result.get("snippet", "")),
        ]))
        return any(term in text for term in terms)

    return False


def score_case(case: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    deduped = dedupe_results(results)
    relevant_ranks = [
        rank
        for rank, result in enumerate(deduped, start=1)
        if is_relevant(result, case)
    ]
    first_rank = relevant_ranks[0] if relevant_ranks else None
    top_results = deduped[:10]
    irrelevant_hits = sum(1 for result in top_results if not is_relevant(result, case))

    return {
        "result_count": len(deduped),
        "top_kuerzel": [r.get("kuerzel") for r in top_results[:5]],
        "first_relevant_rank": first_rank,
        "relevant_ranks": relevant_ranks,
        "recall_at_5": bool(first_rank and first_rank <= 5),
        "recall_at_10": bool(first_rank and first_rank <= 10),
        "mrr": (1.0 / first_rank) if first_rank else 0.0,
        "irrelevant_hits_at_10": irrelevant_hits,
        "hits_evaluated": len(top_results),
        "no_results": len(deduped) == 0,
        "negative_case": case.get("should_find", True) is False,
        "negative_false_positive": case.get("should_find", True) is False and len(deduped) > 0,
    }


def run_eval(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_cases(Path(args.cases))
    modes = [mode.strip() for mode in args.modes.split(",") if mode.strip()]
    invalid = set(modes) - set(DEFAULT_MODES)
    if invalid:
        raise ValueError(f"Invalid modes: {', '.join(sorted(invalid))}")

    started = datetime.now(UTC)
    case_results: list[dict[str, Any]] = []

    for case in cases:
        mode_results: dict[str, Any] = {}
        for mode in modes:
            t0 = time.monotonic()
            try:
                results = run_search(case, mode, args)
                score = score_case(case, results)
                score["latency_ms"] = round((time.monotonic() - t0) * 1000)
                mode_results[mode] = score
            except Exception as exc:
                mode_results[mode] = {
                    "error": str(exc),
                    "latency_ms": round((time.monotonic() - t0) * 1000),
                    "negative_case": case.get("should_find", True) is False,
                }
        case_results.append({
            "id": case["id"],
            "query": case["query"],
            "query_type": case.get("query_type", "unknown"),
            "should_find": case.get("should_find", True),
            "filters": case.get("filters") or {},
            "expected": case.get("expected") or {},
            "modes": mode_results,
        })

    return {
        "generated_at": started.isoformat(),
        "backend": args.backend,
        "base_url": args.base_url if args.backend == "api" else None,
        "es_host": args.es_host if args.backend == "local-haystack" else None,
        "index": args.index if args.backend == "local-haystack" else None,
        "data_dir": args.data_dir if args.backend == "local-federated" else None,
        "top_k": args.top_k,
        "modes": modes,
        "case_count": len(cases),
        "summary": summarize(case_results, modes),
        "cases": case_results,
    }


def _rate(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def summarize(case_results: list[dict[str, Any]], modes: list[str]) -> dict[str, Any]:
    summary = {}
    for mode in modes:
        stats = defaultdict(float)
        positive_cases = 0
        negative_cases = 0
        mrr_total = 0.0

        for case in case_results:
            result = case["modes"][mode]
            stats["cases"] += 1
            if result.get("error"):
                stats["failures"] += 1
                if not case.get("should_find", True):
                    negative_cases += 1
                else:
                    positive_cases += 1
                continue

            if result.get("negative_case"):
                negative_cases += 1
                if result.get("negative_false_positive"):
                    stats["negative_false_positives"] += 1
            else:
                positive_cases += 1
                stats["recall_at_5_hits"] += int(result["recall_at_5"])
                stats["recall_at_10_hits"] += int(result["recall_at_10"])
                mrr_total += result["mrr"]

            stats["no_results"] += int(result["no_results"])
            stats["irrelevant_hits"] += result["irrelevant_hits_at_10"]
            stats["hits_evaluated"] += result["hits_evaluated"]

        summary[mode] = {
            "cases": int(stats["cases"]),
            "positive_cases": positive_cases,
            "negative_cases": negative_cases,
            "failure_rate": _rate(stats["failures"], stats["cases"]),
            "recall_at_5": _rate(stats["recall_at_5_hits"], positive_cases),
            "recall_at_10": _rate(stats["recall_at_10_hits"], positive_cases),
            "mrr": _rate(mrr_total, positive_cases),
            "irrelevant_hit_rate": _rate(stats["irrelevant_hits"], stats["hits_evaluated"]),
            "no_result_rate": _rate(stats["no_results"], stats["cases"]),
            "negative_false_positive_rate": _rate(stats["negative_false_positives"], negative_cases),
        }
    return summary


def _pct(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    return f"{value:.1%}"


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Retrieval Eval Report",
        "",
        f"- Generated at: `{result['generated_at']}`",
        f"- Backend: `{result['backend']}`",
        f"- Cases: `{result['case_count']}`",
        f"- Top K: `{result['top_k']}`",
        "",
        "## Summary",
        "",
        "| Mode | Failure | Recall@5 | Recall@10 | MRR | Irrelevant hits | No results | Negative false positives |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for mode, metrics in result["summary"].items():
        lines.append(
            "| {mode} | {failure} | {r5} | {r10} | {mrr} | {irr} | {nores} | {neg} |".format(
                mode=mode,
                failure=_pct(metrics["failure_rate"]),
                r5=_pct(metrics["recall_at_5"]),
                r10=_pct(metrics["recall_at_10"]),
                mrr=f"{metrics['mrr']:.3f}" if metrics["mrr"] is not None else "n/a",
                irr=_pct(metrics["irrelevant_hit_rate"]),
                nores=_pct(metrics["no_result_rate"]),
                neg=_pct(metrics["negative_false_positive_rate"]),
            )
        )

    lines.extend(["", "## Misses", ""])
    miss_count = 0
    for case in result["cases"]:
        if not case.get("should_find", True):
            continue
        for mode, mode_result in case["modes"].items():
            if mode_result.get("error"):
                lines.append(f"- `{case['id']}` in `{mode}` failed: {mode_result['error']}")
                miss_count += 1
            elif not mode_result.get("recall_at_10"):
                top = ", ".join(str(k) for k in mode_result.get("top_kuerzel", []) if k)
                lines.append(f"- `{case['id']}` in `{mode}` missed Recall@10. Top: {top or 'none'}")
                miss_count += 1
    if miss_count == 0:
        lines.append("- None")

    lines.extend(["", "## Negative Case Violations", ""])
    neg_count = 0
    for case in result["cases"]:
        if case.get("should_find", True):
            continue
        for mode, mode_result in case["modes"].items():
            if mode_result.get("error"):
                continue
            if mode_result.get("negative_false_positive"):
                top = ", ".join(str(k) for k in mode_result.get("top_kuerzel", []) if k)
                lines.append(f"- `{case['id']}` in `{mode}` returned results. Top: {top or 'none'}")
                neg_count += 1
    if neg_count == 0:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def write_reports(result: dict[str, Any], report_dir: Path) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    json_path = report_dir / f"{date}-retrieval.json"
    md_path = report_dir / f"{date}-retrieval.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    md_path.write_text(render_markdown(result))
    return json_path, md_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH))
    parser.add_argument("--backend", choices=["api", "local-haystack", "local-federated"], default="api")
    parser.add_argument("--base-url", default="https://spd-antraege.de")
    parser.add_argument("--es-host", default="http://localhost:9200")
    parser.add_argument("--index", default="spd-motions")
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--modes", default=",".join(DEFAULT_MODES))
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--no-report", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    result = run_eval(args)

    print(render_markdown(result))
    if not args.no_report:
        json_path, md_path = write_reports(result, Path(args.report_dir))
        print(f"Wrote JSON report: {json_path}")
        print(f"Wrote Markdown report: {md_path}")

    failures = sum(
        1
        for case in result["cases"]
        for mode_result in case["modes"].values()
        if mode_result.get("error")
    )
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
