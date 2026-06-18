#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

DEFAULT_TEST_LABELS = [
    "apps.crm.tests",
    "apps.accounts.tests",
    "apps.businesses.tests",
    "apps.billings.tests",
]
TEST_OPTIONS_WITH_VALUES = {
    "-k",
    "-p",
    "-t",
    "-v",
    "--exclude-tag",
    "--parallel",
    "--pattern",
    "--pythonpath",
    "--settings",
    "--tag",
    "--testrunner",
    "--top-level-directory",
    "--verbosity",
}


def _has_explicit_test_labels(args: list[str]) -> bool:
    skip_next = False

    for arg in args:
        if skip_next:
            skip_next = False
            continue

        if arg in TEST_OPTIONS_WITH_VALUES:
            skip_next = True
            continue

        if arg.startswith("--") and "=" in arg:
            continue

        if arg.startswith("-v") and arg != "-v":
            continue

        if arg.startswith("-p") and arg != "-p":
            continue

        if arg.startswith("-") and arg != "-":
            continue

        return True

    return False


def _with_default_test_labels(argv: list[str]) -> list[str]:
    if len(argv) < 2 or argv[1] != "test":
        return argv

    if _has_explicit_test_labels(argv[2:]):
        return argv

    return [argv[0], argv[1], *DEFAULT_TEST_LABELS, *argv[2:]]


def _apply_local_runserver_defaults(argv: list[str]) -> None:
    if len(argv) < 2 or argv[1] != "runserver":
        return

    project_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(project_dir)
    env_file = os.path.join(repo_root, ".env")

    if os.path.exists(env_file):
        return

    os.environ.setdefault("ENV", "development")
    os.environ.setdefault("DEBUG", "True")
    os.environ.setdefault("SECRET_KEY", "clarivo-local-development-secret-key")
    os.environ.setdefault("ALLOWED_HOSTS", "127.0.0.1,localhost")
    os.environ.setdefault(
        "CSRF_TRUSTED_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:8001,http://localhost:8001",
    )


def main():
    """Run administrative tasks."""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)
    _apply_local_runserver_defaults(sys.argv)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskio.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(_with_default_test_labels(sys.argv))


if __name__ == "__main__":
    main()
