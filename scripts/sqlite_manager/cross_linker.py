#!/usr/bin/env python3
"""
Cross-Chapter Linking Engine
Provides:
1. Dictionary Scan: Automatically identifies mentions of known topics from other chapters
   and inserts [[domain/slug|alias]] links without touching code blocks or existing links.
2. Similarity Scan: Uses vector embeddings across all chapters to find high-similarity
   topics (> 0.82) that belong to different files and are not yet linked.
"""

import re
import time
from pathlib import Path
from typing import Optional
import numpy as np

from .connection import get_connection, logger
from .indexer import normalize_slug

# Words and titles that are too generic to link automatically
GENERIC_STOP_HEADINGS = {
    "overview", "summary", "abstract", "introduction", "background",
    "conclusion", "conclusions", "notes", "references", "index",
    "table of contents", "changelog", "future work", "architecture",
    "benchmarks", "evaluation", "evaluations", "results", "discussion",
    "limitations", "status threat", "metadata", "key takeaways", "faq",
    "example", "examples", "configuration", "highlights", "the problem",
    "the beginning", "the architecture", "what's new", "whats new", "tl;dr",
    "tldr", "key features", "details", "setup", "usage", "features",
    "installation", "prerequisites", "motivation", "demo", "demo video",
    "disclaimer", "pros and cons", "getting started", "how it works", "why",
    "who am i", "about", "context", "next steps", "update", "updates",
    "what it is", "the problem it solves", "how to use", "why it matters",
    "how to", "deep dive", "in-depth", "the context", "the use case",
    "the use cases", "the system", "the approach", "the solution",
    "the pattern", "the pipeline", "the workflow", "the model", "the prompt",
    "the challenge", "the goal", "the objective", "the framework",
    "hardware setup", "hardware used", "key components", "hardware",
    "environment", "dependencies", "test setup", "benchmark setup"
}


def clean_heading_text(heading: str) -> str:
    """Strips leading/trailing markdown, bracket wrappers, and numbers."""
    h = heading.strip().lstrip("#").strip()
    h = re.sub(r"^\[\[(.*)\]\]$", r"\1", h)
    return h.strip()


def is_substantive_concept_heading(heading: str) -> bool:
    """
    Returns True ONLY if the heading represents a substantive architectural concept.
    Rejects:
    - Scraped post items (e.g. headings starting with [[, containing URLs, or raw social media feeds)
    - News digests, newsletters, release announcements, model cards (e.g. 'Last Week in', 'Announcing', 'HF Model')
    - Generic conversational phrases (e.g. 'the context', 'the use case', 'how it works')
    - Full sentences, questions, exclamations, dates, or version strings
    """
    raw = heading.strip()
    if raw.startswith("[[") or "http://" in raw or "https://" in raw:
        return False

    clean = clean_heading_text(raw)
    clean_lower = clean.lower()

    if clean_lower in GENERIC_STOP_HEADINGS:
        return False

    # Filter out scraped post titles and noise markers
    noise_markers = [
        "http://", "https://", "t.co/", "hf model", "last week in", "announcing",
        "release", "week of", "e-commerce", "show hn", "ask hn", "newsletter",
        "changelog", "readme.md", "manual.md", "architecture.md", ".json", ".py", ".md",
        "github.com", "reddit.com", "twitter.com", "x.com", "crate ", "ingested", "cycle #"
    ]
    if any(m in clean_lower for m in noise_markers):
        return False

    # Filter out date or version prefixed titles
    if re.match(r'^(v?\d+\.|\d{1,2}/\d{1,2}|\d{4}-\d{2})', clean_lower):
        return False

    # A technical concept is a concise noun phrase (2 to 7 words, 6 to 55 characters)
    words = clean.split()
    if len(words) < 2 or len(words) > 7:
        return False
    if len(clean) < 6 or len(clean) > 55:
        return False

    # Questions, exclamations, ellipses indicate conversational forum chatter
    if any(punct in clean for punct in ["?", "!", "...", ":", ";"]):
        return False

    return True


def build_concept_dictionary(db_path: Path, min_length: int = 6) -> dict[str, tuple[str, str, str]]:
    """
    Builds an in-memory dictionary of known concepts from wiki_sections_index.
    Returns: dict mapping lowercase phrase -> (owner_file, heading_slug, original_heading)
    Sorted with longest phrases first to prevent sub-string collision.
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.execute("""
            SELECT file_path, heading, heading_slug 
            FROM wiki_sections_index 
            WHERE LENGTH(heading) >= ?;
        """, (min_length,))
        raw_items = cursor.fetchall()
    finally:
        conn.close()

    dictionary = {}
    for file_path, heading, heading_slug in raw_items:
        if not is_substantive_concept_heading(heading):
            continue

        clean = clean_heading_text(heading)
        clean_lower = clean.lower()

        # Map phrase to target destination
        dictionary[clean_lower] = (file_path, heading_slug, heading)

    # Sort descending by length so longer multi-word concepts match before single words
    sorted_dict = dict(sorted(dictionary.items(), key=lambda item: len(item[0]), reverse=True))
    return sorted_dict


def scan_and_link_text(content: str, current_file: str, concept_dict: dict[str, tuple[str, str, str]]) -> tuple[str, list[dict]]:
    """
    Deprecated / Disabled:
    Deterministic regex string replacement for cross-links has been removed to prevent knowledge graph corruption.
    All cross-chapter wikilinks must be authored intentionally by agents via the 4-Point Epistemic Link Audit.
    Returns the content completely unchanged and an empty list of applied links.
    """
    logger.warning("scan_and_link_text called, but deterministic regex auto-linking is permanently disabled. Content left unchanged.")
    return content, []


def find_cross_chapter_similarities(
    db_path: Path, 
    threshold: float = 0.82, 
    limit: int = 25,
    file: str | None = None,
    heading: str | None = None
) -> list[dict]:
    """
    Calculates cosine similarity across chapter sections using their vector embeddings.
    If file (and optionally heading) is specified, only finds sections in OTHER chapters
    that are similar to that specific section (targeted search for new/modified content).
    Otherwise, scans all sections across all chapters for top similar pairs.
    """
    t0 = time.perf_counter()
    conn = get_connection(db_path)
    try:
        # Load all sections
        cursor = conn.execute("""
            SELECT file_path, heading, heading_slug, embedding, content
            FROM wiki_sections_index;
        """)
        rows = cursor.fetchall()
        if len(rows) < 2:
            return []

        # Load existing resolved links to avoid suggesting already connected pairs
        link_cursor = conn.execute("""
            SELECT source_file, target_file 
            FROM wiki_resolved_links 
            WHERE is_resolved = 1 AND is_cross_chapter = 1;
        """)
        existing_edges = set((r[0], r[1]) for r in link_cursor.fetchall())
    finally:
        conn.close()

    # If target file is provided, run targeted 1-to-many similarity search for that section
    if file:
        target_stem = Path(file).stem.lower()
        target_heading_clean = heading.strip().lower() if heading else None

        # Locate the target section
        target_row = None
        for r in rows:
            f_stem = Path(r[0]).stem.lower()
            if f_stem == target_stem:
                if target_heading_clean:
                    if r[1].lower() == target_heading_clean or r[2] == normalize_slug(heading) or target_heading_clean in r[1].lower():
                        target_row = r
                        break
                else:
                    target_row = r
                    break

        if not target_row:
            logger.warning("Target section '%s' in '%s' not found in index for targeted similarity search.", heading, file)
            return []

        # If embedding is missing for the target section, compute it on the fly
        target_emb_bytes = target_row[3]
        if target_emb_bytes is None:
            from .search import get_embedding_model
            model = get_embedding_model()
            text = f"{target_row[1]}: {target_row[4][:500] if target_row[4] else ''}"
            emb_list = list(model.embed([text]))
            target_emb = np.array(emb_list[0], dtype=np.float32)
            # Cache back to database
            conn = get_connection(db_path)
            try:
                conn.execute(
                    "UPDATE wiki_sections_index SET embedding = ? WHERE file_path = ? AND heading = ?",
                    (target_emb.tobytes(), target_row[0], target_row[1])
                )
                conn.commit()
            finally:
                conn.close()
        else:
            target_emb = np.frombuffer(target_emb_bytes, dtype=np.float32)

        # Normalize target embedding vector
        target_norm = target_emb / (np.linalg.norm(target_emb) or 1.0)

        # Filter other sections in different chapters that have embeddings and substantive titles
        other_rows = [
            r for r in rows 
            if Path(r[0]).stem.lower() != target_stem 
            and r[3] is not None 
            and is_substantive_concept_heading(r[1])
        ]

        if not other_rows:
            return []

        other_mat = np.stack([np.frombuffer(r[3], dtype=np.float32) for r in other_rows])
        other_norms = np.linalg.norm(other_mat, axis=1, keepdims=True)
        other_norms[other_norms == 0] = 1.0
        other_norm_mat = other_mat / other_norms

        # Dot product with target vector
        sims = other_norm_mat @ target_norm

        candidates = []
        matching_indices = np.where(sims >= threshold)[0]
        for idx in matching_indices:
            r = other_rows[idx]
            score = float(sims[idx])
            candidates.append({
                "source_file": target_row[0],
                "source_heading": target_row[1],
                "source_slug": target_row[2],
                "target_file": r[0],
                "target_heading": r[1],
                "target_slug": r[2],
                "similarity": round(score, 4),
                "is_already_linked": (target_row[0], r[0]) in existing_edges or (r[0], target_row[0]) in existing_edges
            })

        candidates.sort(key=lambda x: x["similarity"], reverse=True)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("Targeted suggest_links for '%s' scanned %d sections in %.2f ms, found %d candidates",
                    target_row[1], len(other_rows), elapsed_ms, len(candidates))
        return candidates[:limit]

    # Global all-pairs fallback when no specific file is requested
    valid_rows = [r for r in rows if is_substantive_concept_heading(r[1]) and r[3] is not None]
    if len(valid_rows) < 2:
        return []

    files = [r[0] for r in valid_rows]
    headings = [r[1] for r in valid_rows]
    slugs = [r[2] for r in valid_rows]
    embeddings = [np.frombuffer(r[3], dtype=np.float32) for r in valid_rows]

    # Convert to 2D numpy matrix: shape (N, 384)
    mat = np.stack(embeddings)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    norm_mat = mat / norms

    # Fast matrix multiplication for cosine similarity
    sim_matrix = norm_mat @ norm_mat.T

    # Find cross-chapter pairs exceeding threshold
    n = len(valid_rows)
    candidates = []

    for i in range(n):
        file_i = files[i]
        heading_i = headings[i]

        matching_indices = np.where((sim_matrix[i, i+1:] >= threshold))[0] + (i + 1)
        for j in matching_indices:
            file_j = files[j]
            heading_j = headings[j]

            # Only cross-chapter
            if Path(file_i).stem.lower() == Path(file_j).stem.lower():
                continue

            score = float(sim_matrix[i, j])

            candidates.append({
                "source_file": file_i,
                "source_heading": heading_i,
                "source_slug": slugs[i],
                "target_file": file_j,
                "target_heading": heading_j,
                "target_slug": slugs[j],
                "similarity": round(score, 4),
                "is_already_linked": (file_i, file_j) in existing_edges or (file_j, file_i) in existing_edges
            })

    candidates.sort(key=lambda x: x["similarity"], reverse=True)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info("find_cross_chapter_similarities scanned %d sections in %.2f ms, found %d candidates", 
                n, elapsed_ms, len(candidates))

    return candidates[:limit]
