"""Tests for privacy-safe global Work Cubby reporting."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import work_cubby
from scripts import build_global_report
from scripts import privacy


class GlobalReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = mock.patch.dict(
            os.environ,
            {"WORK_CUBBY_ROOT": str(self.root), "WORK_CUBBY_MEMBER": "agent-a"},
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.temp.cleanup)
        work_cubby.init_cubby(argparse.Namespace(
            member="agent-a",
            github_login="octocat",
            display_name="Agent <A>",
            purpose="Public work",
            at="2026-08-15T00:00:00Z",
            reconstructed=False,
            if_missing=False,
        ))

    def test_report_separates_observed_reconstructed_and_active(self):
        work_cubby.import_shift(argparse.Namespace(
            member="agent-a",
            started_at="2026-08-15T01:00:00Z",
            ended_at="2026-08-15T02:00:00Z",
            task="Imported",
            summary="Historical work",
            evidence=["https://example.test/pr/1"],
            source="session evidence",
            shift_id="imported",
        ))
        work_cubby.clock_in(argparse.Namespace(
            member="agent-a",
            at="2026-08-15T03:00:00Z",
            shift_id="observed",
            task="Observed",
            source="session timestamp",
            reconstructed=False,
        ))
        work_cubby._clock_out(
            "agent-a",
            summary="Observed work",
            evidence=["commit:abc123"],
            at="2026-08-15T03:30:00Z",
            shift_id="observed",
        )
        work_cubby.clock_in(argparse.Namespace(
            member="agent-a",
            at="2026-08-15T04:00:00Z",
            shift_id="active",
            task="Still working",
            source="session timestamp",
            reconstructed=False,
        ))

        report = build_global_report.semantic_report(self.root)

        self.assertEqual(1800, report["totals"]["observed_seconds"])
        self.assertEqual(3600, report["totals"]["reconstructed_seconds"])
        self.assertEqual(5400, report["totals"]["total_seconds"])
        self.assertEqual(1, report["totals"]["active_shifts"])
        self.assertEqual("Still working", report["active_shifts"][0]["task"])
        self.assertEqual(2, report["totals"]["completed_shifts"])

    def test_html_escapes_member_and_shift_text(self):
        report = build_global_report.semantic_report(self.root)
        report["generated_at"] = "2026-08-15T00:00:00Z"
        page = build_global_report.render_html(report)
        self.assertIn("Agent &lt;A&gt;", page)
        self.assertNotIn("Agent <A>", page)

    def test_privacy_rejects_email_phone_secret_and_private_path(self):
        bad_values = (
            "person@example.com",
            "+1 404 555 1212",
            "github_pat_abcdefghijklmnopqrstuvwxyz",
            "/Users/private/work.txt",
        )
        for value in bad_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    privacy.validate_public_string(value, "fixture")

    def test_evidence_must_be_public_or_commit_reference(self):
        privacy.validate_evidence(
            ["https://github.com/kody-w/repo/pull/1", "commit:abc123"],
            "fixture",
        )
        with self.assertRaises(ValueError):
            privacy.validate_evidence(["file:///private/report"], "fixture")

    def test_generation_timestamp_is_stable_without_semantic_change(self):
        first = build_global_report.build_report(self.root)
        second = build_global_report.build_report(self.root, first)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

