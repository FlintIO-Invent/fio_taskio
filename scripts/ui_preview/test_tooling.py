"""Safety/snapshot tests. No Django application initialization or database access."""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.error import URLError

import check_ui_workflow as workflow
from ui_preview import cli, core, guard


class StaticWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def document(self, target):
        (self.root / "README.md").write_text(f"[Reference]({target})\n")

    def test_missing_optional_local_references_are_reported(self):
        for target in (
            "design_references/phoenix/package.json",
            "ui-lab/services-dashboard/tabler/dist/index.html",
            "ui-lab/services-appointments/dist/index.html",
        ):
            with self.subTest(target=target):
                self.document(target)
                failures, historical, optional = workflow.documentation_link_failures(
                    self.root, ["README.md"]
                )
                self.assertEqual(failures, [])
                self.assertEqual(historical, [])
                self.assertEqual(optional, [target])

    def test_missing_manifest_source_fails_without_a_document_link(self):
        self.document("https://example.invalid/")
        failures = workflow.manifest_failures(
            self.root, ["README.md", "scripts/ui_preview/runtime.py"]
        )
        self.assertEqual(len(failures), 1)
        self.assertIn("scripts/ui_preview/runtime.py", failures[0])

    def test_manifest_file_inside_optional_tree_is_required(self):
        target = "design_references/phoenix/required.json"
        self.document(target)
        names = ["README.md", target]
        self.assertTrue(workflow.manifest_failures(self.root, names))
        failures, _, optional = workflow.documentation_link_failures(self.root, names)
        self.assertEqual(len(failures), 1)
        self.assertEqual(optional, [])

    def test_essential_screenshot_inside_historical_tree_is_required(self):
        target = "ui-lab/services-dashboard/daisyui/evidence/step4/screenshots/essential.png"
        self.document(target)
        names = ["README.md", target]
        self.assertTrue(workflow.manifest_failures(self.root, names))
        failures, historical, _ = workflow.documentation_link_failures(self.root, names)
        self.assertEqual(len(failures), 1)
        self.assertEqual(historical, [])

    def test_known_historical_gallery_remains_optional(self):
        target = "ui-lab/services-dashboard/evidence/gallery.html"
        self.document(target)
        failures, historical, optional = workflow.documentation_link_failures(
            self.root, ["README.md"]
        )
        self.assertEqual(failures, [])
        self.assertEqual(historical, [target])
        self.assertEqual(optional, [])

    def test_arbitrary_evidence_path_does_not_hide_a_missing_source(self):
        self.document("scripts/evidence/required.py")
        failures, historical, optional = workflow.documentation_link_failures(
            self.root, ["README.md"]
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(historical, [])
        self.assertEqual(optional, [])

    def test_missing_required_markdown_is_reported_without_reading_it(self):
        names = ["README.md"]
        self.assertTrue(workflow.manifest_failures(self.root, names))
        self.assertEqual(workflow.documentation_link_failures(self.root, names), ([], [], []))

    def test_unsafe_and_duplicate_manifest_entries_still_fail(self):
        self.document("https://example.invalid/")
        failures = workflow.manifest_failures(
            self.root, ["README.md", "README.md", "../outside.py", "/outside.py"]
        )
        self.assertEqual(len(failures), 3)


class LauncherToolingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        custom = self.base / "custom-temp"
        custom.mkdir()
        self.enterContext(mock.patch.dict(os.environ, {"TMPDIR": str(custom)}))
        self.enterContext(mock.patch.object(tempfile, "tempdir", None))
        self.root, marker = core.make_root("session")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.state = {
            "id": marker["id"],
            "root": str(self.root),
            "python": sys.executable,
            "password": "synthetic-fixture-only",
            "clock": "2026-11-15T12:00:00+00:00",
            "route": "/crm/agent/dashboard/",
            "comparison": "captured",
            "launcher_port": port,
        }
        for i, name in enumerate(core.SIDES):
            directory = self.root / name
            directory.mkdir()
            source = self.root / "sources" / name
            source.mkdir(parents=True)
            self.state[name] = {
                "directory": str(directory),
                "data_directory": str(directory / "pgdata"),
                "host": "127.0.0.1",
                "port": 55480 + i,
                "http_port": 8890 + i,
                "database": f"mm_preview_{marker['id']}_{name}",
                "source": str(source),
            }
            core.write_json(directory / "fixtures.json", {"accounts": []})
        core.write_json(self.root / "session.json", self.state)
        shutil.copytree(
            Path(core.__file__).parent,
            self.root / "tooling/ui_preview",
            ignore=shutil.ignore_patterns("__pycache__", "test_*.py"),
        )
        self.children = []
        actual_popen = subprocess.Popen

        def spawn(*args, **kwargs):
            child = actual_popen(*args, **kwargs)
            self.children.append(child)
            return child

        self.enterContext(mock.patch.object(cli.subprocess, "Popen", side_effect=spawn))
        self.addCleanup(self.stop_children)

    def stop_children(self):
        for child in self.children:
            if child.poll() is None:
                core.stop_process(core.process_record(child.pid), "ui_preview.launcher", self.root)
            child.wait(timeout=5)

    def test_custom_tmpdir_launcher_is_ready_before_cli_reports_success(self):
        with (
            mock.patch.object(cli, "pg_start"),
            mock.patch.object(cli, "spawn"),
            mock.patch.object(cli, "health"),
            mock.patch.object(sys, "argv", ["preview", "start", "--session", str(self.root)]),
            redirect_stdout(StringIO()) as output,
        ):
            cli.main()
        self.assertIn('"launcher"', output.getvalue())
        cli.launcher_health(self.state)
        child_env = Path(f"/proc/{self.children[0].pid}/environ").read_bytes().split(b"\0")
        self.assertIn(f"TMPDIR={self.root.parent}".encode(), child_env)
        self.assertFalse(any(value.startswith(b"PYTHONMALLOC=") for value in child_env))
        self.assertEqual(list(self.root.rglob("pgdata")), [])

    def test_launcher_environment_is_validated_and_drops_credentials(self):
        with mock.patch.dict(
            os.environ,
            {
                "DATABASE_URL": "synthetic-ordinary-database",
                "HTTP_PROXY": "synthetic-proxy",
                "PYTHONMALLOC": "debug",
            },
        ):
            env = cli.launcher_environment(self.root, self.state)
        self.assertEqual(env["TMPDIR"], str(self.root.parent))
        for name in ("DATABASE_URL", "HTTP_PROXY", "PYTHONMALLOC"):
            self.assertNotIn(name, env)

    def test_changed_session_identity_is_rejected_before_spawn(self):
        with self.assertRaises(RuntimeError):
            cli.start_launcher(self.root, {**self.state, "id": "unowned"})
        self.assertEqual(self.children, [])

    def test_launcher_exit_returns_nonzero_cli_status(self):
        (self.root / "tooling/ui_preview/launcher.py").write_text("raise SystemExit(7)\n")
        with (
            mock.patch.object(cli, "pg_start"),
            mock.patch.object(cli, "spawn"),
            mock.patch.object(cli, "health"),
            mock.patch.object(sys, "argv", ["preview", "start", "--session", str(self.root)]),
            redirect_stderr(StringIO()) as error,
            self.assertRaises(SystemExit) as exited,
        ):
            cli.main()
        self.assertEqual(exited.exception.code, 1)
        self.assertIn("launcher stopped", error.getvalue())

    def test_live_but_unready_launcher_times_out(self):
        with (
            mock.patch.object(cli, "process_alive", return_value=True),
            mock.patch.object(cli, "launcher_health", side_effect=URLError("not ready")),
            mock.patch.object(cli.time, "monotonic", side_effect=[0, 0, 11]),
            mock.patch.object(cli.time, "sleep"),
            self.assertRaisesRegex(RuntimeError, "did not become ready"),
        ):
            cli.start_launcher(self.root, self.state)

    def test_wrong_http_service_or_session_is_rejected(self):
        for service, session in (("before", self.state["id"]), ("launcher", "other-session")):
            response = SimpleNamespace(
                headers={"X-Motionmate-Preview": service, "X-Motionmate-Preview-Session": session},
                read=mock.Mock(),
            )
            with mock.patch.object(cli, "build_opener") as opener:
                opener.return_value.open.return_value.__enter__.return_value = response
                with self.assertRaisesRegex(RuntimeError, "not this preview launcher"):
                    cli.launcher_health(self.state)
            response.read.assert_not_called()


class PreviewToolingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def fake_repo(self):
        repo = self.root / "repo"
        for name in core.RUNTIME_DIRS:
            (repo / "src" / name).mkdir(parents=True)
        for name in core.RUNTIME_FILES:
            (repo / "src" / name).write_text("# local fixture\n")
        return repo

    def test_snapshot_includes_untracked_source_excludes_data_and_is_independent(self):
        repo = self.fake_repo()
        code = repo / "src/apps/untracked.py"
        code.write_text("before\n")
        (repo / "src/untracked_helper.py").write_text("# root helper\n")
        (repo / ".env").write_text("do not copy")
        (repo / "src/media").mkdir()
        (repo / "src/media/private.txt").write_text("ordinary data")
        target = self.root / "snapshot"
        core.snapshot(repo, target)
        code.write_text("after\n")
        self.assertEqual((target / "src/apps/untracked.py").read_text(), "before\n")
        self.assertTrue((target / "src/untracked_helper.py").is_file())
        self.assertFalse((target / ".env").exists())
        self.assertFalse((target / "src/media").exists())
        core.verify_source(target)
        (target / "src/apps/untracked.py").write_text("tamper")
        with self.assertRaises(RuntimeError):
            core.verify_source(target)

    def test_symlinks_are_rejected_in_runtime_sources(self):
        repo = self.fake_repo()
        (repo / "src/apps/link").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            core.snapshot(repo, self.root / "snapshot")

    def test_step7_reconstruction_requires_proof_for_every_changed_file(self):
        repo = self.fake_repo()
        source = core.snapshot(repo, self.root / "source")
        saved = self.root / "saved"
        saved.mkdir()
        before = json.loads((source / "source.json").read_text())["files"]
        old = saved / "original/src/config.py"
        old.parent.mkdir(parents=True)
        old.write_text("# original\n")
        before["src/config.py"] = core.digest(old)
        core.write_json(saved / "before-sha256.json", before)
        core.restore_step7_before(source, saved)
        self.assertEqual((source / "src/config.py").read_text(), "# original\n")
        core.verify_source(source)
        before["src/helpers.py"] = "unproven"
        core.write_json(saved / "before-sha256.json", before)
        with self.assertRaises(RuntimeError):
            core.restore_step7_before(source, saved)

    def test_ownership_rejects_ordinary_directory_and_symlink(self):
        with self.assertRaises(RuntimeError):
            core.owned_root(self.root)
        root, _ = core.make_root("snapshot")
        self.addCleanup(shutil.rmtree, root)
        self.assertEqual(core.owned_root(root, "snapshot")[0], root)
        link = self.root / "link"
        link.symlink_to(root, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            core.owned_root(link, "snapshot")

    def test_child_environment_drops_credentials_proxies_and_normal_database(self):
        side = {
            "secret": "synthetic",
            "port": 55488,
            "database": "mm_preview_test_before",
            "source": str(self.root / "source"),
            "directory": str(self.root / "before"),
            "http_port": 8780,
        }
        with mock.patch.dict(
            os.environ,
            {
                "DATABASE_URL": "secret-normal-database",
                "STRIPE_SECRET_KEY": "secret-provider",
                "HTTP_PROXY": "external-proxy",
            },
        ):
            env = core.child_env(
                self.root, {"before": side, "db_user": "preview"}, "before", "serve"
            )
        for name in ("DATABASE_URL", "STRIPE_SECRET_KEY", "HTTP_PROXY"):
            self.assertNotIn(name, env)
        self.assertEqual(env["DB_PORT"], "55488")
        self.assertEqual(env["DB_NAME"], "mm_preview_test_before")

    def test_runtime_blocks_financial_and_schema_writes_but_allows_real_auth_and_setup(self):
        with mock.patch.object(
            guard, "settings", SimpleNamespace(SIDE={"directory": str(self.root)})
        ):
            execute = mock.Mock(return_value="real query")
            for sql in [
                'INSERT INTO "billings_invoice" VALUES (1)',
                "UPDATE businesses_businesssubscription SET status=1",
                "DELETE FROM logistics_logisticscharge",
                "DROP TABLE accounts_taskiouser",
            ]:
                with self.subTest(sql=sql), self.assertRaises(guard.PreviewWriteBlocked):
                    guard.runtime_writes(execute, sql, [], False, {})
            execute.assert_not_called()
            self.assertEqual(
                guard.runtime_writes(
                    execute, "INSERT INTO django_session VALUES (1)", [], False, {}
                ),
                "real query",
            )
            self.assertEqual(
                guard.runtime_writes(
                    execute,
                    "UPDATE businesses_useronboardingstate SET completed_welcome=true",
                    [],
                    False,
                    {},
                ),
                "real query",
            )

    def test_network_guard_blocks_before_dns_or_other_local_database_connect(self):
        with (
            mock.patch.object(
                guard,
                "settings",
                SimpleNamespace(SIDE={"directory": str(self.root), "port": 55488}),
            ),
            mock.patch("socket.getaddrinfo"),
            mock.patch.object(socket.socket, "connect"),
            mock.patch.object(socket.socket, "connect_ex"),
        ):
            guard.network_guard()
            with self.assertRaises(RuntimeError):
                socket.getaddrinfo("example.invalid", 443)
            with socket.socket() as sock:
                with self.assertRaises(RuntimeError):
                    sock.connect(("127.0.0.1", 5432))

    def test_stop_refuses_unrelated_process_without_signalling(self):
        record = core.process_record(os.getpid())
        with mock.patch("os.kill") as kill, self.assertRaises(RuntimeError):
            core.stop_process(record, "a-preview-process-that-is-not-this-command")
        kill.assert_not_called()

    def test_database_identity_failure_stops_before_connect(self):
        with (
            mock.patch.object(core, "load_session", return_value=(self.root, {"id": "owned"})),
            mock.patch.object(
                core, "control_identity", side_effect=RuntimeError("identifier changed")
            ),
            mock.patch.object(core.psycopg2, "connect") as connect,
        ):
            with self.assertRaises(RuntimeError):
                core.verify_database(self.root, {"id": "owned", "before": {}}, "before")
            connect.assert_not_called()


class AppointmentAdapterTests(unittest.TestCase):
    def test_fixture_refuses_ordinary_environment_before_model_import(self):
        from ui_preview.appointments_fixtures import seed

        with mock.patch.dict(
            os.environ,
            {"DJANGO_SETTINGS_MODULE": "taskio.settings", "MOTIONMATE_PREVIEW_PHASE": "serve"},
        ):
            with self.assertRaisesRegex(RuntimeError, "verified preview setup"):
                seed({})

    def test_adapter_verifies_sources_before_database_or_writes(self):
        from ui_preview import appointments_checks as checks

        with (
            mock.patch.object(checks, "verify_source", side_effect=RuntimeError("changed source")),
            mock.patch.object(checks, "verify_database") as database,
        ):
            with self.assertRaisesRegex(RuntimeError, "changed source"):
                checks.prepare(Path("/missing"), {"before": {"source": "/missing"}})
            database.assert_not_called()

    def test_adapter_verifies_database_before_marker_or_child_environment(self):
        from ui_preview import appointments_checks as checks

        state = {"before": {"source": "/before"}, "after": {"source": "/after"}}
        with (
            mock.patch.object(checks, "verify_source"),
            mock.patch.object(
                checks, "verify_database", side_effect=RuntimeError("unowned database")
            ),
            mock.patch.object(checks, "child_env") as child,
        ):
            with self.assertRaisesRegex(RuntimeError, "unowned database"):
                checks.prepare(Path("/missing"), state)
            child.assert_not_called()


if __name__ == "__main__":
    unittest.main()
