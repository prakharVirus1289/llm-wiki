#!/usr/bin/env python3
"""
Telemetry Audit & Knowledge Graph Analyzer:
Prepares physical programmatic reads for the Milestone Review Council.
"""

import sys
import re
import sqlite3
from pathlib import Path
from collections import defaultdict

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
WIKI_DIR = WORKSPACE_ROOT / "wiki"
DB_PATH = WORKSPACE_ROOT / "raw_firehose.db"

def run_audit():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM raw_firehose;")
    total_raw = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM raw_firehose WHERE processed = 1;")
    high_signal = c.fetchone()[0]

    c.execute("SELECT platform, COUNT(*) FROM raw_firehose GROUP BY platform ORDER BY COUNT(*) DESC;")
    platforms = c.fetchall()
    conn.close()

    print(f"TOTAL RAW ITEMS: {total_raw}")
    print(f"HIGH SIGNAL ITEMS: {high_signal}")
    print("\nPLATFORM DISTRIBUTION:")
    for p, count in platforms:
        pct = (count / total_raw) * 100
        print(f"  - {p}: {count} ({pct:.1f}%)")

    # Chapter analysis
    print("\nCHAPTER ANALYSIS:")
    all_wikilinks = set()
    chapter_headings = {}
    for md in WIKI_DIR.glob("*.md"):
        if md.name == "index.md":
            continue
        text = md.read_text(encoding="utf-8")
        headings = re.findall(r'^(#{1,4})\s+(.+)$', text, re.MULTILINE)
        wikilinks = re.findall(r'\[\[(.+?)\]\]', text)
        for wl in wikilinks:
            all_wikilinks.add(wl.strip())
        chapter_headings[md.name] = [h[1].strip() for h in headings]
        print(f"  - {md.name}: {len(headings)} headings, {len(wikilinks)} wikilinks")

    print(f"\nTOTAL UNIQUE WIKILINKS REFERENCED: {len(all_wikilinks)}")

if __name__ == "__main__":
    run_audit()
