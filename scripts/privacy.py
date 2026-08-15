#!/usr/bin/env python3
"""Public-boundary validation for Work Cubby manifests and ledgers."""
from __future__ import annotations

import re
from pathlib import Path


EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)"
)
PRIVATE_PATH_RE = re.compile(
    r"(?:/Users/[^/\s]+|/home/[^/\s]+|[A-Za-z]:\\Users\\[^\\\s]+)"
)
SECRET_PATTERNS = (
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+=*\b", re.IGNORECASE),
    re.compile(
        r"\b(?:password|passwd|api[_-]?key|access[_-]?token|secret)\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
)
PUBLIC_EVIDENCE_PREFIXES = ("https://", "commit:")


def validate_public_string(value: str, context: str) -> None:
    """Reject common PII, secret, and private-machine material."""
    findings = []
    if EMAIL_RE.search(value):
        findings.append("email address")
    if PHONE_RE.search(value):
        findings.append("phone number")
    if PRIVATE_PATH_RE.search(value):
        findings.append("private machine path")
    if any(pattern.search(value) for pattern in SECRET_PATTERNS):
        findings.append("credential or secret")
    if findings:
        raise ValueError(f"{context}: public-boundary violation ({', '.join(findings)})")


def validate_evidence(evidence: object, context: str) -> None:
    """Require evidence to be a public URL or an immutable commit reference."""
    if not isinstance(evidence, list):
        raise ValueError(f"{context}: evidence must be an array")
    for index, value in enumerate(evidence):
        if not isinstance(value, str):
            raise ValueError(f"{context}[{index}]: evidence must be a string")
        validate_public_string(value, f"{context}[{index}]")
        if not value.startswith(PUBLIC_EVIDENCE_PREFIXES):
            raise ValueError(
                f"{context}[{index}]: evidence must start with "
                f"{' or '.join(PUBLIC_EVIDENCE_PREFIXES)}"
            )


def validate_public_tree(root: Path) -> None:
    """Validate every public cubby manifest and work ledger."""
    cubbies = root / "cubbies"
    if not cubbies.exists():
        return
    for cubby in sorted(cubbies.iterdir()):
        if not cubby.is_dir() or cubby.name.startswith((".", "_")):
            continue
        manifest = cubby / "cubby.json"
        if manifest.exists():
            import json

            manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
            for field in ("display_name", "what_im_cooking"):
                value = manifest_data.get(field)
                if isinstance(value, str):
                    validate_public_string(
                        value,
                        f"{manifest.relative_to(root)}:{field}",
                    )
        ledger = cubby / "show-and-tell" / "work-ledger.jsonl"
        if not ledger.exists():
            continue
        for line_number, line in enumerate(
            ledger.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            record = json.loads(line)
            payload = record.get("payload", {})
            for field in ("task", "summary", "source", "purpose", "display_name"):
                value = payload.get(field)
                if isinstance(value, str):
                    validate_public_string(
                        value,
                        f"{ledger.relative_to(root)}:{line_number}:{field}",
                    )
            if record.get("kind") == "cubby.clock_out":
                validate_evidence(
                    payload.get("evidence", []),
                    f"{ledger.relative_to(root)}:{line_number}:evidence",
                )
