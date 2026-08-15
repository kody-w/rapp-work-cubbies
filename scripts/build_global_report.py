#!/usr/bin/env python3
"""Build privacy-safe global Work Cubby JSON and static HTML reports."""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
JSON_OUTPUT = DOCS / "global.json"
HTML_OUTPUT = DOCS / "index.html"
sys.path.insert(0, str(ROOT))
import work_cubby  # noqa: E402
from scripts.privacy import validate_public_tree  # noqa: E402


def utc_now() -> str:
    """Return an RFC-3339 UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def elapsed_hms(seconds: int) -> str:
    """Render elapsed seconds as HH:MM:SS."""
    return work_cubby.elapsed_hms(seconds)


def cubby_paths(root: Path) -> list[Path]:
    """Return public member cubbies in stable order."""
    cubbies = root / "cubbies"
    if not cubbies.exists():
        return []
    return [
        path for path in sorted(cubbies.iterdir())
        if path.is_dir() and not path.name.startswith((".", "_"))
    ]


def read_records(cubby: Path) -> list[dict]:
    """Read one cubby's ledger."""
    ledger = cubby / "show-and-tell" / "work-ledger.jsonl"
    if not ledger.exists():
        return []
    return [
        json.loads(line)
        for line in ledger.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def member_report(root: Path, cubby: Path) -> tuple[dict, list[dict], list[dict]]:
    """Build one member summary plus completed and active shift rows."""
    manifest = json.loads((cubby / "cubby.json").read_text(encoding="utf-8"))
    records = read_records(cubby)
    clock_ins: dict[str, dict] = {}
    completed = []
    for record in records:
        payload = record.get("payload", {})
        shift_id = payload.get("shift_id")
        if record.get("kind") == "cubby.clock_in" and shift_id:
            clock_ins[shift_id] = record
        elif record.get("kind") == "cubby.clock_out" and shift_id:
            started = clock_ins.pop(shift_id, None)
            completed.append({
                "member_id": cubby.name,
                "display_name": manifest["display_name"],
                "shift_id": shift_id,
                "task": (started or {}).get("payload", {}).get("task", ""),
                "source": (started or {}).get("payload", {}).get("source", ""),
                "started_at": payload.get("started_at"),
                "ended_at": payload.get("ended_at"),
                "elapsed_seconds": int(payload.get("elapsed_seconds", 0) or 0),
                "elapsed_hms": payload.get("elapsed_hms", "00:00:00"),
                "summary": payload.get("summary", ""),
                "evidence": payload.get("evidence", []),
                "reconstructed": bool(
                    record.get("reconstructed")
                    or (started or {}).get("reconstructed")
                ),
                "sha256": record.get("sha256"),
            })

    active = [{
        "member_id": cubby.name,
        "display_name": manifest["display_name"],
        "shift_id": shift_id,
        "task": record.get("payload", {}).get("task", ""),
        "source": record.get("payload", {}).get("source", ""),
        "started_at": record.get("utc"),
        "reconstructed": bool(record.get("reconstructed")),
        "sha256": record.get("sha256"),
    } for shift_id, record in sorted(clock_ins.items())]

    observed_seconds = sum(
        row["elapsed_seconds"] for row in completed if not row["reconstructed"]
    )
    reconstructed_seconds = sum(
        row["elapsed_seconds"] for row in completed if row["reconstructed"]
    )
    member = {
        "member_id": cubby.name,
        "display_name": manifest["display_name"],
        "github_login": manifest["github_login"],
        "purpose": manifest["what_im_cooking"],
        "joined_at": manifest["created_at"],
        "completed_shifts": len(completed),
        "active_shifts": len(active),
        "observed_seconds": observed_seconds,
        "observed_hms": elapsed_hms(observed_seconds),
        "reconstructed_seconds": reconstructed_seconds,
        "reconstructed_hms": elapsed_hms(reconstructed_seconds),
        "total_seconds": observed_seconds + reconstructed_seconds,
        "total_hms": elapsed_hms(observed_seconds + reconstructed_seconds),
        "evidence_count": sum(len(row["evidence"]) for row in completed),
        "ledger_records": len(records),
        "ledger_head_sha256": records[-1].get("sha256") if records else None,
        "cubby_manifest": (
            f"https://raw.githubusercontent.com/kody-w/rapp-work-cubbies/main/"
            f"cubbies/{cubby.name}/cubby.json"
        ),
    }
    return member, completed, active


def semantic_report(root: Path) -> dict:
    """Aggregate all public member ledgers without wall-clock-derived values."""
    validate_public_tree(root)
    members = []
    completed = []
    active = []
    for cubby in cubby_paths(root):
        member, member_completed, member_active = member_report(root, cubby)
        members.append(member)
        completed.extend(member_completed)
        active.extend(member_active)

    completed.sort(
        key=lambda row: (row.get("ended_at") or "", row["member_id"]),
        reverse=True,
    )
    active.sort(key=lambda row: (row.get("started_at") or "", row["member_id"]))
    observed_seconds = sum(row["observed_seconds"] for row in members)
    reconstructed_seconds = sum(row["reconstructed_seconds"] for row in members)
    return {
        "schema": "rapp-work-report/1.0",
        "neighborhood": {
            "name": "work-cubbies",
            "address": (
                "rapp://neighborhood/work-cubbies@"
                "github.com/kody-w/rapp-work-cubbies"
            ),
            "repository": "https://github.com/kody-w/rapp-work-cubbies",
        },
        "privacy": {
            "classification": "public-sanitized",
            "contains_pii": False,
            "contains_private_transcripts": False,
            "evidence_policy": "public https URLs and immutable commit references only",
        },
        "totals": {
            "members": len(members),
            "completed_shifts": len(completed),
            "active_shifts": len(active),
            "observed_seconds": observed_seconds,
            "observed_hms": elapsed_hms(observed_seconds),
            "reconstructed_seconds": reconstructed_seconds,
            "reconstructed_hms": elapsed_hms(reconstructed_seconds),
            "total_seconds": observed_seconds + reconstructed_seconds,
            "total_hms": elapsed_hms(observed_seconds + reconstructed_seconds),
            "evidence_count": sum(row["evidence_count"] for row in members),
        },
        "members": members,
        "active_shifts": active,
        "recent_completed_shifts": completed[:100],
    }


def build_report(root: Path, current: dict | None = None) -> dict:
    """Add a stable generation timestamp to the semantic report."""
    report = semantic_report(root)
    current_semantic = (
        {key: value for key, value in current.items() if key != "generated_at"}
        if isinstance(current, dict) else None
    )
    report["generated_at"] = (
        current.get("generated_at")
        if current_semantic == report
        else utc_now()
    )
    return report


def evidence_html(values: list[str]) -> str:
    """Render public evidence links and commit references."""
    items = []
    for value in values:
        escaped = html.escape(value)
        if value.startswith("https://"):
            items.append(
                f'<li><a href="{escaped}" rel="noopener">{escaped}</a></li>'
            )
        else:
            items.append(f"<li><code>{escaped}</code></li>")
    return "<ul>" + "".join(items) + "</ul>" if items else "<p>None recorded.</p>"


def render_html(report: dict) -> str:
    """Render a static, dependency-free global work report."""
    totals = report["totals"]
    active = "".join(
        f"""<article class="shift active"><h3>{html.escape(row["display_name"])}</h3>
<p><strong>Clocked in:</strong> {html.escape(row["started_at"])}</p>
<p>{html.escape(row["task"])}</p></article>"""
        for row in report["active_shifts"]
    ) or '<p class="empty">No active shifts.</p>'
    members = "".join(
        f"""<article class="member"><h3>{html.escape(row["display_name"])}</h3>
<p><code>{html.escape(row["member_id"])}</code> · @{html.escape(row["github_login"])}</p>
<p>{html.escape(row["purpose"])}</p>
<dl><dt>Observed</dt><dd>{row["observed_hms"]}</dd>
<dt>Reconstructed</dt><dd>{row["reconstructed_hms"]}</dd>
<dt>Total</dt><dd>{row["total_hms"]}</dd>
<dt>Completed shifts</dt><dd>{row["completed_shifts"]}</dd></dl>
<p class="hash">Ledger head: <code>{html.escape(row["ledger_head_sha256"] or "none")}</code></p>
</article>"""
        for row in report["members"]
    )
    recent = "".join(
        f"""<article class="shift"><h3>{html.escape(row["display_name"])} · {html.escape(row["elapsed_hms"])}</h3>
<p><strong>{html.escape(row["task"])}</strong></p>
<p>{html.escape(row["summary"])}</p>
<p>{html.escape(row["started_at"] or "")} → {html.escape(row["ended_at"] or "")}
{" · reconstructed" if row["reconstructed"] else " · observed"}</p>
<details><summary>Evidence ({len(row["evidence"])})</summary>{evidence_html(row["evidence"])}</details>
</article>"""
        for row in report["recent_completed_shifts"]
    ) or '<p class="empty">No completed shifts yet.</p>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Work Cubbies · Global Public Report</title>
<style>
:root{{--bg:#0d1117;--panel:#161b22;--line:#30363d;--text:#d8dee9;--muted:#8b949e;--blue:#8cc8ff;--green:#7ee787}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 system-ui;padding:24px}}
main{{max-width:1100px;margin:auto}}a{{color:var(--blue)}}code{{word-break:break-all}}h1,h2{{color:var(--blue)}}
.lead{{color:var(--muted)}}.totals,.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}}
.total,.member,.shift{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}}
.total strong{{display:block;font-size:1.7rem;color:var(--green)}}dl{{display:grid;grid-template-columns:1fr auto;gap:5px 12px}}
dt{{color:var(--muted)}}dd{{margin:0}}.active{{border-color:var(--green)}}.hash{{font-size:.78rem;color:var(--muted)}}
.empty{{color:var(--muted)}}footer{{margin-top:32px;color:var(--muted);font-size:.9rem}}
</style></head><body><main>
<h1>Work Cubbies</h1>
<p class="lead">Global, privacy-safe reporting of important agent work. Observed and reconstructed hours are always separate.</p>
<p><a href="https://github.com/kody-w/rapp-work-cubbies">Join the neighborhood</a> ·
<a href="global.json">Machine-readable report</a></p>
<section><h2>Global totals</h2><div class="totals">
<div class="total"><strong>{totals["members"]}</strong>members</div>
<div class="total"><strong>{totals["active_shifts"]}</strong>active shifts</div>
<div class="total"><strong>{totals["observed_hms"]}</strong>observed work</div>
<div class="total"><strong>{totals["reconstructed_hms"]}</strong>reconstructed work</div>
<div class="total"><strong>{totals["total_hms"]}</strong>total recorded</div>
<div class="total"><strong>{totals["evidence_count"]}</strong>evidence references</div>
</div></section>
<section><h2>Clocked in now</h2><div class="grid">{active}</div></section>
<section><h2>Members</h2><div class="grid">{members}</div></section>
<section><h2>Recent completed shifts</h2><div class="grid">{recent}</div></section>
<footer>Generated {html.escape(report["generated_at"])} · Public-sanitized · No PII or private transcripts.</footer>
</main></body></html>
"""


def write_atomic(path: Path, content: str) -> None:
    """Atomically write one generated report file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """Build or verify the committed global report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    current = None
    if JSON_OUTPUT.exists():
        current = json.loads(JSON_OUTPUT.read_text(encoding="utf-8"))
    report = build_report(ROOT, current)
    json_text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    html_text = render_html(report)
    if args.check:
        stale = (
            not JSON_OUTPUT.exists()
            or not HTML_OUTPUT.exists()
            or JSON_OUTPUT.read_text(encoding="utf-8") != json_text
            or HTML_OUTPUT.read_text(encoding="utf-8") != html_text
        )
        if stale:
            print("global public report is stale", file=sys.stderr)
            return 1
        print("global public report is current")
        return 0
    write_atomic(JSON_OUTPUT, json_text)
    write_atomic(HTML_OUTPUT, html_text)
    print(
        f"reported {report['totals']['members']} member(s), "
        f"{report['totals']['completed_shifts']} completed shift(s), "
        f"{report['totals']['active_shifts']} active shift(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

