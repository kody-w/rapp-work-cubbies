#!/usr/bin/env python3
"""Validate cubby manifests, append-only ledgers, and PR ownership boundaries."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import work_cubby  # noqa: E402
from scripts.privacy import validate_public_tree  # noqa: E402


def changed_files(base_sha: str) -> list[str]:
    """Return paths changed from the pull request base."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_sha}...HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def validate_changed_paths(head_ref: str, paths: list[str]) -> str | None:
    """Ensure a cubby branch changes only its member directory + derived index."""
    if not head_ref.startswith("cubby/"):
        return None
    parts = head_ref.split("/")
    if len(parts) < 3:
        raise ValueError("cubby branch must be cubby/<member-id>/<purpose>")
    member = parts[1]
    work_cubby.validate_slug(member)
    allowed_prefix = f"cubbies/{member}/"
    allowed_shared = {"super-rar/index.json"}
    forbidden = [
        path for path in paths
        if not path.startswith(allowed_prefix) and path not in allowed_shared
    ]
    if forbidden:
        raise PermissionError(
            f"branch {head_ref} cannot change paths outside {allowed_prefix}: "
            + ", ".join(forbidden)
        )
    return member


def validate_append_only(base_sha: str, member: str, paths: list[str]) -> None:
    """Require the current ledger to retain the base ledger byte-for-byte."""
    ledger = f"cubbies/{member}/show-and-tell/work-ledger.jsonl"
    if ledger not in paths:
        return
    current = (ROOT / ledger).read_bytes()
    result = subprocess.run(
        ["git", "show", f"{base_sha}:{ledger}"],
        cwd=ROOT,
        capture_output=True,
    )
    if result.returncode == 0 and not current.startswith(result.stdout):
        raise ValueError(f"{ledger} is not append-only")


def validate_actor(member: str | None) -> None:
    """Bind a new/changed cubby to the GitHub actor declared in its manifest."""
    if not member:
        return
    actor = os.environ.get("GITHUB_ACTOR")
    if not actor:
        return
    manifest = json.loads(
        (ROOT / "cubbies" / member / "cubby.json").read_text(encoding="utf-8")
    )
    if manifest.get("github_login") != actor:
        raise PermissionError(
            f"{member} belongs to {manifest.get('github_login')}, not {actor}"
        )


def main() -> int:
    """Run all validation gates."""
    try:
        result = work_cubby.verify_all()
        validate_public_tree(ROOT)
        base_sha = os.environ.get("GITHUB_BASE_SHA")
        head_ref = os.environ.get("GITHUB_HEAD_REF", "")
        if base_sha:
            paths = changed_files(base_sha)
            member = validate_changed_paths(head_ref, paths)
            validate_append_only(base_sha, member, paths) if member else None
            validate_actor(member)
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "rebuild_super_rar.py"), "--check"],
            cwd=ROOT,
            check=True,
        )
        print(json.dumps(result, indent=2))
        return 0
    except Exception as error:
        print(f"validation failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
