"""Select 20 diverse Anträge from sample_300 as eval fixtures.

Stratified by: year decade, submitter_type, status, doc_type.
Prefers longer texts (more extraction surface).
"""

import json
from pathlib import Path

SAMPLE_PATH = Path("data/taxonomy/sample_300.json")
OUTPUT_PATH = Path("evals/fixtures/eval_docs.json")

# Target: 20 docs, stratified
TARGET = 20


def select_diverse(docs: list[dict], n: int) -> list[dict]:
    """Greedy diverse selection: pick docs that maximize coverage."""
    # Score each doc by text length (prefer longer = more to extract)
    docs = sorted(docs, key=lambda d: len(d.get("text_clean", "")), reverse=True)

    selected = []
    seen_years = set()
    seen_submitters = set()
    seen_statuses = set()
    seen_topics = set()

    def diversity_score(doc):
        score = 0
        y = doc.get("year")
        if y and y not in seen_years:
            score += 3
        st = doc.get("submitter_type", "")
        if st and st not in seen_submitters:
            score += 3
        status = doc.get("status_raw", "")
        if status and status not in seen_statuses:
            score += 2
        dt = doc.get("doc_type", "")
        if dt and dt not in seen_topics:
            score += 2
        # Bonus for text length
        score += min(len(doc.get("text_clean", "")) / 1000, 3)
        return score

    while len(selected) < n and docs:
        # Score remaining docs
        docs.sort(key=diversity_score, reverse=True)
        pick = docs.pop(0)
        selected.append(pick)

        # Update seen sets
        if pick.get("year"):
            seen_years.add(pick["year"])
        if pick.get("submitter_type"):
            seen_submitters.add(pick["submitter_type"])
        if pick.get("status_raw"):
            seen_statuses.add(pick["status_raw"])
        if pick.get("doc_type"):
            seen_topics.add(pick["doc_type"])

    return selected


def main():
    with open(SAMPLE_PATH) as f:
        all_docs = json.load(f)

    # Filter: need text_clean and kuerzel
    valid = [d for d in all_docs if d.get("text_clean") and d.get("kuerzel")]
    print(f"Valid docs: {len(valid)}/{len(all_docs)}")

    selected = select_diverse(valid, TARGET)

    # Strip to eval-relevant fields only
    eval_docs = []
    for doc in selected:
        eval_docs.append({
            "id": doc["id"],
            "kuerzel": doc["kuerzel"],
            "title": doc.get("title", ""),
            "year": doc.get("year"),
            "submitter_type": doc.get("submitter_type", ""),
            "submitter_raw": doc.get("submitter_raw", ""),
            "status_raw": doc.get("status_raw", ""),
            "doc_type": doc.get("doc_type", ""),
            "text_clean": doc["text_clean"],
        })

    # Summary
    from collections import Counter
    print(f"\nSelected {len(eval_docs)} eval docs:")
    print(f"  Years: {sorted(set(d['year'] for d in eval_docs if d['year']))}")
    print(f"  Submitters: {dict(Counter(d['submitter_type'] for d in eval_docs))}")
    print(f"  Statuses: {dict(Counter(d['status_raw'] for d in eval_docs))}")
    print(f"  DocTypes: {dict(Counter(d['doc_type'] for d in eval_docs))}")
    print(f"  Avg text length: {sum(len(d['text_clean']) for d in eval_docs) // len(eval_docs)} chars")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(eval_docs, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
