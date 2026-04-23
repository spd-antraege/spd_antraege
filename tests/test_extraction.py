"""
Phase 2b: Document intelligence extraction tests.

Unit tests run without API. Integration tests require ANTHROPIC_API_KEY.
"""

import json

import pytest

from conftest import REPO_ROOT, requires_corpus


INTELLIGENCE_DIR = REPO_ROOT / "data" / "intelligence"

requires_intelligence = pytest.mark.skipif(
    not INTELLIGENCE_DIR.exists() or not list(INTELLIGENCE_DIR.rglob("*.json")),
    reason="data/intelligence/ not found -- run extraction first",
)


# ===========================================================================
# Schema validation (on extracted files)
# ===========================================================================

@requires_intelligence
class TestExtractionSchema:
    def _load_all(self):
        results = []
        for p in INTELLIGENCE_DIR.rglob("*.json"):
            results.append(json.loads(p.read_text()))
        return results

    def test_all_have_doc_id(self):
        """Every extraction has a doc_id."""
        for r in self._load_all():
            assert r.get("doc_id"), f"Missing doc_id: {r.get('kuerzel', '?')}"

    def test_all_have_primary_topic(self):
        """Every extraction has a primary topic."""
        missing = []
        for r in self._load_all():
            if r.get("_parse_error") or r.get("_error"):
                continue
            primary = r.get("topics", {}).get("primary")
            if not primary:
                missing.append(r.get("kuerzel", "?"))
        assert len(missing) == 0, f"{len(missing)} docs without primary topic: {missing[:10]}"

    def test_all_have_demands(self):
        """>=95% of extractions have at least one demand."""
        all_results = [r for r in self._load_all() if not r.get("_parse_error") and not r.get("_error")]
        with_demands = [r for r in all_results if len(r.get("demands", [])) > 0]
        rate = len(with_demands) / len(all_results) if all_results else 0
        assert rate >= 0.95, f"Only {rate:.1%} have demands ({len(with_demands)}/{len(all_results)})"

    def test_style_register_valid(self):
        """Style register is one of the valid options."""
        valid = {"formal-fordernd", "narrativ-persoenlich", "technisch-sachlich", "emotional-appellativ"}
        invalid = []
        for r in self._load_all():
            if r.get("_parse_error") or r.get("_error"):
                continue
            reg = r.get("style", {}).get("register", "")
            if reg and reg not in valid:
                invalid.append((r.get("kuerzel", "?"), reg))
        assert len(invalid) < len(self._load_all()) * 0.05, f"Too many invalid registers: {invalid[:10]}"

    def test_demand_types_valid(self):
        """Demand types are from the allowed set."""
        valid = {"prohibition", "mandate", "funding", "investigation", "position", "resolution"}
        invalid = []
        for r in self._load_all():
            for d in r.get("demands", []):
                if d.get("type") and d["type"] not in valid:
                    invalid.append((r.get("kuerzel", "?"), d["type"]))
        assert len(invalid) < 50, f"Too many invalid demand types: {invalid[:10]}"

    def test_confidence_distribution(self):
        """>=90% of extractions have confidence >= 0.7."""
        all_results = self._load_all()
        high_conf = [r for r in all_results if r.get("confidence", 0) >= 0.7]
        rate = len(high_conf) / len(all_results) if all_results else 0
        assert rate >= 0.90, f"Only {rate:.1%} have confidence >= 0.7"

    def test_topics_from_taxonomy(self):
        """Primary topics exist in the taxonomy."""
        import yaml
        tax_path = REPO_ROOT / "data" / "taxonomy" / "topics.yaml"
        if not tax_path.exists():
            pytest.skip("taxonomy not found")
        with open(tax_path) as f:
            tax = yaml.safe_load(f)
        valid_ids = set()
        for domain_id, domain in tax.get("domains", {}).items():
            valid_ids.add(domain_id)  # domain IDs are also valid
            for topic_id in domain.get("subtopics", {}):
                valid_ids.add(topic_id)

        invalid = []
        for r in self._load_all():
            if r.get("_parse_error") or r.get("_error"):
                continue
            primary = r.get("topics", {}).get("primary", "")
            if primary and primary not in valid_ids:
                invalid.append((r.get("kuerzel", "?"), primary))
        # Allow some drift (LLM might use domain IDs or slight variations)
        assert len(invalid) < len(self._load_all()) * 0.10, \
            f"{len(invalid)} docs with invalid primary topic: {invalid[:10]}"

    def test_no_parse_errors(self):
        """<1% of extractions have parse errors."""
        all_results = self._load_all()
        errors = [r for r in all_results if r.get("_parse_error") or r.get("_error")]
        rate = len(errors) / len(all_results) if all_results else 0
        assert rate < 0.01, f"{rate:.1%} parse errors ({len(errors)}/{len(all_results)})"

    def test_extraction_count_matches_corpus(self):
        """Number of extraction files matches corpus size (±5)."""
        import pandas as pd
        parquet_path = REPO_ROOT / "data" / "derived" / "antraege.parquet"
        if not parquet_path.exists():
            pytest.skip("parquet not found")
        df = pd.read_parquet(parquet_path)
        extractions = list(INTELLIGENCE_DIR.rglob("*.json"))
        diff = abs(len(extractions) - len(df))
        assert diff <= 5, f"Extraction count {len(extractions)} vs corpus {len(df)} (diff={diff})"


# ===========================================================================
# Idempotency
# ===========================================================================

@requires_intelligence
class TestExtractionIdempotency:
    def test_content_hash_present(self):
        """Every extraction stores the content_hash for change detection."""
        for p in list(INTELLIGENCE_DIR.rglob("*.json"))[:100]:
            r = json.loads(p.read_text())
            if r.get("_error"):
                continue
            assert r.get("content_hash"), f"Missing content_hash: {r.get('kuerzel', p.name)}"
