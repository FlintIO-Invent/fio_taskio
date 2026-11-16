"""Synthetic offline gate/resume tests. No application runtime or database."""

import argparse
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import workflow as w

REPORTS = (
    "docs/design/motionmate-ui-lab/10-appointments-bookings-audit.md",
    "docs/design/motionmate-ui-lab/11-appointments-bookings-design-brief.md",
    "docs/design/motionmate-ui-lab/12-appointments-bookings-prototype-review.md",
    "docs/design/motionmate-ui-lab/13-appointments-bookings-production-integration-audit.md",
)
CONSENT = {
    "source": "SIMULATION ONLY: synthetic user message",
    "quote": "SIMULATION ONLY: approve this stage within its stated scope",
    "scope": "Synthetic presentation workflow; no application edits or consent",
}


def sample(mode="full", vertical="SERVICE"):
    state = json.loads((w.ASSETS / "state.json").read_text())
    state.update(
        task_id="appointments-simulation",
        mode=mode,
        vertical=vertical,
        route="/appointments/",
        objective="Simulate existing connected review",
        design_version="v1" if mode == "full" else None,
    )
    return state


def complete(state, phase, reference="synthetic-evidence"):
    state["completed_phases"].append(phase)
    state["evidence"][phase] = [
        {"kind": "simulation", "reference": reference, "summary": "Synthetic phase evidence only"}
    ]


def approve(state, gate, result):
    record = copy.deepcopy(CONSENT)
    if gate != "acceptance":
        record["design_version"] = state["design_version"]
    key = {
        "design": "design_sha256",
        "implementation": "manifest_sha256",
        "acceptance": "candidate_sha256",
    }[gate]
    record[key] = result[key]
    state["approvals"][gate] = record


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="motionmate-workflow-test-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / "prototype.html").write_text("Synthetic connected prototype")
        (self.repo / "target.html").write_text("Synthetic current presentation")
        self.identity = {"branch": "synthetic", "head": "synthetic-head", "status": ""}

    def check(self, state, **kwargs):
        return w.inspect_state(state, self.repo, **kwargs)

    def at_a(self, vertical="SERVICE"):
        state = sample(vertical=vertical)
        state["design_artifacts"] = {"prototype.html": w.sha(self.repo / "prototype.html")}
        for phase in w.PHASES["full"][:4]:
            complete(state, phase)
        return state

    def at_b(self, mode="full"):
        if mode == "full":
            state = self.at_a()
            approve(state, "design", self.check(state))
            complete(state, "integration")
        else:
            state = sample("quick")
            for phase in ("audit", "plan"):
                complete(state, phase)
        state["manifest"] = [
            {
                "path": "target.html",
                "action": "modify",
                "purpose": "Synthetic layout",
                "shared": False,
                "before_sha256": w.sha(self.repo / "target.html"),
            }
        ]
        state["baseline"] = self.identity.copy()
        return state

    def through_report(self, state):
        approve(state, "implementation", self.check(state))
        for phase in w.PHASES[state["mode"]][len(state["completed_phases"]) :]:
            if phase == "validation":
                state["validation"] = [
                    {"check": "Synthetic task", "status": "pass", "evidence": "simulation"}
                ]
            complete(state, phase)
        return state

    def test_full_stops_at_each_gate_and_completes_only_after_acceptance(self):
        state = self.at_a()
        self.assertEqual(self.check(state)["gate"], "A")
        approve(state, "design", self.check(state))
        self.assertEqual(self.check(state)["current_phase"], "integration")
        state = self.at_b()
        self.assertEqual(self.check(state)["gate"], "B")
        state = self.through_report(state)
        self.assertEqual(self.check(state)["gate"], "C")
        approve(state, "acceptance", self.check(state))
        self.assertEqual(self.check(state)["current_phase"], "done")

    def test_quick_plan_requires_consent_without_design_or_prototype(self):
        state = self.at_b("quick")
        self.assertEqual(self.check(state)["gate"], "B")
        self.assertIsNone(state["approvals"]["design"])
        self.assertEqual(self.check(self.through_report(state))["current_phase"], "done")

    def test_cannot_mark_integration_complete_without_a(self):
        state = self.at_a()
        complete(state, "integration")
        with self.assertRaisesRegex(ValueError, "Gate A"):
            self.check(state)

    def test_cannot_complete_before_without_b(self):
        state = self.at_b()
        complete(state, "before")
        with self.assertRaisesRegex(ValueError, "Gate B"):
            self.check(state)

    def test_changed_design_bytes_or_version_invalidates_approval(self):
        state = self.at_b()
        (self.repo / "prototype.html").write_text("Different design")
        with self.assertRaisesRegex(ValueError, "artifact missing/changed"):
            self.check(state)
        state["design_artifacts"]["prototype.html"] = w.sha(self.repo / "prototype.html")
        with self.assertRaisesRegex(ValueError, "Stale design"):
            self.check(state)
        state = self.at_b()
        state["design_version"] = "v2"
        with self.assertRaisesRegex(ValueError, "Stale design"):
            self.check(state)

    def test_manifest_or_objective_expansion_invalidates_b(self):
        for key, value in (("objective", "Different behavior"), ("vertical", "SHARED")):
            state = self.at_b()
            approve(state, "implementation", self.check(state))
            state[key] = value
            with self.assertRaisesRegex(ValueError, "Stale implementation"):
                self.check(state)
        state = self.at_b()
        approve(state, "implementation", self.check(state))
        state["manifest"][0]["purpose"] = "Expanded scope"
        with self.assertRaisesRegex(ValueError, "Stale implementation"):
            self.check(state)

    def test_new_design_consent_cannot_reuse_old_implementation_binding(self):
        state = self.at_b()
        approve(state, "implementation", self.check(state))
        (self.repo / "prototype.html").write_text("Revised design with renewed A")
        state["design_artifacts"]["prototype.html"] = w.sha(self.repo / "prototype.html")
        state["approvals"]["design"]["design_sha256"] = w.digest(
            {"version": state["design_version"], "artifacts": state["design_artifacts"]}
        )
        with self.assertRaisesRegex(ValueError, "Stale implementation"):
            self.check(state)

    def test_concurrent_file_or_git_drift_blocks_preimplementation(self):
        state = self.at_b()
        approve(state, "implementation", self.check(state))
        with patch.object(w, "git_identity", return_value=self.identity):
            self.check(state, pre_implementation=True)
            (self.repo / "target.html").write_text("Concurrent edit")
            with self.assertRaisesRegex(ValueError, "Overlapping"):
                self.check(state, pre_implementation=True)
        with patch.object(w, "git_identity", return_value={**self.identity, "head": "different"}):
            with self.assertRaisesRegex(ValueError, "drift"):
                self.check(state, pre_implementation=True)

    def test_shared_manifest_requires_impact_and_both_vertical_check_plan(self):
        state = self.at_b()
        state["manifest"][0]["shared"] = True
        with self.assertRaisesRegex(ValueError, "shared impact"):
            self.check(state)
        state["manifest"][0].update(
            shared_impact="Services/Logistics consumers",
            shared_regression="Both verticals; roles/modules/subscriptions/locations",
        )
        self.check(state)

    def test_invalid_manifest_paths_duplicate_paths_and_symlinks_fail(self):
        for name in ("../escape", "/absolute", "src/*.html", "./target.html"):
            state = self.at_b()
            state["manifest"][0]["path"] = name
            with self.assertRaises(ValueError):
                self.check(state)
        state = self.at_b()
        state["manifest"].append(copy.deepcopy(state["manifest"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.check(state)
        (self.repo / "link").symlink_to(self.repo / "target.html")
        state = self.at_b()
        state["manifest"][0]["path"] = "link"
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.check(state)

    def test_pending_validation_cannot_be_completed_and_missing_approval_evidence_fails(self):
        state = self.through_report(self.at_b())
        state["validation"][0]["status"] = "pending"
        with self.assertRaisesRegex(ValueError, "actual results"):
            self.check(state)
        state = self.at_b()
        state["approvals"]["design"]["quote"] = ""
        with self.assertRaisesRegex(ValueError, "quote"):
            self.check(state)

    def test_resume_saved_state_keeps_gate_and_consent_candidate_is_bound(self):
        state = self.at_b()
        path = self.repo / "state.json"
        w.write_json(path, state)
        resumed = json.loads(path.read_text())
        self.assertEqual(self.check(resumed)["gate"], "B")
        state = self.through_report(resumed)
        approve(state, "acceptance", self.check(state))
        (self.repo / "target.html").write_text("Changed after acceptance")
        with self.assertRaisesRegex(ValueError, "Stale candidate"):
            self.check(state)

    def test_logistics_design_has_its_own_gate(self):
        self.assertEqual(self.check(self.at_a("LOGISTICS"))["gate"], "A")

    def test_skipped_phase_and_missing_evidence_fail(self):
        state = sample()
        complete(state, "brief")
        with self.assertRaisesRegex(ValueError, "skipped"):
            self.check(state)
        state = sample()
        state["completed_phases"] = ["audit"]
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.check(state)

    def test_init_refuses_existing_task(self):
        args = argparse.Namespace(
            task="synthetic-task",
            output=self.repo / "task",
            vertical="SERVICE",
            mode="quick",
            route="/appointments/",
            objective="Synthetic only",
        )
        w.initialize(args)
        self.assertTrue((args.output / "state.json").is_file())
        with self.assertRaisesRegex(ValueError, "already exists"):
            w.initialize(args)

    def test_interrupted_checkpoint_retains_previous_record(self):
        path = self.repo / "checkpoint.json"
        w.write_json(path, {"checkpoint": "original"})
        original = path.read_bytes()
        with patch.object(Path, "replace", side_effect=OSError("Simulated interruption")):
            with self.assertRaisesRegex(OSError, "interruption"):
                w.write_json(path, {"checkpoint": "replacement"})
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(self.repo.glob(".checkpoint.json.*.tmp")))


class HistoricalSimulation(unittest.TestCase):
    def test_existing_appointments_documents_stop_at_b_without_reopening_work(self):
        before = {name: w.sha(w.REPO / name) for name in REPORTS}
        state = sample()
        # Only existing documents are read. These synthetic approvals are not
        # imported into any actual task or historical approval record.
        state["design_artifacts"] = {REPORTS[2]: before[REPORTS[2]]}
        for phase, reference in zip(
            w.PHASES["full"][:4], (REPORTS[0], REPORTS[1], REPORTS[2], REPORTS[2]), strict=True
        ):
            complete(state, phase, reference)
        self.assertEqual(w.inspect_state(state)["gate"], "A")
        approve(state, "design", w.inspect_state(state))
        complete(state, "integration", REPORTS[3])
        self.assertEqual(w.inspect_state(state)["gate"], "B")
        self.assertIsNone(state["approvals"]["implementation"])
        self.assertEqual(before, {name: w.sha(w.REPO / name) for name in REPORTS})


if __name__ == "__main__":
    unittest.main()
