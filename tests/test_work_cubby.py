"""Contract tests for isolated, append-only work cubbies."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import work_cubby
from scripts import validate


class WorkCubbyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.root_env = mock.patch.dict(
            os.environ,
            {"WORK_CUBBY_ROOT": str(self.root), "WORK_CUBBY_MEMBER": "agent-a"},
            clear=False,
        )
        self.root_env.start()
        self.addCleanup(self.root_env.stop)
        self.addCleanup(self.temp.cleanup)
        self.init_member("agent-a")

    def init_member(self, member: str) -> None:
        with mock.patch.dict(os.environ, {"WORK_CUBBY_MEMBER": member}):
            work_cubby.init_cubby(argparse.Namespace(
                member=member,
                github_login="octocat",
                display_name=member,
                purpose="Track work",
                at="2026-08-15T00:00:00Z",
                reconstructed=False,
                if_missing=False,
            ))

    def test_clock_round_trip_and_elapsed_time(self):
        start = work_cubby.clock_in(argparse.Namespace(
            member="agent-a",
            at="2026-08-15T01:00:00Z",
            shift_id="shift-1",
            task="Build",
            source="observed",
            reconstructed=False,
        ))
        stop = work_cubby._clock_out(
            "agent-a",
            summary="Built it",
            evidence=["commit:abc123"],
            at="2026-08-15T02:02:03Z",
            shift_id="shift-1",
        )
        self.assertEqual("shift-1", start["payload"]["shift_id"])
        self.assertEqual(3723, stop["payload"]["elapsed_seconds"])
        self.assertEqual("01:02:03", stop["payload"]["elapsed_hms"])
        verified = work_cubby.verify_member("agent-a")
        self.assertEqual(3, verified["records"])
        self.assertEqual([], verified["open_shifts"])

    def test_historical_import_is_explicitly_reconstructed(self):
        events = work_cubby.import_shift(argparse.Namespace(
            member="agent-a",
            started_at="2026-08-15T03:00:00Z",
            ended_at="2026-08-15T04:00:00Z",
            task="Imported task",
            summary="Imported summary",
            evidence=["https://example.test/pr/1"],
            source="session evidence",
            shift_id="import-1",
        ))
        self.assertTrue(all(event["reconstructed"] for event in events))
        self.assertEqual(3600, events[-1]["payload"]["elapsed_seconds"])

    def test_declared_actor_cannot_write_another_member(self):
        self.init_member("agent-b")
        with self.assertRaises(PermissionError):
            work_cubby.clock_in(argparse.Namespace(
                member="agent-b",
                at="2026-08-15T05:00:00Z",
                shift_id="wrong-owner",
                task="No",
                source="observed",
                reconstructed=False,
            ))

    def test_hash_tamper_is_rejected(self):
        path = work_cubby.ledger_path("agent-a")
        rows = path.read_text(encoding="utf-8").splitlines()
        event = json.loads(rows[0])
        event["payload"]["purpose"] = "tampered"
        path.write_text(json.dumps(event) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "sha256 mismatch"):
            work_cubby.verify_member("agent-a")

    def test_member_branch_cannot_edit_another_cubby(self):
        with self.assertRaises(PermissionError):
            validate.validate_changed_paths(
                "cubby/agent-a/shift",
                [
                    "cubbies/agent-a/show-and-tell/work-ledger.jsonl",
                    "cubbies/agent-b/show-and-tell/work-ledger.jsonl",
                ],
            )
        member = validate.validate_changed_paths(
            "cubby/agent-a/shift",
            [
                "cubbies/agent-a/show-and-tell/work-ledger.jsonl",
                "super-rar/index.json",
            ],
        )
        self.assertEqual("agent-a", member)


if __name__ == "__main__":
    unittest.main()

