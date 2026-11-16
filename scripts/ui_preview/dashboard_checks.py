"""Portable Step 7 checks, restricted to a verified disposable preview cluster."""

import argparse
import importlib.util
import inspect
import os
import socket
import subprocess
import sys
from pathlib import Path
from unittest import mock

from ui_preview.core import REPO, child_env, load_session, verify_database, verify_source


def run(root, state, browser=False):
    for name in ("before", "after"):
        verify_source(state[name]["source"])
    verify_database(root, state, "after")
    side = state["after"]
    marker = Path(side["directory"]) / "DISPOSABLE"
    if marker.exists() and marker.read_text().strip() != side["system_identifier"]:
        raise RuntimeError("Existing dashboard-test identity marker differs; nothing is replaced.")
    marker.write_text(side["system_identifier"] + "\n")
    env = child_env(root, state, "after", "test")
    env.update(
        {
            "DJANGO_SETTINGS_MODULE": "taskio.services_test_settings",
            "SERVICES_TEST_PG_PORT": str(side["port"]),
            "SERVICES_TEST_PG_USER": state["db_user"],
            "SERVICES_DASHBOARD_UI_ROOT": side["directory"],
            # Do not add the ordinary repository root: src.config must be the frozen copy.
            "PYTHONPATH": os.pathsep.join(
                [str(REPO / "scripts"), str(Path(side["source"]) / "src")]
            ),
        }
    )
    if os.environ.get("PWA_CHROMIUM"):
        env["PWA_CHROMIUM"] = os.environ["PWA_CHROMIUM"]
    stages = ["server", "before", "after"] if browser else ["server"]
    for stage in stages:
        subprocess.run(
            [
                state["python"],
                "-m",
                "ui_preview.dashboard_checks",
                "--session",
                str(root),
                "--execute-stage",
                stage,
            ],
            cwd=side["source"],
            env=env,
            check=True,
        )


def execute(root, state, stage):
    if (
        os.environ.get("DJANGO_SETTINGS_MODULE") != "taskio.services_test_settings"
        or os.environ.get("MOTIONMATE_PREVIEW_ROOT") != str(root)
        or os.environ.get("SERVICES_DASHBOARD_UI_ROOT") != state["after"]["directory"]
        or os.environ.get("SERVICES_TEST_PG_PORT") != str(state["after"]["port"])
    ):
        raise RuntimeError(
            "Use the public check-dashboard command with its sanitized child environment."
        )
    # Establish ownership and live identity before Django can create its test database.
    verify_database(root, state, "after")
    side = state["after"]
    allowed_databases = {"postgres", "test_services_rollout"}
    original_dns = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def dns(host, *args, **kwargs):
        if host not in {None, "127.0.0.1", "localhost", "::1"}:
            raise RuntimeError("Dashboard checks refuse external DNS.")
        return original_dns(host, *args, **kwargs)

    def check_address(address):
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
            raise RuntimeError("Dashboard checks refuse non-loopback connections.")
        if address[1] not in {side["port"], 8768}:
            raise RuntimeError("Dashboard checks refuse another local service.")

    def connect(sock, address):
        check_address(address)
        return original_connect(sock, address)

    def connect_ex(sock, address):
        check_address(address)
        return original_connect_ex(sock, address)

    def identity(sender, connection, **kwargs):
        configured = connection.settings_dict
        if (configured["HOST"], str(configured["PORT"])) != ("127.0.0.1", str(side["port"])):
            raise RuntimeError("Dashboard checks refuse an unowned connection.")
        # Django's no-database maintenance connection uses NAME=None for postgres.
        if configured["NAME"] not in allowed_databases | {None}:
            raise RuntimeError("Dashboard checks refuse an unowned database.")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('data_directory'), "
                "(SELECT system_identifier::text FROM pg_control_system()), current_database()"
            )
            directory, identifier, database = cursor.fetchone()
        if (directory, identifier) != (side["data_directory"], side["system_identifier"]):
            connection.close()
            raise RuntimeError("Dashboard test connection identity changed.")
        if database not in allowed_databases:
            raise RuntimeError("Unexpected dashboard test database.")

    from django.db.backends.signals import connection_created

    connection_created.connect(identity, weak=False)
    sys.argv.append("test")  # Preserve the application's existing test-mode detection.
    with (
        mock.patch("socket.getaddrinfo", dns),
        mock.patch.object(socket.socket, "connect", connect),
        mock.patch.object(socket.socket, "connect_ex", connect_ex),
    ):
        import django

        django.setup()
        from django.conf import settings
        from django.test.utils import get_runner, override_settings

        overrides = {
            "STRIPE_ENABLED": False,
            "STRIPE_SECRET_KEY": "",
            "STRIPE_PUBLISHABLE_KEY": "",
            "STRIPE_WEBHOOK_SECRET": "",
        }
        if stage == "before":
            before = Path(state["before"]["source"])
            overrides["TEMPLATES"] = [
                {
                    **settings.TEMPLATES[0],
                    "DIRS": [str(before / "src/templates"), *settings.TEMPLATES[0]["DIRS"]],
                }
            ]
            original = before / "src/apps/crm/views.py"
            spec = importlib.util.spec_from_file_location("apps.crm.views", original)
            module = importlib.util.module_from_spec(spec)
            sys.modules["apps.crm.views"] = module
            spec.loader.exec_module(module)
            import apps.crm

            apps.crm.views = module
            from django.urls import resolve, reverse

            if (
                Path(inspect.unwrap(resolve(reverse("agent_dashboard")).func).__code__.co_filename)
                != original
            ):
                raise RuntimeError("Original dashboard view was not selected.")
        labels = ["apps.crm.test_services_dashboard_ui"]
        if stage != "server":
            os.environ["SERVICES_DASHBOARD_UI_STAGE"] = stage
            labels = ["services_dashboard_ui_browser_check"]
        with override_settings(**overrides):
            runner = get_runner(settings)(verbosity=1, interactive=False, debug_mode=True)
            failures = runner.run_tests(labels)
        raise SystemExit(bool(failures))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--execute-stage", required=True, choices=["server", "before", "after"])
    args = parser.parse_args()
    root, state = load_session(args.session)
    execute(root, state, args.execute_stage)
