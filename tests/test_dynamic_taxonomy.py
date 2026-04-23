"""
Phase 8: Dynamic Taxonomy Engine tests.

Unit tests run without any external services.
"""

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from conftest import REPO_ROOT

# Ensure src/ is importable (conftest already does this via sys.path)
from spdbe.taxonomy_engine import (
    TaxonomyProposal,
    UnmatchedAccumulator,
    approve_proposal,
    generate_proposals,
    scan_unmatched_signals,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def accumulator():
    """In-memory accumulator (no DB)."""
    return UnmatchedAccumulator(use_db=False)


@pytest.fixture
def sample_taxonomy(tmp_path):
    """Minimal taxonomy YAML for testing."""
    tax = {
        "version": "1.0",
        "domains": {
            "wohnen": {
                "label_de": "Wohnen & Stadtentwicklung",
                "subtopics": {
                    "mietenpolitik": {"label_de": "Mietenpolitik"},
                    "sozialer_wohnungsbau": {"label_de": "Sozialer Wohnungsbau"},
                },
            },
            "bildung": {
                "label_de": "Bildung",
                "subtopics": {
                    "schulpolitik": {"label_de": "Schulpolitik"},
                },
            },
        },
    }
    path = tmp_path / "topics.yaml"
    with open(path, "w") as f:
        yaml.dump(tax, f, allow_unicode=True, default_flow_style=False)
    return path


# ---------------------------------------------------------------------------
# Accumulation tests
# ---------------------------------------------------------------------------

class TestUnmatchedAccumulation:
    def test_add_and_count(self, accumulator):
        """Adding signals increments counts correctly."""
        accumulator.add("klimageld", "doc-001")
        accumulator.add("klimageld", "doc-002")
        accumulator.add("klimageld", "doc-003")
        accumulator.add("fahrradstraßen", "doc-001")

        assert accumulator.count("klimageld") == 3
        assert accumulator.count("fahrradstraßen") == 1
        assert accumulator.count("nonexistent") == 0

    def test_deduplication(self, accumulator):
        """Same doc_id for same signal is not double-counted."""
        accumulator.add("klimageld", "doc-001")
        accumulator.add("klimageld", "doc-001")

        assert accumulator.count("klimageld") == 1

    def test_case_normalization(self, accumulator):
        """Signals are normalized to lowercase."""
        accumulator.add("Klimageld", "doc-001")
        accumulator.add("klimageld", "doc-002")

        assert accumulator.count("klimageld") == 2

    def test_empty_signal_ignored(self, accumulator):
        """Empty or whitespace-only signals are ignored."""
        accumulator.add("", "doc-001")
        accumulator.add("  ", "doc-002")

        assert accumulator.get_proposals(threshold=1) == []


class TestShouldProposeThreshold:
    def test_below_threshold(self, accumulator):
        """Signal below threshold should not be proposed."""
        for i in range(4):
            accumulator.add("klimageld", f"doc-{i:03d}")

        assert not accumulator.should_propose("klimageld", threshold=5)

    def test_at_threshold(self, accumulator):
        """Signal exactly at threshold should be proposed."""
        for i in range(5):
            accumulator.add("klimageld", f"doc-{i:03d}")

        assert accumulator.should_propose("klimageld", threshold=5)

    def test_above_threshold(self, accumulator):
        """Signal above threshold should be proposed."""
        for i in range(10):
            accumulator.add("klimageld", f"doc-{i:03d}")

        assert accumulator.should_propose("klimageld", threshold=5)

    def test_get_proposals_filters(self, accumulator):
        """get_proposals returns only signals above threshold."""
        for i in range(6):
            accumulator.add("klimageld", f"doc-{i:03d}")
        for i in range(3):
            accumulator.add("fahrradstraßen", f"doc-{i:03d}")

        proposals = accumulator.get_proposals(threshold=5)
        signals = [p["signal"] for p in proposals]

        assert "klimageld" in signals
        assert "fahrradstraßen" not in signals


# ---------------------------------------------------------------------------
# Proposal tests
# ---------------------------------------------------------------------------

class TestTaxonomyProposal:
    def test_rocketchat_message_contains_topic(self):
        """Rocket.Chat message contains the topic name and count."""
        proposal = TaxonomyProposal(
            topic_id="klimageld",
            domain_id="umwelt",
            label_de="Klimageld",
            evidence_doc_ids=["doc-001", "doc-002", "doc-003"],
        )
        msg = proposal.to_rocketchat_message()

        assert "Klimageld" in msg
        assert "klimageld" in msg
        assert "3 Dokumente" in msg
        assert "doc-001" in msg

    def test_rocketchat_message_truncates_long_list(self):
        """More than 5 doc_ids are truncated with a '(+N weitere)' suffix."""
        ids = [f"doc-{i:03d}" for i in range(8)]
        proposal = TaxonomyProposal(
            topic_id="test",
            domain_id="test",
            label_de="Test",
            evidence_doc_ids=ids,
        )
        msg = proposal.to_rocketchat_message()

        assert "(+3 weitere)" in msg


# ---------------------------------------------------------------------------
# Scan & generation tests
# ---------------------------------------------------------------------------

class TestScanUnmatchedSignals:
    def test_scan_intelligence_dir(self, tmp_path):
        """scan_unmatched_signals reads signals from JSON files."""
        # Create fake intelligence files
        for i in range(6):
            doc = {
                "doc_id": f"doc-{i:03d}",
                "connections": {
                    "unmatched_signals": ["klimageld", "fahrradstraßen"],
                },
            }
            (tmp_path / f"doc-{i:03d}.json").write_text(json.dumps(doc))

        acc = scan_unmatched_signals(tmp_path)

        assert acc.count("klimageld") == 6
        assert acc.count("fahrradstraßen") == 6


class TestGenerateProposals:
    def test_proposals_skip_existing(self, accumulator, sample_taxonomy):
        """Proposals are not generated for topics already in taxonomy."""
        # "mietenpolitik" is already in the taxonomy
        for i in range(6):
            accumulator.add("mietenpolitik", f"doc-{i:03d}")

        proposals = generate_proposals(accumulator, sample_taxonomy, threshold=5)
        topic_ids = [p.topic_id for p in proposals]

        assert "mietenpolitik" not in topic_ids

    def test_proposals_created_for_new(self, accumulator, sample_taxonomy):
        """Proposals are generated for signals not in taxonomy."""
        for i in range(6):
            accumulator.add("klimageld", f"doc-{i:03d}")

        proposals = generate_proposals(accumulator, sample_taxonomy, threshold=5)
        topic_ids = [p.topic_id for p in proposals]

        assert "klimageld" in topic_ids
        assert proposals[0].label_de == "Klimageld"


class TestApproveProposal:
    def test_approval_modifies_taxonomy(self, sample_taxonomy):
        """Approving a proposal adds the topic to the YAML file."""
        proposal = TaxonomyProposal(
            topic_id="klimageld",
            domain_id="wohnen",
            label_de="Klimageld",
            evidence_doc_ids=["doc-001", "doc-002"],
        )

        doc_ids = approve_proposal(proposal, sample_taxonomy)

        # Verify file was updated
        with open(sample_taxonomy) as f:
            tax = yaml.safe_load(f)

        subtopics = tax["domains"]["wohnen"]["subtopics"]
        assert "klimageld" in subtopics
        assert subtopics["klimageld"]["label_de"] == "Klimageld"

        # Returns doc_ids for re-extraction
        assert doc_ids == ["doc-001", "doc-002"]

        # Proposal status updated
        assert proposal.status == "approved"

    def test_approval_creates_domain_if_missing(self, sample_taxonomy):
        """Approving into a non-existent domain creates it."""
        proposal = TaxonomyProposal(
            topic_id="windenergie",
            domain_id="energie",
            label_de="Windenergie",
            evidence_doc_ids=["doc-010"],
        )

        approve_proposal(proposal, sample_taxonomy)

        with open(sample_taxonomy) as f:
            tax = yaml.safe_load(f)

        assert "energie" in tax["domains"]
        assert "windenergie" in tax["domains"]["energie"]["subtopics"]
