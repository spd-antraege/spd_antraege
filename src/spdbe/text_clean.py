"""Stage C: Text cleaning, markdown stripping, de-boilerplating."""

from __future__ import annotations

import re
from collections import Counter


def strip_markdown(text: str) -> str:
    """Remove markdown syntax, producing plain text."""
    # Remove headers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove bold/italic
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
    # Remove links [text](url)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove images ![alt](url)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    # Remove blockquote markers
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    # Remove horizontal rules
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    # Remove inline code
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove list markers
    text = re.sub(r"^[\s]*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\s]*\d+\.\s+", "", text, flags=re.MULTILINE)
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Default boilerplate phrases (extended at runtime from corpus analysis)
_KNOWN_BOILERPLATE = [
    "Der Landesparteitag möge beschließen",
    "Der Landesparteitag hat beschlossen",
    "Die Antragskommission empfiehlt",
    "Empfehlung der Antragskommission",
]


def build_boilerplate_index(corpus_texts: list[str], threshold: float = 0.05) -> set[str]:
    """Identify sentences that appear in >threshold fraction of documents.

    Returns a set of normalized sentence strings to remove.
    """
    sentence_doc_counts: Counter = Counter()
    n_docs = len(corpus_texts)

    for text in corpus_texts:
        sentences = _split_sentences(text)
        # Count each unique sentence once per document
        unique = set(s.strip().lower() for s in sentences if len(s.strip()) > 20)
        for s in unique:
            sentence_doc_counts[s] += 1

    # Sentences in >threshold of docs are boilerplate
    boilerplate = set()
    for s, count in sentence_doc_counts.items():
        if count / n_docs >= threshold:
            boilerplate.add(s)

    # Add known phrases
    for phrase in _KNOWN_BOILERPLATE:
        boilerplate.add(phrase.strip().lower())

    return boilerplate


def _split_sentences(text: str) -> list[str]:
    """Simple sentence splitting on newlines and periods."""
    # Split on double newlines first (paragraph boundaries)
    paragraphs = re.split(r"\n\n+", text)
    sentences = []
    for para in paragraphs:
        # Split on sentence-ending punctuation followed by space or newline
        parts = re.split(r"(?<=[.!?])\s+", para.strip())
        sentences.extend(p.strip() for p in parts if p.strip())
    return sentences


def deboilerplate(text: str, boilerplate_index: set[str] | None = None) -> str:
    """Remove boilerplate sentences from text.

    If no index provided, uses only the known phrases list.
    """
    if boilerplate_index is None:
        boilerplate_index = set(p.strip().lower() for p in _KNOWN_BOILERPLATE)

    lines = text.split("\n")
    kept = []
    for line in lines:
        stripped = line.strip().lower()
        # Check if the line IS a boilerplate phrase
        is_boilerplate = False
        for bp in boilerplate_index:
            if stripped == bp or (len(bp) > 20 and bp in stripped and len(stripped) < len(bp) * 2):
                is_boilerplate = True
                break
        if not is_boilerplate:
            kept.append(line)

    result = "\n".join(kept)
    # Collapse excessive blank lines
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def compute_boilerplate_share(original: str, cleaned: str) -> float:
    """Fraction of text removed by de-boilerplating."""
    orig_len = len(original.strip())
    if orig_len == 0:
        return 0.0
    clean_len = len(cleaned.strip())
    return max(0.0, min(1.0, 1.0 - clean_len / orig_len))
