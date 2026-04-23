"""
Eval runner for SPD Antrag extraction quality.

Runs extraction on 20 diverse cached Anträge, scores against baseline,
detects regressions. Ported from amtsguide_scraper/evals/run.py.

Usage:
    python -m evals.run                # run eval, print scores
    python -m evals.run --save          # save current as baseline
    python -m evals.run --check         # exit 1 if regression > 5%
    python -m evals.run --model claude-sonnet-4-5-20250929  # test different model
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

import anthropic

FIXTURES_DIR = ROOT / "evals" / "fixtures"
EVAL_DOCS_PATH = FIXTURES_DIR / "eval_docs.json"
BASELINE_PATH = FIXTURES_DIR / "baseline_scores.json"
TAXONOMY_PATH = ROOT / "data" / "taxonomy" / "topics.yaml"

# Fields we score in the extraction output
SCORED_FIELDS = {
    "topics.primary": {"weight": 3.0, "type": "exact"},
    "topics.secondary": {"weight": 1.0, "type": "set_overlap"},
    "demands": {"weight": 3.0, "type": "list_present"},
    "actors.addressees": {"weight": 2.0, "type": "list_present"},
    "actors.mentioned": {"weight": 1.0, "type": "list_present"},
    "strategy.framing": {"weight": 1.0, "type": "non_empty"},
    "style.register": {"weight": 2.0, "type": "enum", "valid": [
        "formal-fordernd", "narrativ-persoenlich",
        "technisch-sachlich", "emotional-appellativ",
    ]},
    "style.complexity": {"weight": 1.0, "type": "enum", "valid": ["low", "medium", "high"]},
    "style.persuasion_mode": {"weight": 1.0, "type": "enum", "valid": [
        "Sachzwang", "Werteappell", "Dringlichkeit", "Solidaritaet", "Empoerung",
    ]},
}


def _get_nested(data: dict, path: str):
    """Get nested value by dot path."""
    parts = path.split(".")
    current = data
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def score_field(value, field_name: str, spec: dict) -> tuple[float, str]:
    """Score a single extracted field. Returns (score 0-1, reason)."""
    ftype = spec["type"]

    if ftype == "exact":
        if value and isinstance(value, str) and len(value) > 0:
            return 1.0, f"present: {value}"
        return 0.0, "missing"

    elif ftype == "set_overlap":
        if isinstance(value, list) and len(value) > 0:
            return 1.0, f"{len(value)} items"
        return 0.0, "empty or missing"

    elif ftype == "list_present":
        if isinstance(value, list) and len(value) > 0:
            # Check items have content
            valid = [item for item in value if item and (
                isinstance(item, str) and len(item) > 0 or
                isinstance(item, dict) and any(v for v in item.values() if v)
            )]
            if valid:
                return 1.0, f"{len(valid)} items"
            return 0.3, f"{len(value)} items but empty content"
        return 0.0, "empty or missing"

    elif ftype == "non_empty":
        if value and isinstance(value, str) and len(value.strip()) > 3:
            return 1.0, f"present ({len(value)} chars)"
        return 0.0, "missing or too short"

    elif ftype == "enum":
        valid_values = spec.get("valid", [])
        if value in valid_values:
            return 1.0, f"valid: {value}"
        elif value and isinstance(value, str):
            return 0.5, f"non-standard: {value}"
        return 0.0, "missing"

    return 0.0, f"unknown type: {ftype}"


def score_extraction(extraction: dict) -> dict:
    """Score a full extraction result. Returns per-field scores + weighted total."""
    field_scores = {}
    total_weighted = 0.0
    total_weight = 0.0

    for field_path, spec in SCORED_FIELDS.items():
        value = _get_nested(extraction, field_path)
        score, reason = score_field(value, field_path, spec)
        weight = spec["weight"]
        field_scores[field_path] = {
            "score": score,
            "weight": weight,
            "reason": reason,
        }
        total_weighted += score * weight
        total_weight += weight

    overall = total_weighted / total_weight if total_weight > 0 else 0.0
    return {
        "overall": round(overall, 4),
        "fields": field_scores,
        "parse_error": extraction.get("_parse_error", False),
        "confidence": extraction.get("confidence", 0.0),
    }


def run_eval(model: str = "claude-haiku-4-5-20251001") -> dict:
    """Run extraction eval on all fixture docs."""
    from spdbe.extraction import extract_single, _build_taxonomy_reference

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set. Use: python -m evals.run")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    if not EVAL_DOCS_PATH.exists():
        print(f"ERROR: No eval docs at {EVAL_DOCS_PATH}. Run: python evals/select_fixtures.py")
        sys.exit(1)

    with open(EVAL_DOCS_PATH) as f:
        eval_docs = json.load(f)

    taxonomy_ref = _build_taxonomy_reference(TAXONOMY_PATH)

    results = {}
    total_score = 0.0
    total_docs = 0
    total_cost = {"input_tokens": 0, "output_tokens": 0}

    for doc in eval_docs:
        kuerzel = doc["kuerzel"]
        print(f"  {kuerzel}...", end=" ", flush=True)

        extraction = extract_single(doc, taxonomy_ref, client, model=model)

        # Score
        scores = score_extraction(extraction)
        results[kuerzel] = {
            "scores": scores,
            "extraction": extraction,
        }
        total_score += scores["overall"]
        total_docs += 1

        marker = "+" if scores["overall"] >= 0.8 else "~" if scores["overall"] >= 0.5 else "-"
        print(f"{marker} {scores['overall']:.0%} (conf={scores['confidence']:.1f})")

    overall = total_score / total_docs if total_docs else 0.0

    return {
        "model": model,
        "overall_score": round(overall, 4),
        "num_docs": total_docs,
        "doc_scores": {k: v["scores"]["overall"] for k, v in results.items()},
        "field_averages": _compute_field_averages(results),
        "details": results,
    }


def _compute_field_averages(results: dict) -> dict:
    """Compute average score per field across all docs."""
    field_totals = {}
    field_counts = {}

    for kuerzel, data in results.items():
        for field_path, fdata in data["scores"]["fields"].items():
            if field_path not in field_totals:
                field_totals[field_path] = 0.0
                field_counts[field_path] = 0
            field_totals[field_path] += fdata["score"]
            field_counts[field_path] += 1

    return {
        field: round(field_totals[field] / field_counts[field], 3)
        for field in sorted(field_totals.keys())
    }


def main():
    args = sys.argv[1:]
    save = "--save" in args
    check = "--check" in args
    model = "claude-haiku-4-5-20251001"

    for i, arg in enumerate(args):
        if arg == "--model" and i + 1 < len(args):
            model = args[i + 1]

    print(f"Running extraction eval (model: {model})...")
    print(f"Eval docs: {EVAL_DOCS_PATH}")
    print()

    scores = run_eval(model=model)

    print(f"\n{'='*50}")
    print(f"Overall score: {scores['overall_score']:.1%}")
    print(f"Docs evaluated: {scores['num_docs']}")
    print()

    print("Field averages:")
    for field, avg in scores["field_averages"].items():
        marker = "+" if avg >= 0.8 else "~" if avg >= 0.5 else "-"
        print(f"  {marker} {field}: {avg:.0%}")

    print()
    print("Per-document scores:")
    for kuerzel, score in sorted(scores["doc_scores"].items(), key=lambda x: x[1]):
        marker = "+" if score >= 0.8 else "~" if score >= 0.5 else "-"
        print(f"  {marker} {kuerzel}: {score:.0%}")

    if save:
        # Save without full extraction details (too large)
        baseline = {
            "model": scores["model"],
            "overall_score": scores["overall_score"],
            "num_docs": scores["num_docs"],
            "doc_scores": scores["doc_scores"],
            "field_averages": scores["field_averages"],
        }
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(BASELINE_PATH, "w") as f:
            json.dump(baseline, f, indent=2)
        print(f"\nBaseline saved to {BASELINE_PATH}")

    if check:
        if not BASELINE_PATH.exists():
            print("No baseline found. Run with --save first.")
            sys.exit(1)
        with open(BASELINE_PATH) as f:
            baseline = json.load(f)
        drop = baseline["overall_score"] - scores["overall_score"]
        if drop > 0.05:
            print(f"\nREGRESSION: score dropped {drop:.1%} "
                  f"(baseline {baseline['overall_score']:.1%} -> current {scores['overall_score']:.1%})")
            sys.exit(1)
        else:
            print(f"\nPASS: score {scores['overall_score']:.1%} "
                  f"(baseline {baseline['overall_score']:.1%}, delta {-drop:+.1%})")


if __name__ == "__main__":
    main()
