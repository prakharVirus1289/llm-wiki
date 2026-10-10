#!/usr/bin/env python3
"""
LLM-Wiki MCP Server: Native stdio JSON-RPC 2.0 Interface
Provides high-speed section reads, surgical AST patching, and Git PR staging.
Compatible with standard MCP tool callers and subagents.
"""

import sys
import json
import time
import sqlite3
import logging
import subprocess
from pathlib import Path
from logging.handlers import RotatingFileHandler

# Enforce UTF-8 on Windows stdout/stderr to support emojis and unicode in posts
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
WIKI_DIR = WORKSPACE_ROOT / "wiki"
DB_PATH = WORKSPACE_ROOT / "raw_firehose.db"
LOG_DIR = WORKSPACE_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "mcp_server.log"

# IMPORTANT: Logger MUST ONLY write to sys.stderr or file handler, NEVER stdout (stdout is reserved for JSON-RPC messages)
logger = logging.getLogger("llm_wiki_mcp")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    fh = RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.INFO)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

# Import our AST Splicer and SQLite utility
sys.path.append(str(WORKSPACE_ROOT / "scripts"))
from ast_splicer import ASTSplicer
from sqlite_manager import get_connection, get_backlinks, get_related_concepts, get_dangling_links

def handle_read_section(params: dict) -> dict:
    file_name = params.get("file", "")
    file_path = WIKI_DIR / file_name
    heading = params.get("heading", "")
    logger.info("MCP read_section called for file='%s', heading='%s'", file_name, heading)
    if not file_path.exists():
        logger.warning("MCP read_section target file '%s' not found", file_name)
        return {"error": f"File '{file_name}' does not exist in wiki/"}
    
    text = ASTSplicer.read_section(file_path, heading)
    if text is None:
        logger.info("MCP read_section: heading '%s' not found in %s", heading, file_name)
        return {"found": False, "content": ""}
    logger.info("MCP read_section: successfully read %d chars from '%s'", len(text), heading)
    return {"found": True, "content": text}

def handle_patch_section(params: dict) -> dict:
    file_name = params.get("file", "")
    file_path = WIKI_DIR / file_name
    heading = params.get("heading", "")
    content = params.get("content", "")
    logger.info("MCP patch_section called for file='%s', heading='%s' (%d chars content)", file_name, heading, len(content))
    
    ASTSplicer.splice_section(file_path, heading, content)
    errs = ASTSplicer.lint_file(file_path)
    if errs:
        logger.warning("MCP patch_section: lint warnings encountered in %s: %s", file_name, errs)
        return {"status": "warning", "lint_errors": errs}
    logger.info("MCP patch_section: section '%s' patched cleanly with 0 lint errors", heading)
    return {"status": "success", "message": f"Section '{heading}' updated cleanly in {file_name}."}

def handle_query_firehose_fts(params: dict) -> dict:
    keyword = params.get("keyword", "")
    limit = params.get("limit", 10)
    logger.info("MCP query_firehose_fts: keyword='%s', limit=%d", keyword, limit)
    t0 = time.perf_counter()
    
    if not DB_PATH.exists():
        logger.warning("raw_firehose.db does not exist yet")
        return {"results": [], "warning": "raw_firehose.db does not exist yet"}

    conn = get_connection(DB_PATH)
    try:
        cursor = conn.execute("""
            SELECT r.id, r.platform, r.title, r.canonical_url, snippet(firehose_fts, 1, '<b>', '</b>', '...', 15)
            FROM firehose_fts f
            JOIN raw_firehose r ON f.rowid = r.rowid
            WHERE firehose_fts MATCH ?
            LIMIT ?
        """, (keyword, limit))
        results = [
            {"id": row[0], "platform": row[1], "title": row[2], "url": row[3], "snippet": row[4]}
            for row in cursor.fetchall()
        ]
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("MCP query_firehose_fts: returned %d raw items in %.2f ms", len(results), elapsed_ms)
    finally:
        conn.close()
    return {"results": results}

def handle_query_wiki_sections(params: dict) -> dict:
    query = params.get("query", "")
    limit = params.get("limit", 5)
    logger.info("MCP query_wiki_sections: query='%s', limit=%d", query, limit)
    t0 = time.perf_counter()
    
    if not DB_PATH.exists():
        logger.warning("raw_firehose.db does not exist yet")
        return {"results": [], "warning": "raw_firehose.db does not exist yet"}

    conn = get_connection(DB_PATH)
    try:
        cursor = conn.execute("""
            SELECT file_path, heading, snippet(wiki_sections_fts, 2, '<b>', '</b>', '...', 12)
            FROM wiki_sections_fts
            WHERE wiki_sections_fts MATCH ?
            LIMIT ?;
        """, (query, limit))
        results = [
            {"file": row[0], "heading": row[1], "snippet": row[2]}
            for row in cursor.fetchall()
        ]
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("MCP query_wiki_sections: returned %d matching sections in %.2f ms", len(results), elapsed_ms)
    finally:
        conn.close()
    return {"results": results}

def handle_acquire_section_lease(params: dict) -> dict:
    file_path = params.get("file", "")
    section_slug = params.get("section", "")
    agent_id = params.get("agent_id", "default-agent")
    duration = params.get("duration_seconds", 300)
    logger.info("MCP acquire_section_lease: file='%s', section='%s', agent='%s', duration=%ds", 
                file_path, section_slug, agent_id, duration)
    
    expires_at = int(time.time()) + duration
    
    if not DB_PATH.exists():
        from sqlite_manager import init_db
        init_db(DB_PATH)

    conn = get_connection(DB_PATH)
    try:
        cursor = conn.execute("""
            INSERT INTO active_leases (file_path, section_slug, agent_id, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(file_path, section_slug) DO UPDATE SET
                agent_id = excluded.agent_id,
                expires_at = excluded.expires_at
            WHERE active_leases.expires_at < unixepoch();
        """, (file_path, section_slug, agent_id, expires_at))
        conn.commit()
        if cursor.rowcount > 0:
            logger.info("MCP acquire_section_lease: acquired lease for '%s' (expires %d)", section_slug, expires_at)
            return {"acquired": True, "expires_at": expires_at}
        else:
            logger.warning("MCP acquire_section_lease: lease conflict on '%s'", section_slug)
            return {"acquired": False, "reason": "Lease currently held by another agent"}
    except sqlite3.OperationalError as e:
        logger.error("MCP acquire_section_lease error: %s", e)
        return {"acquired": False, "reason": str(e)}
    finally:
        conn.close()


def handle_stage_git_pr(params: dict) -> dict:
    branch = params.get("branch", "pr/automated-update")
    title = params.get("title", "Autonomous AST section patch")
    diff_summary = params.get("diff_summary", "Autonomous update")
    logger.info("MCP stage_git_pr: branch='%s', title='%s'", branch, title)
    
    subprocess.run(["git", "checkout", "-B", branch], cwd=WORKSPACE_ROOT, check=True)
    subprocess.run(["git", "add", "wiki/"], cwd=WORKSPACE_ROOT, check=True)
    subprocess.run(["git", "commit", "-m", f"{title}\n\n{diff_summary}"], cwd=WORKSPACE_ROOT, check=True)
    logger.info("MCP stage_git_pr: committed changes to branch '%s'", branch)
    return {"staged": True, "branch": branch, "commit_msg": title}

def handle_get_backlinks(params: dict) -> dict:
    concept = params.get("concept", "")
    logger.info("MCP get_backlinks: concept='%s'", concept)
    if not concept:
        return {"error": "Parameter 'concept' is required"}
    if not DB_PATH.exists():
        return {"backlinks": [], "warning": "raw_firehose.db does not exist yet"}
    t0 = time.perf_counter()
    bls = get_backlinks(DB_PATH, concept)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info("MCP get_backlinks: concept='%s' found %d backlinks in %.2f ms", concept, len(bls), elapsed_ms)
    return {"concept": concept, "count": len(bls), "backlinks": bls}

def handle_get_related_concepts(params: dict) -> dict:
    concept = params.get("concept", "")
    depth = params.get("depth", 1)
    logger.info("MCP get_related_concepts: concept='%s', depth=%d", concept, depth)
    if not concept:
        return {"error": "Parameter 'concept' is required"}
    if not DB_PATH.exists():
        return {"related": [], "warning": "raw_firehose.db does not exist yet"}
    t0 = time.perf_counter()
    rel = get_related_concepts(DB_PATH, concept, depth=depth)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info("MCP get_related_concepts: concept='%s' found %d related in %.2f ms", concept, len(rel), elapsed_ms)
    return {"concept": concept, "related": rel}

def handle_get_dangling_links(params: dict) -> dict:
    limit = params.get("limit", 20)
    logger.info("MCP get_dangling_links: limit=%d", limit)
    if not DB_PATH.exists():
        return {"dangling": [], "warning": "raw_firehose.db does not exist yet"}
    t0 = time.perf_counter()
    dang = get_dangling_links(DB_PATH, limit=limit)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info("MCP get_dangling_links: returned %d voids in %.2f ms", len(dang), elapsed_ms)
    return {"dangling": dang}

TOOL_REGISTRY = {
    "read_section": handle_read_section,
    "patch_section": handle_patch_section,
    "query_firehose_fts": handle_query_firehose_fts,
    "query_wiki_sections": handle_query_wiki_sections,
    "acquire_section_lease": handle_acquire_section_lease,
    "stage_git_pr": handle_stage_git_pr,
    "get_backlinks": handle_get_backlinks,
    "get_related_concepts": handle_get_related_concepts,
    "get_dangling_links": handle_get_dangling_links
}

def main():
    logger.info("LLM-Wiki stdio MCP Server started (JSON-RPC 2.0 loop active)")
    while True:
        line = sys.stdin.readline()
        if not line:
            logger.info("LLM-Wiki stdio MCP Server received EOF on stdin; exiting cleanly.")
            break
        try:
            request = json.loads(line)
            req_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})
            logger.debug("Received MCP request: id=%s, method='%s'", req_id, method)

            # MCP tools/list support
            if method == "tools/list":
                tools = [
                    {"name": "read_section", "description": "Reads a specific markdown heading section without loading the whole file."},
                    {"name": "patch_section", "description": "Surgically splices a specific markdown heading section and lints the output."},
                    {"name": "query_firehose_fts", "description": "Searches raw scraped items via SQLite FTS5."},
                    {"name": "query_wiki_sections", "description": "Searches compiled wiki headings and content via SQLite FTS5 in <1ms."},
                    {"name": "acquire_section_lease", "description": "Acquires a concurrency lease on a target section."},
                    {"name": "stage_git_pr", "description": "Stages wiki edits to a dedicated Git PR branch."},
                    {"name": "get_backlinks", "description": "Finds all chapters and section headings citing a specific concept slug or domain/concept (e.g., 'sqlite_wal' or 'consensus/leases')."},
                    {"name": "get_related_concepts", "description": "Finds related and co-cited concepts within the knowledge graph."},
                    {"name": "get_dangling_links", "description": "Finds top cited concepts that lack a defining section in the wiki (knowledge gaps)."}
                ]
                response = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}
            elif method in TOOL_REGISTRY:
                result = TOOL_REGISTRY[method](params)
                response = {"jsonrpc": "2.0", "id": req_id, "result": result}
            elif method == "tools/call":
                # Standard MCP tools/call wrapper
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                if tool_name in TOOL_REGISTRY:
                    result = TOOL_REGISTRY[tool_name](tool_args)
                    response = {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}
                else:
                    logger.warning("Tool '%s' not registered in TOOL_REGISTRY", tool_name)
                    response = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"}}
            else:
                logger.warning("Method '%s' not recognized", method)
                response = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method '{method}' not found"}}
            
            raw_response = json.dumps(response) + "\n"
            sys.stdout.write(raw_response)
            sys.stdout.flush()
            logger.debug("Sent MCP response: id=%s (%d bytes)", req_id, len(raw_response))
        except Exception as e:
            logger.exception("Error handling MCP request: %s", e)
            err_resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
