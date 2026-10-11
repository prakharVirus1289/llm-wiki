#!/usr/bin/env python3
"""
Search Module: FTS5 Lexical Search & FastEmbed Vector Hybrid Engine
Combines SQLite FTS5 BM25-style ranks with CPU-based sentence-transformer vector embeddings using RRF.
"""

import os
import re
import time
from pathlib import Path
from .connection import get_connection, logger
from .firehose import query_firehose_raw

_embedding_model = None

def get_embedding_model():
    """Lazy loader for fastembed TextEmbedding model."""
    global _embedding_model
    if _embedding_model is None:
        try:
            from fastembed import TextEmbedding
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            _embedding_model = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")
        except Exception as e:
            logger.error("Failed to load fastembed TextEmbedding: %s", e)
            raise
    return _embedding_model


STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "aren't", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both",
    "but", "by", "can", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does",
    "doesn't", "doing", "don't", "down", "during", "each", "few", "for", "from", "further", "had",
    "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd",
    "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself", "let's",
    "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off", "on", "once",
    "only", "or", "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same",
    "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves", "then", "there",
    "there's", "these", "they", "they'd", "they'll", "they're", "they've", "this", "those",
    "through", "to", "too", "under", "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll",
    "we're", "we've", "were", "weren't", "what", "what's", "when", "when's", "where", "where's",
    "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself",
    "yourselves", "investigate", "explore", "tell", "explain", "find", "describe"
}


def search_keywords(db_path: Path, keywords: str, limit: int = 30) -> list[dict]:
    """
    Executes pure lexical FTS5 search across wiki sections with stopword stripping and BM25 ranking.
    """
    if not db_path.exists() or not keywords.strip():
        return []

    t0 = time.perf_counter()
    clean = re.sub(r'[^\w\s]', ' ', keywords).strip()
    words = [w for w in clean.split() if len(w) > 1 and w.lower() not in STOPWORDS]
    if not words:
        words = [w for w in clean.split() if len(w) > 1]
    if not words:
        return []

    fts_expr = " OR ".join(f'"{w}"' for w in words[:25])
    conn = get_connection(db_path)
    try:
        cursor = conn.execute("""
            SELECT file_path, heading, snippet(wiki_sections_fts, 2, '<b>', '</b>', '...', 15), bm25(wiki_sections_fts) as rank
            FROM wiki_sections_fts
            WHERE wiki_sections_fts MATCH ?
            ORDER BY rank
            LIMIT ?;
        """, (fts_expr, limit))
        results = [
            {
                "file": row[0],
                "heading": row[1],
                "snippet": row[2],
                "bm25_rank": round(float(row[3]), 4)
            }
            for row in cursor.fetchall()
        ]
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("FTS5 search_keywords returned %d matches in %.2f ms (query='%s')", len(results), elapsed_ms, fts_expr)
        return results
    except Exception as e:
        logger.warning("search_keywords error on expr '%s': %s", fts_expr, e)
        return []
    finally:
        conn.close()


def search_similarity(db_path: Path, query_text: str, limit: int = 30) -> list[dict]:
    """
    Executes pure fastembed vector cosine similarity search across all indexed wiki sections.
    """
    if not db_path.exists() or not query_text.strip():
        return []

    t0 = time.perf_counter()
    conn = get_connection(db_path)
    try:
        import numpy as np

        cursor = conn.execute("""
            SELECT file_path, heading, embedding
            FROM wiki_sections_index
            WHERE embedding IS NOT NULL;
        """)
        emb_rows = cursor.fetchall()
        if not emb_rows:
            return []

        model = get_embedding_model()
        q_emb = list(model.embed([query_text]))[0]
        q_vec = np.array(q_emb, dtype=np.float32)
        q_norm = np.linalg.norm(q_vec)
        if q_norm > 0:
            q_vec = q_vec / q_norm

        files_headings = []
        vecs = []
        for r in emb_rows:
            files_headings.append((r[0], r[1]))
            vecs.append(np.frombuffer(r[2], dtype=np.float32))

        mat = np.stack(vecs)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        mat = mat / norms

        sims = np.dot(mat, q_vec)
        top_indices = np.argsort(sims)[::-1][:limit]

        results = []
        for rank, idx in enumerate(top_indices, 1):
            fh = files_headings[idx]
            sim_score = float(sims[idx])
            results.append({
                "rank": rank,
                "file": fh[0],
                "heading": fh[1],
                "similarity": round(sim_score, 4)
            })

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("search_similarity returned %d matches in %.2f ms (query='%s')", len(results), elapsed_ms, query_text)
        return results
    except Exception as e:
        logger.warning("search_similarity error for query '%s': %s", query_text, e)
        return []
    finally:
        conn.close()


def search_section(db_path: Path, query_text: str, limit: int = 20) -> list[dict]:
    """Executes high-speed lexical search on wiki_sections_fts and returns structured dict list."""
    if not db_path.exists():
        return []

    logger.debug("FTS5 search_section executing for query: '%s' (limit=%d)", query_text, limit)
    conn = get_connection(db_path)
    try:
        cursor = conn.execute("""
            SELECT file_path, heading, snippet(wiki_sections_fts, 2, '<b>', '</b>', '...', 12)
            FROM wiki_sections_fts
            WHERE wiki_sections_fts MATCH ?
            LIMIT ?;
        """, (query_text, limit))
        return [
            {"file": row[0], "heading": row[1], "snippet": row[2]}
            for row in cursor.fetchall()
        ]
    except Exception as e:
        logger.warning("search_section error: %s", e)
        return []
    finally:
        conn.close()


def query_section(db_path: Path, query_text: str, limit: int = 20):
    """CLI wrapper: executes lexical search on wiki_sections_fts and prints results."""
    t0 = time.perf_counter()
    rows = search_section(db_path, query_text, limit)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info("FTS5 query_section returned %d matching sections in %.2f ms", len(rows), elapsed_ms)
    if not rows:
        print(f"[NOT FOUND] No sections matched query: '{query_text}'")
        return
    print(f"[MATCHES] Found {len(rows)} matching sections:")
    for r in rows:
        print(f"  - File: {r['file']} | Heading: {r['heading']}")
        print(f"    Snippet: {r['snippet']}")


def query_firehose(db_path: Path, keyword: str, limit: int = 5):
    """CLI wrapper: executes lexical search on raw_firehose and prints results."""
    t0 = time.perf_counter()
    rows = query_firehose_raw(db_path, keyword, limit)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info("FTS5 query_firehose returned %d raw items in %.2f ms", len(rows), elapsed_ms)
    if not rows:
        print(f"[NOT FOUND] No raw posts matched keyword: '{keyword}'")
        return
    print(f"[FIREHOSE MATCHES] Found {len(rows)} raw posts:")
    for r in rows:
        print(f"  - [{r['platform']}] {r['title']}")
        print(f"    URL: {r['url']}")
        print(f"    Snippet: {r['snippet']}")


def search_hybrid(db_path: Path, query_text: str, limit: int = 20) -> list[dict]:
    """Executes hybrid search fusing FTS5 lexical ranking with vector cosine similarity via RRF, returning structured dict list."""
    if not db_path.exists():
        return []

    logger.debug("Hybrid search executing for query: '%s' (limit=%d)", query_text, limit)
    t0 = time.perf_counter()
    conn = get_connection(db_path)
    try:
        import numpy as np

        # 1. Lexical FTS5 candidate matching
        keyword_ranks = {}
        fts_query = re.sub(r'[^\w\s]', ' ', query_text).strip()
        fts_words = [w for w in fts_query.split() if len(w) > 1 and w.lower() not in STOPWORDS]
        if not fts_words:
            fts_words = [w for w in fts_query.split() if len(w) > 1]
        if fts_words:
            fts_expr = " OR ".join(f'"{w}"' for w in fts_words[:25])
            try:
                cursor = conn.execute("""
                    SELECT file_path, heading, snippet(wiki_sections_fts, 2, '<b>', '</b>', '...', 12)
                    FROM wiki_sections_fts
                    WHERE wiki_sections_fts MATCH ?
                    LIMIT 50;
                """, (fts_expr,))
                fts_rows = cursor.fetchall()
                for rank, row in enumerate(fts_rows):
                    keyword_ranks[(row[0], row[1])] = (rank + 1, row[2])
            except Exception as e:
                logger.warning("FTS5 match failed for '%s': %s", fts_expr, e)

        # 2. Vector Semantic Similarity
        cursor = conn.execute("""
            SELECT file_path, heading, embedding
            FROM wiki_sections_index
            WHERE embedding IS NOT NULL;
        """)
        emb_rows = cursor.fetchall()
        meaning_ranks = {}
        if emb_rows:
            try:
                model = get_embedding_model()
                q_emb = list(model.embed([query_text]))[0]
                q_vec = np.array(q_emb, dtype=np.float32)
                q_norm = np.linalg.norm(q_vec)
                if q_norm > 0:
                    q_vec = q_vec / q_norm

                files_headings = []
                vecs = []
                for r in emb_rows:
                    files_headings.append((r[0], r[1]))
                    vecs.append(np.frombuffer(r[2], dtype=np.float32))

                mat = np.stack(vecs)
                norms = np.linalg.norm(mat, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                mat = mat / norms

                sims = np.dot(mat, q_vec)
                top_indices = np.argsort(sims)[::-1][:50]
                for rank, idx in enumerate(top_indices):
                    fh = files_headings[idx]
                    meaning_ranks[fh] = (rank + 1, float(sims[idx]))
            except Exception as e:
                logger.warning("Vector semantic search failed: %s", e)

        # 3. Reciprocal Rank Fusion (RRF)
        all_candidates = set(keyword_ranks.keys()).union(set(meaning_ranks.keys()))
        if not all_candidates:
            return []

        scored = []
        for cand in all_candidates:
            kw_data = keyword_ranks.get(cand)
            mn_data = meaning_ranks.get(cand)
            kw_rank = kw_data[0] if kw_data else None
            mn_rank = mn_data[0] if mn_data else None

            kw_score = 1.0 / (60 + kw_rank) if kw_rank is not None else 0.0
            mn_score = 1.0 / (60 + mn_rank) if mn_rank is not None else 0.0
            rrf_score = kw_score + mn_score
            snippet_text = kw_data[1] if kw_data else ""
            mn_sim = mn_data[1] if mn_data else 0.0

            scored.append({
                "file": cand[0],
                "heading": cand[1],
                "rrf_score": round(rrf_score, 4),
                "kw_rank": kw_rank,
                "vector_rank": mn_rank,
                "vector_similarity": round(mn_sim, 3) if mn_data else None,
                "snippet": snippet_text
            })

        scored.sort(key=lambda x: x["rrf_score"], reverse=True)
        top_results = scored[:limit]

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("search_hybrid returned %d candidates in %.2f ms", len(top_results), elapsed_ms)
        return top_results
    finally:
        conn.close()


def query_hybrid(db_path: Path, query_text: str, limit: int = 20):
    """CLI wrapper: executes hybrid search fusing FTS5 lexical ranking with vector cosine similarity and prints results."""
    t0 = time.perf_counter()
    top_results = search_hybrid(db_path, query_text, limit)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    if not top_results:
        print(f"[NOT FOUND] No sections matched query: '{query_text}'")
        return
    print(f"[HYBRID MATCHES] Found {len(top_results)} candidates in {elapsed_ms:.2f} ms:")
    for idx, res in enumerate(top_results, 1):
        kw_label = f"KW Rank #{res['kw_rank']}" if res['kw_rank'] else "KW: None"
        mn_label = f"Vector Rank #{res['vector_rank']} (sim: {res['vector_similarity']:.3f})" if res['vector_rank'] else "Vector: None"
        print(f"  {idx}. [{res['file']}] -> {res['heading']}")
        print(f"     Score: {res['rrf_score']:.4f} | {kw_label} | {mn_label}")
        if res['snippet']:
            print(f"     Snippet: {res['snippet']}")
