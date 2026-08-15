#!/usr/bin/env python3
"""Append-only work cubbies for the Work Cubbies neighborhood."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_ROOT = Path(__file__).resolve().parent
NEIGHBORHOOD_NAME = "work-cubbies"
NEIGHBORHOOD_ADDRESS = (
    "rapp://neighborhood/work-cubbies@github.com/kody-w/rapp-work-cubbies"
)
NEIGHBORHOOD_RAPPID = (
    "rappid:@kody-w/work-cubbies:"
    "2a7202d8c504431d9cd53e289d0fbea9170eca6ade50e19ad332dd0c530e18d1"
)
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
REQUIRED_MANIFEST_FIELDS = {
    "schema",
    "github_login",
    "slug",
    "display_name",
    "what_im_cooking",
    "created_at",
    "estate",
    "streamable",
}


def root_path() -> Path:
    """Return the repository or local brainstem root."""
    return Path(os.environ.get("WORK_CUBBY_ROOT", DEFAULT_ROOT)).expanduser().resolve()


def cubby_dir(member: str) -> Path:
    """Return one member's cubby directory without accepting arbitrary paths."""
    validate_slug(member)
    return root_path() / "cubbies" / member


def ledger_path(member: str) -> Path:
    """Return one member's append-only work ledger."""
    return cubby_dir(member) / "show-and-tell" / "work-ledger.jsonl"


def validate_slug(value: str) -> None:
    """Reject unsafe member/cubby handles."""
    if not SLUG_RE.fullmatch(value or ""):
        raise ValueError(
            "member must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
        )


def enforce_actor(member: str) -> None:
    """Refuse writes to another member when an actor boundary is declared."""
    actor = os.environ.get("WORK_CUBBY_MEMBER")
    if actor and actor != member:
        raise PermissionError(
            f"WORK_CUBBY_MEMBER={actor!r} cannot write member {member!r}"
        )


def utc_now() -> str:
    """Return an RFC-3339 UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime:
    """Parse and validate a Zulu timestamp."""
    if not value or not value.endswith("Z"):
        raise ValueError("timestamps must be RFC-3339 UTC with a trailing Z")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("timestamp is not UTC")
    return parsed


def canonical_json(value: object) -> str:
    """Return deterministic JSON for hashing."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def event_sha256(event: dict) -> str:
    """Hash an event excluding its own sha256 field."""
    unsigned = {key: value for key, value in event.items() if key != "sha256"}
    return hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest()


def read_ledger(member: str) -> list[dict]:
    """Read and parse one member's ledger."""
    path = ledger_path(member)
    if not path.exists():
        return []
    records = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: {error}") from error
    return records


def _append_event(
    member: str,
    kind: str,
    payload: dict,
    *,
    at: str | None = None,
    reconstructed: bool = False,
) -> dict:
    """Append one sha256-linked event while holding the member ledger lock."""
    enforce_actor(member)
    path = ledger_path(member)
    if not (cubby_dir(member) / "cubby.json").exists():
        raise FileNotFoundError(f"member cubby does not exist: {member}")
    timestamp = at or utc_now()
    parse_utc(timestamp)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            stream.seek(0)
            records = [
                json.loads(line)
                for line in stream.read().splitlines()
                if line.strip()
            ]
            event = {
                "seq": len(records) + 1,
                "utc": timestamp,
                "kind": kind,
                "member_id": member,
                "reconstructed": bool(reconstructed),
                "prev": records[-1]["sha256"] if records else None,
                "payload": payload,
            }
            event["sha256"] = event_sha256(event)
            stream.seek(0, os.SEEK_END)
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            return event
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def save_json(path: Path, value: dict) -> None:
    """Atomically write and read-back validate JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        json.loads(temporary.read_text(encoding="utf-8"))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def init_cubby(args: argparse.Namespace) -> dict:
    """Create a canonical cubby manifest and append its join event."""
    enforce_actor(args.member)
    directory = cubby_dir(args.member)
    manifest_path = directory / "cubby.json"
    if manifest_path.exists():
        if args.if_missing:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        raise FileExistsError(f"cubby already exists: {args.member}")

    created_at = args.at or utc_now()
    parse_utc(created_at)
    manifest = {
        "schema": "rapp-cubby/1.0",
        "github_login": args.github_login,
        "slug": args.member,
        "display_name": args.display_name,
        "what_im_cooking": args.purpose,
        "created_at": created_at,
        "estate": {"anatomy": ["neighborhoods", "show-and-tell"]},
        "streamable": {},
        "parent_cubby": None,
        "is_sub_cubby": False,
        "neighborhood": {
            "name": NEIGHBORHOOD_NAME,
            "address": NEIGHBORHOOD_ADDRESS,
            "neighborhood_rappid": NEIGHBORHOOD_RAPPID,
        },
    }
    if args.reconstructed:
        manifest["materialized_at"] = utc_now()
    save_json(manifest_path, manifest)
    save_json(
        directory / "neighborhoods" / "work-cubbies.json",
        {
            "protocol": "rapp-neighborhood-protocol/1.0",
            "name": NEIGHBORHOOD_NAME,
            "address": NEIGHBORHOOD_ADDRESS,
            "neighborhood_rappid": NEIGHBORHOOD_RAPPID,
        },
    )
    _append_event(
        args.member,
        "cubby.join",
        {
            "github_login": args.github_login,
            "display_name": args.display_name,
            "purpose": args.purpose,
            "neighborhood": NEIGHBORHOOD_ADDRESS,
        },
        at=created_at,
        reconstructed=args.reconstructed,
    )
    return manifest


def open_shifts(records: list[dict]) -> dict[str, dict]:
    """Return clock-ins that do not yet have a matching clock-out."""
    open_by_id: dict[str, dict] = {}
    for record in records:
        shift_id = record.get("payload", {}).get("shift_id")
        if record.get("kind") == "cubby.clock_in" and shift_id:
            open_by_id[shift_id] = record
        elif record.get("kind") == "cubby.clock_out" and shift_id:
            open_by_id.pop(shift_id, None)
    return open_by_id


def clock_in(args: argparse.Namespace) -> dict:
    """Append a clock-in event, refusing overlapping shifts."""
    records = read_ledger(args.member)
    if open_shifts(records):
        raise RuntimeError("member already has an open shift")
    timestamp = args.at or utc_now()
    shift_id = args.shift_id or (
        f"{args.member}-{timestamp.replace(':', '').replace('-', '')}-"
        f"{uuid.uuid4().hex[:8]}"
    )
    return _append_event(
        args.member,
        "cubby.clock_in",
        {
            "shift_id": shift_id,
            "task": args.task,
            "source": args.source,
        },
        at=timestamp,
        reconstructed=args.reconstructed,
    )


def elapsed_hms(seconds: int) -> str:
    """Render elapsed seconds as HH:MM:SS."""
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _clock_out(
    member: str,
    *,
    summary: str,
    evidence: list[str],
    at: str | None = None,
    shift_id: str | None = None,
    reconstructed: bool = False,
) -> dict:
    """Append a clock-out for one open shift."""
    records = read_ledger(member)
    open_by_id = open_shifts(records)
    if not open_by_id:
        raise RuntimeError("member has no open shift")
    selected_id = shift_id or next(reversed(open_by_id))
    if selected_id not in open_by_id:
        raise KeyError(f"open shift not found: {selected_id}")
    started_at = open_by_id[selected_id]["utc"]
    ended_at = at or utc_now()
    elapsed = int((parse_utc(ended_at) - parse_utc(started_at)).total_seconds())
    if elapsed < 0:
        raise ValueError("clock-out precedes clock-in")
    return _append_event(
        member,
        "cubby.clock_out",
        {
            "shift_id": selected_id,
            "started_at": started_at,
            "ended_at": ended_at,
            "elapsed_seconds": elapsed,
            "elapsed_hms": elapsed_hms(elapsed),
            "summary": summary,
            "evidence": evidence,
        },
        at=ended_at,
        reconstructed=reconstructed,
    )


def clock_out(args: argparse.Namespace) -> dict:
    """CLI adapter for clock-out."""
    return _clock_out(
        args.member,
        summary=args.summary,
        evidence=args.evidence,
        at=args.at,
        shift_id=args.shift_id,
        reconstructed=args.reconstructed,
    )


def import_shift(args: argparse.Namespace) -> list[dict]:
    """Import a historical shift while marking both records reconstructed."""
    started = parse_utc(args.started_at)
    ended = parse_utc(args.ended_at)
    if ended < started:
        raise ValueError("imported shift ends before it starts")
    shift_id = args.shift_id or (
        f"{args.member}-import-{args.started_at.replace(':', '').replace('-', '')}"
    )
    clock_in_event = clock_in(
        argparse.Namespace(
            member=args.member,
            at=args.started_at,
            shift_id=shift_id,
            task=args.task,
            source=args.source,
            reconstructed=True,
        )
    )
    clock_out_event = _clock_out(
        args.member,
        summary=args.summary,
        evidence=args.evidence,
        at=args.ended_at,
        shift_id=shift_id,
        reconstructed=True,
    )
    return [clock_in_event, clock_out_event]


def verify_member(member: str) -> dict:
    """Verify one cubby manifest and its complete ledger chain."""
    manifest_path = cubby_dir(member) / "cubby.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_MANIFEST_FIELDS - set(manifest))
    if manifest.get("schema") != "rapp-cubby/1.0":
        raise ValueError(f"{member}: unsupported cubby schema")
    if missing:
        raise ValueError(f"{member}: missing manifest fields {missing}")
    if manifest.get("slug") != member:
        raise ValueError(f"{member}: manifest slug mismatch")

    records = read_ledger(member)
    previous = None
    prior_utc = None
    for expected_seq, record in enumerate(records, 1):
        if record.get("seq") != expected_seq:
            raise ValueError(f"{member}: ledger sequence gap at {expected_seq}")
        if record.get("member_id") != member:
            raise ValueError(f"{member}: cross-member ledger record")
        if record.get("prev") != previous:
            raise ValueError(f"{member}: prev hash mismatch at {expected_seq}")
        if record.get("sha256") != event_sha256(record):
            raise ValueError(f"{member}: sha256 mismatch at {expected_seq}")
        current_utc = parse_utc(record.get("utc", ""))
        if prior_utc and current_utc < prior_utc:
            raise ValueError(f"{member}: non-monotonic UTC at {expected_seq}")
        prior_utc = current_utc
        previous = record["sha256"]

    for record in records:
        if record.get("kind") != "cubby.clock_out":
            continue
        payload = record.get("payload", {})
        elapsed = int(
            (
                parse_utc(payload["ended_at"])
                - parse_utc(payload["started_at"])
            ).total_seconds()
        )
        if payload.get("elapsed_seconds") != elapsed:
            raise ValueError(f"{member}: elapsed seconds mismatch")
        if payload.get("elapsed_hms") != elapsed_hms(elapsed):
            raise ValueError(f"{member}: elapsed HH:MM:SS mismatch")

    return {
        "member": member,
        "records": len(records),
        "head_sha256": records[-1]["sha256"] if records else None,
        "open_shifts": sorted(open_shifts(records)),
    }


def verify_all() -> dict:
    """Verify every public cubby in the selected root."""
    cubbies_root = root_path() / "cubbies"
    results = []
    if cubbies_root.exists():
        for path in sorted(cubbies_root.iterdir()):
            if path.is_dir() and not path.name.startswith((".", "_")):
                results.append(verify_member(path.name))
    return {"ok": True, "cubbies": results}


def status(args: argparse.Namespace) -> dict:
    """Summarize one member's hours and current shift."""
    records = read_ledger(args.member)
    total_seconds = sum(
        int(record.get("payload", {}).get("elapsed_seconds", 0) or 0)
        for record in records
        if record.get("kind") == "cubby.clock_out"
    )
    return {
        "member": args.member,
        "records": len(records),
        "total_seconds": total_seconds,
        "total_hms": elapsed_hms(total_seconds),
        "open_shifts": sorted(open_shifts(records)),
        "head_sha256": records[-1]["sha256"] if records else None,
    }


def mirror_local(args: argparse.Namespace) -> dict:
    """Mirror one sanitized public cubby into the canonical local shelf."""
    source = cubby_dir(args.member)
    if not source.exists():
        raise FileNotFoundError(f"member cubby does not exist: {args.member}")
    target_root = Path(args.target).expanduser().resolve()
    target = target_root / args.member
    target_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    return {"member": args.member, "source": str(source), "target": str(target)}


def add_common_event_flags(parser: argparse.ArgumentParser) -> None:
    """Add shared event metadata flags."""
    parser.add_argument("--at", help="RFC-3339 UTC timestamp; default now")
    parser.add_argument("--reconstructed", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line contract."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="join and create a member cubby")
    init.add_argument("--member", required=True)
    init.add_argument("--github-login", required=True)
    init.add_argument("--display-name", required=True)
    init.add_argument("--purpose", required=True)
    init.add_argument("--if-missing", action="store_true")
    add_common_event_flags(init)
    init.set_defaults(handler=init_cubby)

    start = commands.add_parser("clock-in", help="start a work shift")
    start.add_argument("--member", required=True)
    start.add_argument("--task", required=True)
    start.add_argument("--shift-id")
    start.add_argument("--source", default="observed")
    add_common_event_flags(start)
    start.set_defaults(handler=clock_in)

    stop = commands.add_parser("clock-out", help="finish a work shift")
    stop.add_argument("--member", required=True)
    stop.add_argument("--summary", required=True)
    stop.add_argument("--evidence", action="append", default=[])
    stop.add_argument("--shift-id")
    add_common_event_flags(stop)
    stop.set_defaults(handler=clock_out)

    imported = commands.add_parser("import-shift", help="import historical work")
    imported.add_argument("--member", required=True)
    imported.add_argument("--started-at", required=True)
    imported.add_argument("--ended-at", required=True)
    imported.add_argument("--task", required=True)
    imported.add_argument("--summary", required=True)
    imported.add_argument("--evidence", action="append", default=[])
    imported.add_argument("--source", default="session evidence")
    imported.add_argument("--shift-id")
    imported.set_defaults(handler=import_shift)

    check = commands.add_parser("verify", help="verify every cubby and ledger")
    check.set_defaults(handler=lambda _args: verify_all())

    show = commands.add_parser("status", help="show one member's hours")
    show.add_argument("--member", required=True)
    show.set_defaults(handler=status)

    mirror = commands.add_parser(
        "mirror-local", help="copy a public cubby to ~/.brainstem/cubbies"
    )
    mirror.add_argument("--member", required=True)
    mirror.add_argument(
        "--target",
        default=str(Path.home() / ".brainstem" / "cubbies"),
    )
    mirror.set_defaults(handler=mirror_local)
    return parser


def main() -> int:
    """Run one command and emit machine-readable JSON."""
    try:
        args = build_parser().parse_args()
        result = args.handler(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as error:
        print(
            json.dumps(
                {"ok": False, "error": f"{type(error).__name__}: {error}"}
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
