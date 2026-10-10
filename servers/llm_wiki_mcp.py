#!/usr/bin/env python3
"""
LLM-Wiki MCP Server: Native stdio JSON-RPC 2.0 Interface
Exposes a complete, isolated blackbox API for LLM-Wiki:
- Firehose candidate ingestion & URL deduplication
- FTS5 keyword and fastembed hybrid vector search
- Surgical AST section reads & patches
- Knowledge graph inspection (backlinks, co-citations, dangling links)
- Atomic Git commit & remote push

Database access is completely encapsulated inside the sqlite_manager module.
"""

import sys
import json
import logging
import subprocess
from pathlib import Path
from logging.handlers import RotatingFileHandler

# Enforce UTF-8 on Windows stdout/stderr
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

# Import internal modular components
sys.path.append(str(WORKSPACE_ROOT / "scripts"))
from ast_splicer import ASTSplicer
from sqlite_manager import (
    ingest_candidates,
    query_firehose_raw,
    search_hybrid,
    get_backlinks,
    get_related_concepts,
    get_dangling_links,
)


# ==============================================================================
# Tool Implementations (Blackbox Handlers)
# ==============================================================================

def handle_firehose_ingest(params: dict) -> dict:
    """Ingests raw scraped candidates into raw_firehose with automatic canonical URL deduplication via sqlite_manager."""
    items = params.get("items", [])
    logger.info("MCP firehose_ingest: processing %d items", len(items))
    return ingest_candidates(DB_PATH, items)


def handle_firehose_query(params: dict) -> dict:
    """FTS5 search across raw scraped items via sqlite_manager."""
    keyword = params.get("keyword", "")
    limit = params.get("limit", 10)
    logger.info("MCP firehose_query: keyword='%s', limit=%d", keyword, limit)
    results = query_firehose_raw(DB_PATH, keyword, limit)
    return {"keyword": keyword, "count": len(results), "results": results}


def handle_search_hybrid(params: dict) -> dict:
    """Fuses FTS5 lexical ranking with fastembed vector cosine similarity via sqlite_manager."""
    query_text = params.get("query", "")
    limit = params.get("limit", 10)
    logger.info("MCP search_hybrid: query='%s', limit=%d", query_text, limit)
    results = search_hybrid(DB_PATH, query_text, limit)
    return {"query": query_text, "results": results}


def handle_read_section(params: dict) -> dict:
    """Surgically reads only the lines under a specific heading from wiki/*.md."""
    file_name = params.get("file", "")
    file_path = WIKI_DIR / file_name
    heading = params.get("heading", "")
    logger.info("MCP read_section: file='%s', heading='%s'", file_name, heading)

    if not file_path.exists():
        return {"found": False, "error": f"File '{file_name}' does not exist in wiki/"}

    text = ASTSplicer.read_section(file_path, heading)
    if text is None:
        return {"found": False, "content": "", "message": f"Heading '{heading}' not found in {file_name}"}

    return {"found": True, "file": file_name, "heading": heading, "content": text}


def handle_patch_section(params: dict) -> dict:
    """Surgically replaces a section in wiki/*.md, lints the file, and auto-updates search embeddings."""
    file_name = params.get("file", "")
    file_path = WIKI_DIR / file_name
    heading = params.get("heading", "")
    content = params.get("content", "")
    logger.info("MCP patch_section: file='%s', heading='%s' (%d chars)", file_name, heading, len(content))

    try:
        ASTSplicer.splice_section(file_path, heading, content)
        errs = ASTSplicer.lint_file(file_path)
        return {
            "status": "success",
            "file": file_name,
            "heading": heading,
            "lint_warnings": errs,
            "message": f"Section '{heading}' spliced cleanly in {file_name} with embeddings updated."
        }
    except Exception as e:
        logger.exception("MCP patch_section error: %s", e)
        return {"status": "error", "error": str(e)}


def handle_get_graph(params: dict) -> dict:
    """Inspects backlinks, co-citations, or dangling links via sqlite_manager."""
    action = params.get("action", "backlinks")
    concept = params.get("concept", "")
    limit = params.get("limit", 20)
    logger.info("MCP get_graph: action='%s', concept='%s'", action, concept)

    if action == "backlinks":
        bls = get_backlinks(DB_PATH, concept)
        return {"action": "backlinks", "concept": concept, "results": bls}
    elif action == "related":
        rel = get_related_concepts(DB_PATH, concept)
        return {"action": "related", "concept": concept, "results": rel}
    elif action == "dangling":
        dang = get_dangling_links(DB_PATH, limit=limit)
        return {"action": "dangling", "results": dang}
    else:
        return {"error": f"Unknown graph action '{action}'. Use 'backlinks', 'related', or 'dangling'."}


def handle_git_commit_and_push(params: dict) -> dict:
    """Stages files, commits atomically, and pushes to remote tracking branch."""
    file_name = params.get("file", "wiki/")
    message = params.get("message", "feat: autonomous section patch")
    branch = params.get("branch", "main")
    logger.info("MCP git_commit_and_push: file='%s', msg='%s', branch='%s'", file_name, message, branch)

    try:
        subprocess.run(["git", "add", file_name], cwd=WORKSPACE_ROOT, check=True)
        res_commit = subprocess.run(["git", "commit", "-m", message], cwd=WORKSPACE_ROOT, capture_output=True, text=True)
        res_push = subprocess.run(["git", "push", "origin", branch], cwd=WORKSPACE_ROOT, capture_output=True, text=True)
        return {
            "status": "success",
            "branch": branch,
            "commit_output": res_commit.stdout.strip(),
            "push_output": res_push.stdout.strip()
        }
    except subprocess.CalledProcessError as e:
        logger.error("Git error: %s", e)
        return {"status": "error", "error": str(e)}


# ==============================================================================
# Tool Registry & JSON-RPC Dispatcher
# ==============================================================================

TOOL_REGISTRY = {
    # Canonical tool names
    "llm_wiki_firehose_ingest": handle_firehose_ingest,
    "llm_wiki_firehose_query": handle_firehose_query,
    "llm_wiki_search_hybrid": handle_search_hybrid,
    "llm_wiki_read_section": handle_read_section,
    "llm_wiki_patch_section": handle_patch_section,
    "llm_wiki_get_graph": handle_get_graph,
    "llm_wiki_git_commit_and_push": handle_git_commit_and_push,

    # Short aliases for convenience
    "firehose_ingest": handle_firehose_ingest,
    "firehose_query": handle_firehose_query,
    "search_hybrid": handle_search_hybrid,
    "read_section": handle_read_section,
    "patch_section": handle_patch_section,
    "get_graph": handle_get_graph,
    "git_commit_and_push": handle_git_commit_and_push,
}

TOOL_SCHEMAS = [
    {
        "name": "llm_wiki_firehose_ingest",
        "description": "Ingests newly scraped candidate items into the central firehose database, performing automatic canonical URL deduplication.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "List of post dictionaries containing canonical_id, platform, title, content, and canonical_url"
                }
            },
            "required": ["items"]
        }
    },
    {
        "name": "llm_wiki_firehose_query",
        "description": "Searches raw scraped internet posts (Reddit, Twitter, GitHub) by keyword using SQLite FTS5.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Search keyword or term"},
                "limit": {"type": "integer", "default": 10}
            },
            "required": ["keyword"]
        }
    },
    {
        "name": "llm_wiki_search_hybrid",
        "description": "Searches textbook chapters using hybrid search (FTS5 lexical rank + fastembed CPU vector semantic similarity fused via RRF).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query or question"},
                "limit": {"type": "integer", "default": 10}
            },
            "required": ["query"]
        }
    },
    {
        "name": "llm_wiki_read_section",
        "description": "Surgically reads only the lines under a specific heading from wiki/*.md without loading the entire chapter file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "Markdown chapter file name (e.g. 'caching.md')"},
                "heading": {"type": "string", "description": "Exact heading title to read (e.g. 'LRU Eviction Policy')"}
            },
            "required": ["file", "heading"]
        }
    },
    {
        "name": "llm_wiki_patch_section",
        "description": "Surgically replaces a specific markdown heading section, validates AST syntax/links, and auto-updates search vector embeddings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "Markdown chapter file name (e.g. 'caching.md')"},
                "heading": {"type": "string", "description": "Exact heading title to patch"},
                "content": {"type": "string", "description": "Replacement markdown content for the section"}
            },
            "required": ["file", "heading", "content"]
        }
    },
    {
        "name": "llm_wiki_get_graph",
        "description": "Inspects the textbook knowledge graph: backlinks (reverse citations), related concepts (co-citations), or dangling links (missing concept gaps).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["backlinks", "related", "dangling"], "default": "backlinks"},
                "concept": {"type": "string", "description": "Concept slug to query (required for backlinks/related)"},
                "limit": {"type": "integer", "default": 20}
            },
            "required": ["action"]
        }
    },
    {
        "name": "llm_wiki_git_commit_and_push",
        "description": "Atomically stages modified chapter files, commits to Git, and pushes to remote GitHub repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "default": "wiki/", "description": "Relative path to file to stage"},
                "message": {"type": "string", "description": "Git commit message"},
                "branch": {"type": "string", "default": "main"}
            },
            "required": ["message"]
        }
    }
]


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

            # MCP tools/list
            if method == "tools/list":
                response = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOL_SCHEMAS}}

            # Direct method dispatch
            elif method in TOOL_REGISTRY:
                result = TOOL_REGISTRY[method](params)
                response = {"jsonrpc": "2.0", "id": req_id, "result": result}

            # Standard MCP tools/call wrapper
            elif method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                if tool_name in TOOL_REGISTRY:
                    result = TOOL_REGISTRY[tool_name](tool_args)
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(result, indent=2)}]
                        }
                    }
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
