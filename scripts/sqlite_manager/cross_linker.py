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
    Scans markdown text, identifies mentions of concepts belonging to OTHER chapters,
    and formats them as [[target_domain/target_slug|matched_text]].
    
    Protects:
    - Code blocks (fenced ``` and inline `)
    - Existing [[wikilinks]]
    - URLs (http://, https://)
    - Heading lines (# Heading)
    """
    current_stem = Path(current_file).stem.lower()
    placeholders = []

    def mask_match(match):
        token = f"\x1fMASK_{len(placeholders)}\x1f"
        placeholders.append(match.group(0))
        return token

    # 1. Mask fenced code blocks
    masked = re.sub(r'```[\s\S]*?```', mask_match, content)

    # 2. Mask inline code spans
    masked = re.sub(r'`[^`\n]+`', mask_match, masked)

    # 3. Mask existing wikilinks
    masked = re.sub(r'\[\[[\s\S]*?\]\]', mask_match, masked)

    # 4. Mask URLs
    masked = re.sub(r'https?://[^\s)\]]+', mask_match, masked)

    # 5. Mask heading lines so headers themselves are not recursively linked
    masked = re.sub(r'^(#{1,6}\s+.*)$', mask_match, masked, flags=re.MULTILINE)

    applied_links = []
    
    # 6. Build single combined regex for cross-chapter concepts
    valid_dict = {
        phrase: (owner_file, target_slug, original_heading)
        for phrase, (owner_file, target_slug, original_heading) in concept_dict.items()
        if Path(owner_file).stem.lower() != current_stem and owner_file != current_file
    }

    if not valid_dict:
        # Restore all masked tokens in reverse order to resolve nested masks
        max_passes = 10
        passes = 0
        while "\x1fMASK_" in masked and passes < max_passes:
            for idx in range(len(placeholders) - 1, -1, -1):
                masked = masked.replace(f"\x1fMASK_{idx}\x1f", placeholders[idx])
            passes += 1
        return masked, []

    sorted_phrases = sorted(valid_dict.keys(), key=len, reverse=True)
    pattern = re.compile(rf'\b({"|".join(re.escape(p) for p in sorted_phrases)})\b', re.IGNORECASE)

    def link_replacer(m):
        matched_text = m.group(1)
        key = matched_text.lower()
        if key not in valid_dict:
            return matched_text
        owner_file, target_slug, original_heading = valid_dict[key]
        owner_stem = Path(owner_file).stem.lower()
        target_link = f"[[{owner_stem}/{target_slug}|{matched_text}]]"
        applied_links.append({
            "matched_text": matched_text,
            "target_file": owner_file,
            "target_heading": original_heading,
            "target_link": target_link
        })
        token = f"\x1fMASK_{len(placeholders)}\x1f"
        placeholders.append(target_link)
        return token

    masked = pattern.sub(link_replacer, masked)

    # 7. Restore all masked tokens in reverse order to resolve nested masks
    max_passes = 10
    passes = 0
    while "\x1fMASK_" in masked and passes < max_passes:
        for idx in range(len(placeholders) - 1, -1, -1):
            masked = masked.replace(f"\x1fMASK_{idx}\x1f", placeholders[idx])
        passes += 1

    return masked, applied_links


def find_cross_chapter_similarities(db_path: Path, threshold: float = 0.82, limit: int = 25) -> list[dict]:
    """
    Calculates cosine similarity across all chapter sections using their vector embeddings.
    Filters for high similarity (> threshold) pairs that belong to DIFFERENT files
    and are not yet linked in the database.
    """
    t0 = time.perf_counter()
    conn = get_connection(db_path)
    try:
        # Load all sections with embeddings
        cursor = conn.execute("""
            SELECT file_path, heading, heading_slug, embedding 
            FROM wiki_sections_index 
            WHERE embedding IS NOT NULL;
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

    valid_rows = [r for r in rows if is_substantive_concept_heading(r[1])]
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

        # Look at upper triangle
        matching_indices = np.where((sim_matrix[i, i+1:] >= threshold))[0] + (i + 1)
        for j in matching_indices:
            file_j = files[j]
            heading_j = headings[j]

            # Only cross-chapter
            if file_i == file_j:
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

    # Sort descending by similarity score
    candidates.sort(key=lambda x: x["similarity"], reverse=True)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info("find_cross_chapter_similarities scanned %d sections in %.2f ms, found %d candidates", 
                n, elapsed_ms, len(candidates))

    return candidates[:limit]
