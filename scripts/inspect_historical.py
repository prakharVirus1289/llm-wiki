#!/usr/bin/env python3
"""
Inspect all historical research folders across Documents/
"""

import sqlite3
from pathlib import Path

workspaces = [
    Path(r"C:\Users\ASUS\Documents\deep-web-analysis\Research_Autonomous_Technical_Knowledge_Engine"),
    Path(r"C:\Users\ASUS\Documents\deep-web-analysis\Research_Evolve_stress_test_LLM"),
    Path(r"C:\Users\ASUS\Documents\deep-web-analysis\Research_Karpathy_LLM_Wiki_Coding"),
    Path(r"C:\Users\ASUS\Documents\SharedContextResearch")
]

print("=== HISTORICAL RESEARCH WORKSPACES ===")
for ws in workspaces:
    print(f"\nWorkspace: {ws.name}")
    db_file = ws / "dedup_state.sqlite"
    if db_file.exists():
        try:
            conn = sqlite3.connect(db_file)
            c = conn.cursor()
            c.execute("SELECT count(*) FROM processed_items;")
            item_count = c.fetchone()[0]
            c.execute("SELECT platform, count(*) FROM processed_items GROUP BY platform;")
            platform_counts = c.fetchall()
            print(f"  - Database: {db_file.name} ({db_file.stat().st_size / 1024 / 1024:.2f} MB)")
            print(f"  - Total Processed Items: {item_count}")
            print(f"  - Platforms: {platform_counts}")
            conn.close()
        except Exception as e:
            print(f"  - Error reading DB: {e}")
    else:
        print("  - No dedup_state.sqlite found")

    wiki_files = list(ws.glob("*WIKI*.md")) + list(ws.glob("*wiki*.md"))
    for wf in wiki_files:
        print(f"  - Wiki: {wf.name} ({wf.stat().st_size / 1024:.1f} KB, lines: {len(wf.read_text(encoding='utf-8', errors='replace').splitlines())})")
    
    reports = list((ws / "reports").glob("*.md")) if (ws / "reports").exists() else []
    print(f"  - Reports: {len(reports)} files in reports/")
