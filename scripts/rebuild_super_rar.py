#!/usr/bin/env python3
"""Build the neighborhood's canonical rapp-super-rar/1.0 index."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CUBBIES = ROOT / "cubbies"
OUTPUT = ROOT / "super-rar" / "index.json"
NEIGHBORHOOD_RAPPID = (
    "rappid:@kody-w/work-cubbies:"
    "2a7202d8c504431d9cd53e289d0fbea9170eca6ade50e19ad332dd0c530e18d1"
)
KINDS = {
    "agent": ("agents", "*_agent.py", True),
    "organ": ("organs", "*_organ.py", False),
    "sense": ("senses", "*.py", False),
    "rapplication": ("rapplications", "*", False),
    "neighborhood": ("neighborhoods", "*", False),
    "egg": ("eggs", "*.egg", False),
}


def now_iso() -> str:
    """Return an RFC-3339 UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def purpose(path: Path) -> str:
    """Extract a short public purpose without interpreting code."""
    if path.suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            text = data.get("purpose") or data.get("display_name")
            if isinstance(text, str):
                return text[:140]
        except (OSError, json.JSONDecodeError):
            pass
    return path.name[:140]


def entries() -> list[dict]:
    """Index every supported anatomy artifact by sha256."""
    rows = []
    if not CUBBIES.exists():
        return rows
    for cubby in sorted(CUBBIES.iterdir()):
        if not cubby.is_dir() or cubby.name.startswith((".", "_")):
            continue
        for kind, (subdir, pattern, streamable) in KINDS.items():
            directory = cubby / subdir
            if not directory.exists():
                continue
            for path in sorted(directory.glob(pattern)):
                if not path.is_file() or path.name.startswith((".", "_")):
                    continue
                rows.append({
                    "kind": kind,
                    "name": path.name,
                    "cubby": cubby.name,
                    "path": path.relative_to(ROOT).as_posix(),
                    "streamable": streamable,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "purpose": purpose(path),
                })
    return rows


def build(current: dict | None = None) -> dict:
    """Build a stable index, preserving built_at when entries are unchanged."""
    rows = entries()
    histogram = dict(sorted(Counter(row["kind"] for row in rows).items()))
    unchanged = bool(
        current
        and current.get("entries") == rows
        and current.get("by_kind") == histogram
        and current.get("count") == len(rows)
    )
    return {
        "schema": "rapp-super-rar/1.0",
        "neighborhood_rappid": NEIGHBORHOOD_RAPPID,
        "built_at": current.get("built_at") if unchanged else now_iso(),
        "note": "Public Work Cubbies neighborhood index; work ledgers remain show-and-tell and are not streamable.",
        "count": len(rows),
        "by_kind": histogram,
        "entries": rows,
    }


def main() -> int:
    """Write or check the generated super-RAR index."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    current = None
    if OUTPUT.exists():
        current = json.loads(OUTPUT.read_text(encoding="utf-8"))
    expected = build(current)
    rendered = json.dumps(expected, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print("super-rar/index.json is stale", file=sys.stderr)
            return 1
        print("super-rar/index.json is current")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_name(f".{OUTPUT.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, OUTPUT)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"indexed {len(expected['entries'])} artifact(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

