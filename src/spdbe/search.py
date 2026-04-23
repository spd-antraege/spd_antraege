"""Phase 4: Hybrid search — BM25 + vector + reciprocal rank fusion."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)
import pandas as pd


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------

class BM25Index:
    """Simple BM25 index over corpus text."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_ids: list[str] = []
        self.doc_lens: np.ndarray | None = None
        self.avgdl: float = 0
        self.tf: dict[str, dict[int, int]] = {}  # term → {doc_idx → count}
        self.df: dict[str, int] = {}  # term → doc_count
        self.n_docs: int = 0

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"\w+", text.lower())

    def build(self, doc_ids: list[str], texts: list[str]):
        self.doc_ids = doc_ids
        self.n_docs = len(doc_ids)
        lengths = []

        for idx, text in enumerate(texts):
            tokens = self._tokenize(text)
            lengths.append(len(tokens))
            seen = set()
            for token in tokens:
                if token not in self.tf:
                    self.tf[token] = {}
                self.tf[token][idx] = self.tf[token].get(idx, 0) + 1
                if token not in seen:
                    self.df[token] = self.df.get(token, 0) + 1
                    seen.add(token)

        self.doc_lens = np.array(lengths, dtype=np.float32)
        self.avgdl = self.doc_lens.mean() if self.n_docs > 0 else 1.0

    def search(self, query: str, top_k: int = 20) -> list[tuple[str, float]]:
        tokens = self._tokenize(query)
        scores = np.zeros(self.n_docs, dtype=np.float64)

        for token in tokens:
            if token not in self.tf:
                continue
            df = self.df[token]
            idf = np.log((self.n_docs - df + 0.5) / (df + 0.5) + 1.0)

            for doc_idx, freq in self.tf[token].items():
                dl = self.doc_lens[doc_idx]
                tf_norm = (freq * (self.k1 + 1)) / (freq + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
                scores[doc_idx] += idf * tf_norm

        top_indices = np.argsort(scores)[::-1][:top_k]
        return [(self.doc_ids[i], float(scores[i])) for i in top_indices if scores[i] > 0]


# ---------------------------------------------------------------------------
# Vector search (LanceDB)
# ---------------------------------------------------------------------------

def build_vector_index(
    parquet_path: Path,
    lance_dir: Path,
    model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    batch_size: int = 64,
):
    """Compute embeddings and store in LanceDB."""
    import lancedb
    from sentence_transformers import SentenceTransformer

    df = pd.read_parquet(parquet_path)

    logger.info(f"Loading embedding model: {model_name}")
    model = SentenceTransformer(model_name, device="cpu")

    texts = df["text_clean"].fillna("").tolist()
    doc_ids = df["id"].tolist()

    logger.info(f"Computing embeddings for {len(texts)} documents...")
    embeddings = model.encode(
        [t[:8000] for t in texts],
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
    )

    # Build LanceDB table
    lance_dir.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(lance_dir))

    data = []
    for i, (doc_id, emb) in enumerate(zip(doc_ids, embeddings)):
        data.append({
            "doc_id": doc_id,
            "vector": emb.tolist(),
            "year": int(df.iloc[i]["year"]) if pd.notna(df.iloc[i]["year"]) else 0,
            "submitter_type": str(df.iloc[i].get("submitter_type", "")),
            "status": str(df.iloc[i].get("status_raw", "")),
            "kuerzel": str(df.iloc[i].get("kuerzel", "")),
            "title": str(df.iloc[i].get("title", "")),
        })

    if "documents" in db.table_names():
        db.drop_table("documents")
    db.create_table("documents", data)
    logger.info(f"Vector index built: {len(data)} documents → {lance_dir}")


def vector_search(
    query: str,
    lance_dir: Path,
    model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    top_k: int = 20,
    filters: dict | None = None,
) -> list[tuple[str, float]]:
    """Search the vector index."""
    import lancedb
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name, device="cpu")
    query_emb = model.encode(
        query,
        normalize_embeddings=True,
    )

    db = lancedb.connect(str(lance_dir))
    table = db.open_table("documents")

    # Build filter string
    filter_str = None
    if filters:
        parts = []
        if "year_min" in filters:
            parts.append(f"year >= {filters['year_min']}")
        if "year_max" in filters:
            parts.append(f"year <= {filters['year_max']}")
        if "submitter_type" in filters:
            parts.append(f"submitter_type = '{filters['submitter_type']}'")
        if parts:
            filter_str = " AND ".join(parts)

    search = table.search(query_emb).limit(top_k)
    if filter_str:
        search = search.where(filter_str)
    results = search.to_pandas()

    return [(row["doc_id"], float(1.0 / (1.0 + row["_distance"]))) for _, row in results.iterrows()]


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------

def reciprocal_rank_fusion(
    *ranked_lists: list[tuple[str, float]],
    k: int = 60,
    top_n: int = 20,
) -> list[tuple[str, float]]:
    """Fuse multiple ranked lists using RRF.

    Each input is a list of (doc_id, score) tuples, already sorted by score desc.
    Returns fused list of (doc_id, rrf_score).
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, (doc_id, _) in enumerate(ranked):
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)

    sorted_results = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_results[:top_n]


# ---------------------------------------------------------------------------
# Hybrid search (BM25 + vector + RRF)
# ---------------------------------------------------------------------------

class HybridSearch:
    """Combined BM25 + vector search with reciprocal rank fusion."""

    def __init__(
        self,
        parquet_path: Path,
        lance_dir: Path,
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    ):
        self.parquet_path = parquet_path
        self.lance_dir = lance_dir
        self.model_name = model_name
        self.bm25 = BM25Index()
        self._df: pd.DataFrame | None = None
        self._built = False

    def build(self):
        """Build BM25 index from parquet."""
        self._df = pd.read_parquet(self.parquet_path)
        doc_ids = self._df["id"].tolist()
        texts = self._df["text_clean"].fillna("").tolist()
        self.bm25.build(doc_ids, texts)
        self._built = True

    def search(
        self,
        query: str,
        top_k: int = 20,
        filters: dict | None = None,
        mode: str = "hybrid",
    ) -> list[dict]:
        """Run hybrid search.

        mode: "hybrid" | "bm25" | "vector"
        Returns list of dicts with doc_id, score, kuerzel, title, year, snippet.
        """
        if not self._built:
            self.build()

        results_bm25 = []
        results_vector = []

        if mode in ("hybrid", "bm25"):
            results_bm25 = self.bm25.search(query, top_k=top_k * 2)

        if mode in ("hybrid", "vector"):
            try:
                results_vector = vector_search(
                    query, self.lance_dir, self.model_name, top_k=top_k * 2, filters=filters,
                )
            except Exception:
                # Vector index may not be built yet
                pass

        if mode == "hybrid" and results_bm25 and results_vector:
            fused = reciprocal_rank_fusion(results_bm25, results_vector, top_n=top_k)
        elif results_vector:
            fused = results_vector[:top_k]
        else:
            fused = results_bm25[:top_k]

        # Apply metadata filters to BM25 results (vector search handles its own)
        if filters and mode != "vector" and self._df is not None:
            fused = self._apply_filters(fused, filters)

        # Enrich results
        return self._enrich(fused)

    def _apply_filters(self, results: list[tuple[str, float]], filters: dict) -> list[tuple[str, float]]:
        if self._df is None:
            return results
        valid_ids = set(self._df["id"])
        if "year_min" in filters:
            valid_ids &= set(self._df[self._df["year"] >= filters["year_min"]]["id"])
        if "year_max" in filters:
            valid_ids &= set(self._df[self._df["year"] <= filters["year_max"]]["id"])
        if "submitter_type" in filters:
            valid_ids &= set(self._df[self._df["submitter_type"] == filters["submitter_type"]]["id"])
        return [(did, score) for did, score in results if did in valid_ids]

    def _enrich(self, results: list[tuple[str, float]]) -> list[dict]:
        if self._df is None:
            return [{"doc_id": did, "score": score} for did, score in results]

        enriched = []
        df_indexed = self._df.set_index("id")
        for doc_id, score in results:
            if doc_id in df_indexed.index:
                row = df_indexed.loc[doc_id]
                text = str(row.get("text_clean", ""))
                enriched.append({
                    "doc_id": doc_id,
                    "score": round(score, 4),
                    "kuerzel": str(row.get("kuerzel", "")),
                    "title": str(row.get("title", "")),
                    "year": int(row["year"]) if pd.notna(row.get("year")) else None,
                    "status": str(row.get("status_raw", "")),
                    "submitter_type": str(row.get("submitter_type", "")),
                    "snippet": text[:300] + "..." if len(text) > 300 else text,
                })
            else:
                enriched.append({"doc_id": doc_id, "score": round(score, 4)})
        return enriched


# ---------------------------------------------------------------------------
# Federated search (multi-state, isolated indexes)
# ---------------------------------------------------------------------------

class FederatedSearch:
    """Multi-state search with isolated indexes per Landesverband.

    Each state has its own BM25 index and vector index. No cross-contamination.
    Cross-state queries merge results with RRF.
    """

    def __init__(self, data_dir: Path, model_name: str = "BAAI/bge-m3"):
        self.data_dir = data_dir
        self.model_name = model_name
        self._corpora: dict[str, HybridSearch] = {}
        self._discover_corpora()

    def _discover_corpora(self):
        """Auto-discover available states from data/derived/*/antraege.parquet."""
        derived_dir = self.data_dir / "derived"
        if not derived_dir.exists():
            # Fallback: flat structure (data/derived/antraege.parquet = "berlin")
            flat_parquet = self.data_dir / "derived" / "antraege.parquet"
            if flat_parquet.exists():
                lance = self.data_dir / "vectors" / "documents"
                self._corpora["berlin"] = HybridSearch(flat_parquet, lance, self.model_name)
            return

        for parquet in derived_dir.glob("*/antraege.parquet"):
            state = parquet.parent.name
            lance = self.data_dir / "vectors" / state / "documents"
            self._corpora[state] = HybridSearch(parquet, lance, self.model_name)

        # Fallback: flat structure if no subdirs found
        if not self._corpora:
            flat_parquet = derived_dir / "antraege.parquet"
            if flat_parquet.exists():
                lance = self.data_dir / "vectors" / "documents"
                self._corpora["berlin"] = HybridSearch(flat_parquet, lance, self.model_name)

    @property
    def available_states(self) -> list[str]:
        """List available Landesverbände."""
        return sorted(self._corpora.keys())

    def state_info(self) -> list[dict]:
        """Get doc count and status per state."""
        info = []
        for state, hs in sorted(self._corpora.items()):
            if not hs._built:
                hs.build()
            count = len(hs._df) if hs._df is not None else 0
            info.append({"state": state, "doc_count": count})
        return info

    def search(
        self,
        query: str,
        states: str | list[str] = "berlin",
        top_k: int = 20,
        filters: dict | None = None,
        mode: str = "bm25",
    ) -> list[dict]:
        """Search across one or more states.

        Args:
            query: Search query
            states: "berlin", "all", or ["berlin", "bayern", ...]
            top_k: Number of results
            filters: Metadata filters (year_min, year_max, submitter_type)
            mode: "hybrid", "bm25", or "vector"

        Returns:
            List of result dicts, each tagged with "landesverband" field.
        """
        if states == "all":
            targets = list(self._corpora.keys())
        elif isinstance(states, str):
            targets = [states]
        else:
            targets = list(states)

        # Single state — direct search, no fusion needed
        if len(targets) == 1:
            state = targets[0]
            if state not in self._corpora:
                return []
            results = self._corpora[state].search(query, top_k=top_k, filters=filters, mode=mode)
            for r in results:
                r["landesverband"] = state
            return results

        # Multiple states — search each, fuse with RRF
        all_results: dict[str, dict] = {}  # doc_id → result dict
        ranked_lists = []

        for state in targets:
            if state not in self._corpora:
                continue
            results = self._corpora[state].search(query, top_k=top_k * 2, filters=filters, mode=mode)
            for r in results:
                r["landesverband"] = state
                all_results[r["doc_id"]] = r
            ranked_lists.append([(r["doc_id"], r["score"]) for r in results])

        if not ranked_lists:
            return []

        fused = reciprocal_rank_fusion(*ranked_lists, top_n=top_k)

        # Rebuild result list with RRF scores
        output = []
        for doc_id, rrf_score in fused:
            if doc_id in all_results:
                result = all_results[doc_id].copy()
                result["score"] = round(rrf_score, 4)
                output.append(result)

        return output


if __name__ == "__main__":
    import sys

    data_dir = Path("data")

    if len(sys.argv) > 1 and sys.argv[1] == "build":
        parquet_path = Path("data/derived/antraege.parquet")
        lance_dir = Path("data/vectors/documents")
        build_vector_index(parquet_path, lance_dir)
    elif len(sys.argv) > 1 and sys.argv[1] == "federated":
        fs = FederatedSearch(data_dir)
        logger.info(f"Available states: {fs.available_states}")
        for info in fs.state_info():
            logger.info(f"  {info['state']}: {info['doc_count']} docs")
        query = sys.argv[2] if len(sys.argv) > 2 else "Mietpreisbremse"
        states = sys.argv[3] if len(sys.argv) > 3 else "all"
        results = fs.search(query, states=states, top_k=5, mode="bm25")
        for r in results:
            logger.info(f"  {r['score']:.3f}  [{r.get('landesverband', '?')}]  {r.get('kuerzel', '?'):30s}  {r.get('title', '')[:50]}")
    else:
        # Quick BM25-only test (legacy)
        parquet_path = Path("data/derived/antraege.parquet")
        lance_dir = Path("data/vectors/documents")
        hs = HybridSearch(parquet_path, lance_dir)
        hs.build()
        query = sys.argv[1] if len(sys.argv) > 1 else "Mietpreisbremse"
        results = hs.search(query, top_k=5, mode="bm25")
        for r in results:
            logger.info(f"  {r['score']:.3f}  {r.get('kuerzel', '?'):30s}  {r.get('title', '')[:60]}")
