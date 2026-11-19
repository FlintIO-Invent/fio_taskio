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
        schema_version=1,
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
    if gate == "acceptance" and state["schema_version"] == 2:
        record["review_sha256"] = result["review_sha256"]
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
        for phase in w.LEGACY_PHASES["full"][:4]:
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
        for phase in w.LEGACY_PHASES[state["mode"]][len(state["completed_phases"]) :]:
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


class WorkflowV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="motionmate-workflow-v2-test-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / "brief.md").write_text("Synthetic design direction, no interactive prototype")
        (self.repo / "target.html").write_text("Synthetic BEFORE")
        self.identity = {"branch": "synthetic", "head": "synthetic-head", "status": ""}
        self.workspace = {"status": "", "files": {}}
        self._protected_workspace_function = w.protected_workspace
        for name, value in (
            ("git_identity", self.identity),
            ("protected_workspace", self.workspace),
        ):
            patcher = patch.object(w, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def check(self, state, **kwargs):
        return w.inspect_state(state, self.repo, **kwargs)

    def at_a(self, mode="full", vertical="SERVICE"):
        state = sample(mode, vertical)
        state["schema_version"] = 2
        if mode == "full":
            state["design_artifacts"] = {"brief.md": w.sha(self.repo / "brief.md")}
        for phase in ("audit", "brief" if mode == "full" else "plan"):
            complete(state, phase)
        return state

    def at_b(self, mode="full", vertical="SERVICE"):
        state = self.at_a(mode, vertical)
        if mode == "full":
            approve(state, "design", self.check(state))
            complete(state, "integration")
        state["manifest"] = [
            {
                "path": "target.html",
                "action": "modify",
                "purpose": "Synthetic layout",
                "category": "implementation",
                "vertical": vertical,
                "shared": False,
                "before_sha256": w.sha(self.repo / "target.html"),
            }
        ]
        state["baseline"] = self.identity.copy()
        state["protected_workspace"] = copy.deepcopy(self.workspace)
        return state

    def before(self, state):
        approve(state, "implementation", self.check(state))
        state["preview"] = {
            "kind": "django",
            "vertical": state["vertical"],
            "synthetic_records": True,
            "contracts": ["templates", "routes", "authentication", "forms", "permissions"],
        }
        for index, side in enumerate(("before", "after")):
            state["environments"].append(
                {
                    "id": side,
                    "engine": "postgresql",
                    "disposable": True,
                    "ownership_verified": True,
                    "settings": "synthetic.settings",
                    "database": "synthetic",
                    "cluster_directory": f"/tmp/synthetic-{side}",
                    "system_identifier": f"synthetic-{side}",
                    "port": 55488 + index,
                    "process": f"synthetic-{side}",
                    "identity_evidence": "SIMULATION ONLY",
                }
            )
            state["resource_authorizations"].append({**CONSENT, "environment_id": side})
            state["preview"][side] = {
                "url": f"http://127.0.0.1:{8781 + index}/appointments/",
                "source_sha256": w.digest(side),
                "initial_fixture_sha256": w.digest("synthetic records"),
                "environment_id": side,
            }
        complete(state, "before")
        state["implementation_checkpoint"] = w.target_hashes(self.repo, state)
        return state

    def through_report(self, mode="full", vertical="SERVICE"):
        state = self.before(self.at_b(mode, vertical))
        (self.repo / "target.html").write_text("Synthetic AFTER")
        complete(state, "implementation")
        candidate = self.check(state)["candidate_sha256"]
        state["preview"]["after"]["candidate_sha256"] = candidate
        state["validation"] = [
            {
                "check": "Synthetic Django contracts",
                "status": "pass",
                "vertical": v,
                "evidence": "SIMULATION ONLY",
            }
            for v in ("SERVICE", "LOGISTICS")
        ]
        for phase in w.phases_for(state)[len(state["completed_phases"]) :]:
            complete(state, phase)
        state["implementation_checkpoint"] = w.target_hashes(self.repo, state)
        return state

    def accepted(self):
        state = self.through_report()
        approve(state, "acceptance", self.check(state))
        task = self.repo / w.task_prefix(state)
        task.mkdir(parents=True)
        for name in w.CORE_REPORTS[1:]:
            (task / name).write_text("Essential synthetic workflow record")
        path = task / "state.json"
        w.write_json(path, state)
        return state, path

    def test_v2_full_has_only_real_django_review_and_stops_at_a_b_c(self):
        state = self.at_a()
        self.assertEqual(self.check(state)["gate"], "A")
        self.assertNotIn("prototype", w.phases_for(state))
        self.assertEqual(self.check(self.at_b())["gate"], "B")
        state = self.through_report()
        self.assertEqual(self.check(state)["gate"], "C")
        approve(state, "acceptance", self.check(state))
        self.assertEqual(self.check(state)["current_phase"], "done")
        self.assertIn("Automatically prepare", self.check(state)["next_permitted_action"])

    def test_a_and_b_cannot_be_bypassed_or_preapproved_without_their_plans(self):
        state = self.at_a()
        complete(state, "integration")
        with self.assertRaisesRegex(ValueError, "Gate A"):
            self.check(state)
        state = self.at_b()
        complete(state, "before")
        complete(state, "implementation")
        with self.assertRaisesRegex(ValueError, "Gate B"):
            self.check(state)
        state = self.at_b()
        approve(state, "implementation", self.check(state))
        state["completed_phases"].remove("integration")
        with self.assertRaisesRegex(ValueError, "completed integration plan"):
            self.check(state)

    def test_no_application_edits_before_b_and_concurrent_dirty_edits_detected(self):
        state = self.at_b()
        (self.repo / "target.html").write_text("Unauthorized edit before B")
        with self.assertRaisesRegex(ValueError, "before implementation"):
            self.check(state)
        state = self.at_b()
        self.workspace["files"]["unrelated.py"] = "different bytes with same Git status"
        with self.assertRaisesRegex(ValueError, "Concurrent edits"):
            self.check(state)

    def test_optional_prototype_requires_reason_and_actual_authorization_record(self):
        state = self.at_a()
        state["optional_prototype"]["enabled"] = True
        with self.assertRaisesRegex(ValueError, "needs a request"):
            self.check(state)
        state["optional_prototype"]["reason"] = "Major unresolved interaction uncertainty"
        with self.assertRaisesRegex(ValueError, "object"):
            self.check(state)
        state["optional_prototype"]["authorization"] = CONSENT.copy()
        self.assertEqual(self.check(state)["gate"], "A")
        state["optional_prototype"]["enabled"] = False
        state["evidence"]["brief"][0]["kind"] = "synthetic_prototype"
        with self.assertRaisesRegex(ValueError, "explicit authorization"):
            self.check(state)

    def test_preview_requires_actual_django_postimplementation_after_and_current_candidate(self):
        for change, message in (
            (lambda s: s.update(preview=None), "Actual Django"),
            (lambda s: s["preview"].update(kind="synthetic"), "Actual Django"),
            (lambda s: s["preview"].update(contracts=["templates"]), "actual templates"),
            (lambda s: s["preview"].pop("after"), "after preview"),
            (lambda s: s["preview"]["after"].update(candidate_sha256="wrong"), "current candidate"),
        ):
            with self.subTest(message=message):
                state = self.through_report()
                change(state)
                with self.assertRaisesRegex(ValueError, message):
                    self.check(state)

    def test_preview_requires_verified_authorized_disposable_postgres(self):
        for change, message in (
            (lambda s: s["environments"][0].update(engine="sqlite"), "PostgreSQL"),
            (lambda s: s["environments"][0].update(disposable=False), "PostgreSQL"),
            (lambda s: s["environments"][0].update(ownership_verified=False), "PostgreSQL"),
            (lambda s: s["environments"][0].update(port=5432), "Ordinary"),
            (lambda s: s.update(resource_authorizations=[]), "object"),
            (lambda s: s["preview"]["after"].update(initial_fixture_sha256="f" * 64), "equivalent"),
            (
                lambda s: s["environments"][1].update(system_identifier="synthetic-before"),
                "independent",
            ),
        ):
            with self.subTest(message=message):
                state = self.through_report()
                change(state)
                with self.assertRaisesRegex(ValueError, message):
                    self.check(state)

    def test_services_design_approval_cannot_be_used_for_logistics(self):
        state = self.at_b()
        state["vertical"] = "LOGISTICS"
        state["manifest"][0]["vertical"] = "LOGISTICS"
        with self.assertRaisesRegex(ValueError, "Stale design"):
            self.check(state)
        self.assertEqual(self.check(self.at_a(vertical="LOGISTICS"))["gate"], "A")
        state = self.at_b()
        state["manifest"][0]["vertical"] = "LOGISTICS"
        with self.assertRaisesRegex(ValueError, "outside task scope"):
            self.check(state)

    def test_shared_scope_requires_both_planned_and_executed_verticals(self):
        state = self.at_b()
        state["manifest"][0].update(
            shared=True,
            vertical="SHARED",
            shared_impact="Both consumers",
            shared_regression="Both verticals",
        )
        with self.assertRaisesRegex(ValueError, "both regression"):
            self.check(state)
        state["manifest"][0]["regression_verticals"] = ["SERVICE", "LOGISTICS"]
        self.check(state)
        state = self.through_report(vertical="SHARED")
        state["validation"] = state["validation"][:1]
        with self.assertRaisesRegex(ValueError, "both verticals"):
            self.check(state)

    def test_partial_implementation_resume_checks_checkpoint_without_repeating_b(self):
        state = self.before(self.at_b())
        self.assertEqual(self.check(state, resume=True)["current_phase"], "implementation")
        (self.repo / "target.html").write_text("Authorized partial edit")
        with self.assertRaisesRegex(ValueError, "Interrupted implementation drift"):
            self.check(state, resume=True)
        state["implementation_checkpoint"] = w.target_hashes(self.repo, state)
        path = self.repo / "checkpoint.json"
        w.write_json(path, state)
        self.assertEqual(
            self.check(json.loads(path.read_text()), resume=True)["current_phase"], "implementation"
        )

    def test_v2_quick_keeps_initial_authorization_and_has_no_a_c_or_prototype(self):
        self.assertEqual(self.check(self.at_b("quick"))["gate"], "B")
        state = self.through_report("quick")
        self.assertEqual(self.check(state)["current_phase"], "done")
        self.assertIsNone(state["approvals"]["design"])
        self.assertIsNone(state["approvals"]["acceptance"])
        self.assertNotIn("prototype", w.phases_for(state))

    def test_quick_missing_runtime_reports_limitations_without_extra_gates(self):
        state = self.at_b("quick")
        approve(state, "implementation", self.check(state))
        for phase in w.PHASES["quick"][2:]:
            complete(state, phase)
        state["validation"] = [
            {
                "check": "Browser",
                "status": "blocked",
                "evidence": "Synthetic only",
                "limitation": "No runtime setup authorized",
            }
        ]
        self.assertEqual(self.check(state)["current_phase"], "done")
        state["validation"][0]["status"] = "pass"
        with self.assertRaisesRegex(ValueError, "disclosed blocked"):
            self.check(state)

    def test_frozen_before_and_gate_c_review_identities_cannot_be_rewritten(self):
        state = self.through_report()
        state["before_identity_sha256"] = w.digest(state["preview"]["before"])
        state["preview"]["before"]["source_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "Frozen Django BEFORE"):
            self.check(state)
        state = self.through_report()
        approve(state, "acceptance", self.check(state))
        state["preview"]["after"]["source_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "Stale Django review"):
            self.check(state)

    def test_new_tasks_create_only_core_reports_and_no_prototype(self):
        args = argparse.Namespace(
            task="synthetic-new",
            output=self.repo / "new",
            vertical="SERVICE",
            mode="full",
            route="/appointments/",
            objective="Synthetic only",
        )
        w.initialize(args)
        self.assertEqual({p.name for p in args.output.iterdir()}, set(w.CORE_REPORTS))
        state = json.loads((args.output / "state.json").read_text())
        self.assertEqual(state["schema_version"], 2)
        self.assertFalse(state["optional_prototype"]["enabled"])

    def test_commit_preparation_classifies_files_preserves_required_generated_assets_and_is_idempotent(
        self,
    ):
        state, path = self.accepted()
        fixtures = [
            ("test_journey.py", "tests"),
            ("font.woff2", "required_asset"),
            ("fixture.py", "implementation"),
            ("dist/runtime.css", "required_asset"),
        ]
        for name, category in fixtures:
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / name).write_text("Synthetic required source/asset")
            state["manifest"].append(
                {
                    "path": name,
                    "action": "add",
                    "purpose": "Reproducible dependency",
                    "category": category,
                    "vertical": "SERVICE",
                    "shared": False,
                    "before_sha256": None,
                }
            )
        # Build a new synthetic accepted binding, never modify a real approval.
        state["approvals"]["implementation"]["manifest_sha256"] = None
        state["approvals"]["acceptance"] = None
        implementation = state["approvals"]["implementation"]
        state["approvals"]["implementation"] = None
        # Compute bindings from a copy before implementation phases.
        planning = copy.deepcopy(state)
        planning["completed_phases"] = list(w.PHASES["full"][:3])
        planning["baseline"] = None
        new_manifest_sha = self.check(planning)["manifest_sha256"]
        implementation["manifest_sha256"] = new_manifest_sha
        state["approvals"]["implementation"] = implementation
        candidate = w.digest(w.target_hashes(self.repo, state))
        state["preview"]["after"]["candidate_sha256"] = candidate
        state["implementation_checkpoint"] = w.target_hashes(self.repo, state)
        approve(state, "acceptance", self.check(state))
        (path.parent / "validation.md").write_text("Final test summary")
        (path.parent / "browser.log").write_text("Disposable raw log")
        (path.parent / "screenshots").mkdir()
        (path.parent / "screenshots" / "representative.png").write_text("Selected evidence")
        (path.parent / "screenshots" / "unused.png").write_text("Disposable matrix output")
        (path.parent / "dist").mkdir()
        (path.parent / "dist" / "app.js").write_text("Disposable lab build")
        selected = (
            (path.parent / "screenshots" / "representative.png").relative_to(self.repo).as_posix()
        )
        state["artifact_inventory"].append(
            {
                "path": selected,
                "category": "documentation",
                "ownership": "task",
                "purpose": "Representative review screenshot",
            }
        )
        w.write_json(path, state)
        original = path.read_bytes()
        result = w.prepare_commit(state, path, self.repo)
        manifest = json.loads(Path(result["commit_manifest"]).read_text())
        included = {e["path"]: e["category"] for e in manifest["files"]}
        for name, category in fixtures:
            self.assertEqual(included[name], category)
        self.assertIn(selected, included)
        self.assertTrue(all(e["category"] == "generated" for e in manifest["excluded"]))
        self.assertEqual(len(manifest["excluded"]), 3)
        self.assertEqual(original, path.read_bytes())
        self.assertEqual(result, w.prepare_commit(state, path, self.repo))

    def test_commit_requires_c_and_refuses_stale_acceptance_or_unapproved_source(self):
        state, path = self.accepted()
        state["approvals"]["acceptance"] = None
        with self.assertRaisesRegex(ValueError, "Gate C"):
            w.prepare_commit(state, path, self.repo)
        approve(state, "acceptance", self.check(state))
        state["artifact_inventory"] = [
            {
                "path": "unapproved.py",
                "category": "implementation",
                "ownership": "task",
                "purpose": "Out of scope source",
            }
        ]
        with self.assertRaisesRegex(ValueError, "outside approved manifest"):
            w.prepare_commit(state, path, self.repo)
        state["artifact_inventory"] = []
        (self.repo / "target.html").write_text("Concurrent edit after C")
        with self.assertRaises(ValueError):
            w.prepare_commit(state, path, self.repo)

    def test_unknown_categories_external_required_assets_and_duplicate_inventory_fail(self):
        state = self.at_a()
        entry = {
            "path": "brief.md",
            "category": "documentation",
            "ownership": "task",
            "purpose": "Design",
        }
        state["artifact_inventory"] = [entry, entry.copy()]
        with self.assertRaisesRegex(ValueError, "Duplicate inventory"):
            self.check(state)
        entry["path"] = "/outside/font.woff2"
        state["artifact_inventory"] = [entry]
        with self.assertRaisesRegex(ValueError, "Only excluded generated"):
            self.check(state)
        entry["category"] = "generated"
        self.check(state)

    def test_protected_workspace_hashes_dirty_bytes_untracked_files_and_index(self):
        state = self.at_b()
        (self.repo / "unrelated.txt").write_text("Existing dirty bytes")
        (self.repo / "new.txt").write_text("Existing untracked bytes")
        outputs = [
            " M unrelated.txt\n?? new.txt\n",
            b"unrelated.txt\0",
            b"new.txt\0",
            b"staged diff",
        ]
        # Exercise the real read-only snapshot function rather than the setUp stub.
        real = self._protected_workspace_function
        with patch.object(w.subprocess, "check_output", side_effect=outputs) as reader:
            result = real(self.repo, state)
        self.assertEqual(result["files"]["unrelated.txt"], w.sha(self.repo / "unrelated.txt"))
        self.assertEqual(result["files"]["new.txt"], w.sha(self.repo / "new.txt"))
        self.assertEqual(result["index_sha256"], w.hashlib.sha256(b"staged diff").hexdigest())
        self.assertTrue(all(call.args[0][0] == "git" for call in reader.call_args_list))

    def test_commit_preparation_never_discards_runtime_or_fixture_source_as_generated(self):
        for name in ("src/static/assets/font.woff2", "scripts/fixture.py"):
            with self.subTest(path=name):
                state = self.at_a()
                state["artifact_inventory"] = [
                    {
                        "path": name,
                        "category": "generated",
                        "ownership": "task",
                        "purpose": "Incorrect disposable classification",
                    }
                ]
                with self.assertRaisesRegex(ValueError, "Runtime source/assets"):
                    self.check(state)

    def test_commit_preparation_requires_classification_of_unknown_task_source(self):
        state, path = self.accepted()
        (path.parent / "fixture.py").write_text("Reproducible source")
        with self.assertRaisesRegex(ValueError, "Unclassified task file"):
            w.prepare_commit(state, path, self.repo)

    def test_commit_manifest_cannot_be_silently_overwritten_after_task_artifact_changes(self):
        state, path = self.accepted()
        result = w.prepare_commit(state, path, self.repo)
        output = Path(result["commit_manifest"])
        original = output.read_bytes()
        (path.parent / "validation.md").write_text("Concurrent report edit")
        with self.assertRaisesRegex(ValueError, "Existing commit manifest differs"):
            w.prepare_commit(state, path, self.repo)
        self.assertEqual(output.read_bytes(), original)

    def test_unrelated_artifacts_are_excluded_and_never_deleted(self):
        state, path = self.accepted()
        unrelated = path.parent / "unrelated.md"
        unrelated.write_text("Another person's draft")
        state["artifact_inventory"] = [
            {
                "path": unrelated.relative_to(self.repo).as_posix(),
                "category": "documentation",
                "ownership": "unrelated",
                "purpose": "Concurrent task",
            }
        ]
        w.write_json(path, state)
        result = w.prepare_commit(state, path, self.repo)
        selection = json.loads(Path(result["commit_manifest"]).read_text())
        self.assertEqual(
            selection["excluded"][0]["path"], unrelated.relative_to(self.repo).as_posix()
        )
        self.assertEqual(unrelated.read_text(), "Another person's draft")

    def test_essential_approval_design_and_validation_records_cannot_be_excluded(self):
        state, path = self.accepted()
        state["artifact_inventory"] = [
            {
                "path": path.relative_to(self.repo).as_posix(),
                "category": "generated",
                "ownership": "task",
                "purpose": "Incorrect exclusion",
            }
        ]
        with self.assertRaisesRegex(ValueError, "Essential workflow records"):
            w.prepare_commit(state, path, self.repo)

    def test_preview_rejects_real_records_external_urls_or_shared_databases(self):
        for change, message in (
            (lambda s: s["preview"].update(synthetic_records=False), "synthetic records"),
            (
                lambda s: s["preview"]["after"].update(url="https://production.example/app/"),
                "loopback",
            ),
            (lambda s: s["preview"]["after"].update(environment_id="before"), "independent"),
        ):
            with self.subTest(message=message):
                state = self.through_report()
                change(state)
                with self.assertRaisesRegex(ValueError, message):
                    self.check(state)


class HistoricalSimulation(unittest.TestCase):
    def test_existing_appointments_documents_stop_at_b_without_reopening_work(self):
        before = {name: w.sha(w.REPO / name) for name in REPORTS}
        state = sample()
        # Only existing documents are read. These synthetic approvals are not
        # imported into any actual task or historical approval record.
        state["design_artifacts"] = {REPORTS[2]: before[REPORTS[2]]}
        for phase, reference in zip(
            w.LEGACY_PHASES["full"][:4],
            (REPORTS[0], REPORTS[1], REPORTS[2], REPORTS[2]),
            strict=True,
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
