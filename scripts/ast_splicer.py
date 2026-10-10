#!/usr/bin/env python3
"""
AST Splicer: Surgical Section Byte Replacement for Markdown
Zero semantic drift. Replaces target sections while keeping surrounding bytes identical.
Uses pure standard library Python with zero external pip dependencies.
"""

import sys
import os
import re
import json
import logging
import argparse
import tempfile
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Optional

# Enforce UTF-8 on Windows stdout/stderr to support emojis and unicode in posts
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "ast_splicer.log"

logger = logging.getLogger("ast_splicer")
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


class ASTSplicer:
    @staticmethod
    def inspect_sections(file_path: Path) -> List[Dict]:
        logger.debug("Inspecting sections in %s", file_path)
        content = file_path.read_text(encoding="utf-8")
        heading_regex = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
        matches = list(heading_regex.finditer(content))
        
        sections = []
        for i, match in enumerate(matches):
            level = len(match.group(1))
            title = match.group(2).strip()
            start_pos = match.start()
            
            # End position is start of next heading at same or higher level, or EOF
            end_pos = len(content)
            for next_match in matches[i+1:]:
                next_level = len(next_match.group(1))
                if next_level <= level:
                    end_pos = next_match.start()
                    break
            
            sections.append({
                "level": level,
                "title": title,
                "start_byte": start_pos,
                "end_byte": end_pos,
                "length": end_pos - start_pos
            })
        logger.debug("Discovered %d sections in %s", len(sections), file_path.name)
        return sections

    @staticmethod
    def read_section(file_path: Path, heading_title: str) -> Optional[str]:
        logger.debug("Reading section '%s' from %s", heading_title, file_path.name)
        sections = ASTSplicer.inspect_sections(file_path)
        content = file_path.read_text(encoding="utf-8")
        norm_target = heading_title.lower().strip().lstrip("#").strip()
        
        for sec in sections:
            if sec["title"].lower().strip() == norm_target:
                logger.info("Found section '%s' (%d bytes, range %d-%d) in %s", 
                            sec['title'], sec['length'], sec['start_byte'], sec['end_byte'], file_path.name)
                return content[sec["start_byte"]:sec["end_byte"]]
        logger.warning("Section '%s' not found in %s", heading_title, file_path.name)
        return None

    @staticmethod
    def splice_section(file_path: Path, heading_title: str, new_content: str) -> bool:
        logger.info("Initiating surgical splice of '%s' in %s", heading_title, file_path.name)
        if not file_path.exists():
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(new_content.strip() + "\n", encoding="utf-8")
            logger.info("Created new file %s with section '%s'", file_path.name, heading_title)
            return True

        sections = ASTSplicer.inspect_sections(file_path)
        content = file_path.read_text(encoding="utf-8")
        norm_target = heading_title.lower().strip().lstrip("#").strip()
        
        target_sec = None
        for sec in sections:
            if sec["title"].lower().strip() == norm_target:
                target_sec = sec
                break
                
        if not target_sec:
            # If section doesn't exist, append cleanly at end of file
            logger.info("Section '%s' does not exist in %s; appending to EOF", heading_title, file_path.name)
            separator = "\n\n" if content and not content.endswith("\n\n") else ""
            final_content = content + separator + new_content.strip() + "\n"
        else:
            # Surgical replacement of exact byte slice
            logger.info("Surgically replacing %d bytes for section '%s' in %s", 
                        target_sec['length'], target_sec['title'], file_path.name)
            before = content[:target_sec["start_byte"]]
            after = content[target_sec["end_byte"]:]
            final_content = before + new_content.strip() + "\n\n" + after.lstrip("\n")
        
        # Atomic file write to avoid torn pages on Windows with explicit disk sync
        dir_name = file_path.parent
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=dir_name, delete=False) as tf:
            tf.write(final_content)
            tf.flush()
            os.fsync(tf.fileno())
            temp_name = tf.name
        
        # Atomic replace
        os.replace(temp_name, file_path)
        logger.info("Atomic fsync replace complete: %s updated cleanly", file_path.name)
        return True

    @staticmethod
    def lint_file(file_path: Path) -> List[str]:
        logger.debug("Linting file syntax for %s", file_path.name)
        content = file_path.read_text(encoding="utf-8")
        errors = []
        
        # Check 1: Unclosed code blocks
        if content.count("```") % 2 != 0:
            errors.append("Unclosed fenced code block (odd number of ```)")
            
        # Check 2: Malformed wikilinks
        open_wikilinks = content.count("[[")
        close_wikilinks = content.count("]]")
        if open_wikilinks != close_wikilinks:
            errors.append(f"Mismatched wikilink brackets: {open_wikilinks} '[[' vs {close_wikilinks} ']]'")
            
        if errors:
            logger.warning("Lint failed for %s with %d errors: %s", file_path.name, len(errors), errors)
        else:
            logger.debug("Lint passed cleanly for %s (0 errors)", file_path.name)
        return errors

def main():
    parser = argparse.ArgumentParser(description="AST Markdown Splicer")
    subparsers = parser.add_subparsers(dest="subcommand")

    inspect_p = subparsers.add_parser("inspect")
    inspect_p.add_argument("--file", required=True, type=Path)

    read_p = subparsers.add_parser("read")
    read_p.add_argument("--file", required=True, type=Path)
    read_p.add_argument("--heading", required=True, type=str)

    splice_p = subparsers.add_parser("splice")
    splice_p.add_argument("--file", required=True, type=Path)
    splice_p.add_argument("--heading", required=True, type=str)
    splice_p.add_argument("--content-file", required=True, type=Path)

    lint_p = subparsers.add_parser("lint")
    lint_p.add_argument("--file", required=True, type=Path)

    args = parser.parse_args()

    if args.subcommand == "inspect":
        secs = ASTSplicer.inspect_sections(args.file)
        print(json.dumps(secs, indent=2))
    elif args.subcommand == "read":
        txt = ASTSplicer.read_section(args.file, args.heading)
        if txt:
            print(txt)
        else:
            print(f"Error: Heading '{args.heading}' not found in {args.file}.", file=sys.stderr)
            sys.exit(1)
    elif args.subcommand == "splice":
        new_md = args.content_file.read_text(encoding="utf-8")
        ASTSplicer.splice_section(args.file, args.heading, new_md)
        print(f"[OK] Surgically spliced section '{args.heading}' in {args.file}")
    elif args.subcommand == "lint":
        errs = ASTSplicer.lint_file(args.file)
        if errs:
            for e in errs:
                print(f"[LINT ERROR] {e}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"[OK] {args.file} passed syntax & wikilink linting.")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
