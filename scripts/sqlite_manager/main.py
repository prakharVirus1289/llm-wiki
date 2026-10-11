#!/usr/bin/env python3
"""
SQLite Manager CLI Entry Point
Dispatches commands across database initialization, maintenance, indexing, search, and graph analysis.
"""

import sys
import argparse
from pathlib import Path

# Ensure package import works when invoked directly as a script (e.g. python scripts/sqlite_manager/main.py)
pkg_dir = Path(__file__).resolve().parent
if str(pkg_dir.parent) not in sys.path:
    sys.path.insert(0, str(pkg_dir.parent))

from sqlite_manager.connection import get_connection, init_db, truncate_wal, snapshot_db, logger
from sqlite_manager.indexer import normalize_slug, parse_wikilink, index_wiki
from sqlite_manager.search import get_embedding_model, query_section, query_firehose, query_hybrid
from sqlite_manager.graph import get_backlinks, get_related_concepts, get_dangling_links
from sqlite_manager.cross_linker import build_concept_dictionary, scan_and_link_text, find_cross_chapter_similarities


def main():
    parser = argparse.ArgumentParser(description="SQLite Manager Modular CLI")
    parser.add_argument("action", choices=["init", "truncate", "snapshot", "index-wiki", "query-section", "query-firehose", "query-hybrid", "backlinks", "related", "dangling", "scan-links", "suggest-links"])
    parser.add_argument("--db", default="raw_firehose.db", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--wiki-dir", default=Path("wiki"), type=Path)
    parser.add_argument("--file", type=Path, help="Target markdown file for scan-links")
    parser.add_argument("--threshold", default=0.82, type=float, help="Similarity threshold for suggest-links")
    parser.add_argument("--dry-run", action="store_true", help="Do not overwrite file in scan-links")
    parser.add_argument("--query", type=str)
    parser.add_argument("--concept", type=str)
    parser.add_argument("--limit", default=20, type=int)
    parser.add_argument("--heading", type=str, help="Target section heading for suggest-links")
    parser.add_argument("--embed", action="store_true", help="Generate vector embeddings for new/modified sections")
    args = parser.parse_args()

    if args.action == "init":
        init_db(args.db)
    elif args.action == "truncate":
        truncate_wal(args.db)
    elif args.action == "snapshot":
        if not args.out:
            print("Error: --out is required for snapshot.")
            sys.exit(1)
        snapshot_db(args.db, args.out)
    elif args.action == "index-wiki":
        index_wiki(args.db, args.wiki_dir, embed=args.embed)
    elif args.action == "query-section":
        if not args.query:
            print("Error: --query is required for query-section.")
            sys.exit(1)
        query_section(args.db, args.query, limit=args.limit)
    elif args.action == "query-hybrid":
        if not args.query:
            print("Error: --query is required for query-hybrid.")
            sys.exit(1)
        query_hybrid(args.db, args.query, limit=args.limit)
    elif args.action == "query-firehose":
        if not args.query:
            print("Error: --query is required for query-firehose.")
            sys.exit(1)
        query_firehose(args.db, args.query, limit=args.limit)
    elif args.action == "backlinks":
        if not args.concept:
            print("Error: --concept is required for backlinks.")
            sys.exit(1)
        bls = get_backlinks(args.db, args.concept)
        print(f"[BACKLINKS] Found {len(bls)} citing sections for '{args.concept}':")
        for b in bls:
            print(f"  - {b['source_file']} -> {b['source_heading']} (scope: {b['domain_scope']}, alias: {b['link_alias']})")
    elif args.action == "related":
        if not args.concept:
            print("Error: --concept is required for related.")
            sys.exit(1)
        rel = get_related_concepts(args.db, args.concept)
        print(f"[RELATED] Concepts co-cited with '{args.concept}':")
        for r in rel:
            print(f"  - {r['target_concept']} ({r['domain_scope']}): {r['co_citation_count']} co-citations")
    elif args.action == "dangling":
        dang = get_dangling_links(args.db, limit=args.limit)
        print(f"[DANGLING] Top {len(dang)} uncategorized / dangling concepts:")
        for d in dang:
            print(f"  - [[{d['target_concept']}]] ({d['domain_scope']}): cited {d['incoming_citations']} times by {d['citing_files']}")
    elif args.action == "scan-links":
        print("[SCAN-LINKS] Notice: Deterministic regex auto-linking is permanently disabled to prevent knowledge graph corruption.")
        print("[SCAN-LINKS] All cross-chapter links must be authored intentionally by agents via the 4-Point Epistemic Link Audit.")
        print("[SCAN-LINKS] Use 'suggest-links' instead to discover candidate pairs for agent evaluation.")
    elif args.action == "suggest-links":
        file_arg = str(args.file) if args.file else None
        cands = find_cross_chapter_similarities(args.db, threshold=args.threshold, limit=args.limit, file=file_arg, heading=args.heading)
        target_str = f" for '{args.heading}' in '{file_arg}'" if file_arg else ""
        print(f"[SUGGEST-LINKS] Top {len(cands)} cross-chapter candidate pairs (threshold={args.threshold}{target_str}):")
        for c in cands:
            already = " [ALREADY LINKED]" if c["is_already_linked"] else ""
            print(f"  - ({c['similarity']*100:.1f}%) [{c['source_file']}] '{c['source_heading'][:30]}' <---> [{c['target_file']}] '{c['target_heading'][:30]}'{already}")


if __name__ == "__main__":
    main()
