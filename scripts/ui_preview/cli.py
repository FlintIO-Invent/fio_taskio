"""Explicit snapshot/create/start/stop/refresh/validate commands, no release hooks."""

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from ui_preview.core import (
    REPO,
    SIDES,
    free_port,
    initialize,
    load_session,
    make_root,
    new_session,
    owned_root,
    pg_start,
    process_alive,
    process_record,
    snapshot,
    snapshot_git,
    spawn,
    stop_process,
    stop_side,
    verify_database,
    verify_source,
    write_json,
)


def health(state, name):
    url = f"http://127.0.0.1:{state[name]['http_port']}/_preview/health"
    with build_opener(ProxyHandler({})).open(url, timeout=3) as response:
        value = json.load(response)
    if value["session"] != state["id"] or value["side"] != name:
        raise RuntimeError("HTTP listener is not this preview side.")
    return value


def launcher_environment(root, state):
    validated_root, validated_state = load_session(root)
    if validated_root != root or validated_state["id"] != state["id"]:
        raise RuntimeError("Launcher session ownership/identity changed.")
    env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG") if key in os.environ}
    env.update(
        PYTHONPATH=str(root / "tooling"),
        PYTHONDONTWRITEBYTECODE="1",
        # Preserve the namespace load_session validated, including custom TMPDIR.
        TMPDIR=str(validated_root.parent),
    )
    return env


def launcher_health(state):
    url = f"http://127.0.0.1:{state['launcher_port']}/"
    with build_opener(ProxyHandler({})).open(url, timeout=1) as response:
        if (
            response.headers.get("X-Motionmate-Preview") != "launcher"
            or response.headers.get("X-Motionmate-Preview-Session") != state["id"]
        ):
            raise RuntimeError("HTTP listener is not this preview launcher session.")
        # The actual landing page must render successfully; never log its test credentials.
        response.read()


def start_launcher(root, state):
    env = launcher_environment(root, state)
    process = None
    if not process_alive(state.get("launcher_process")):
        free_port(state["launcher_port"])
        with (root / "launcher.log").open("a") as log:
            process = subprocess.Popen(
                [state["python"], "-m", "ui_preview.launcher", "--session", str(root)],
                cwd=root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        state["launcher_process"] = process_record(process.pid)
        write_json(root / "session.json", state)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not process_alive(state.get("launcher_process")):
            if process is not None:
                process.wait()
            raise RuntimeError(f"Preview launcher stopped; inspect {root / 'launcher.log'}")
        try:
            launcher_health(state)
            return
        except (URLError, ConnectionError, TimeoutError):
            time.sleep(0.1)
    raise RuntimeError(f"Preview launcher did not become ready; inspect {root / 'launcher.log'}")


def start(root, state, names=SIDES):
    for name in names:
        if not (Path(state[name]["directory"]) / "fixtures.json").is_file():
            raise RuntimeError(
                "Preview setup is incomplete; no existing data is automatically reset."
            )
        pg_start(root, state, name)
        spawn(root, state, name)
        for _ in range(100):
            try:
                health(state, name)
                break
            except (URLError, ConnectionError, TimeoutError):
                if not process_alive(state[name].get("process")):
                    raise RuntimeError(
                        f"{name} server stopped; inspect {root / name / 'server.log'}"
                    ) from None
                time.sleep(0.1)
        else:
            raise RuntimeError(f"{name} preview did not become ready.")
    start_launcher(root, state)


def display(root, state):
    print(
        json.dumps(
            {
                "session": str(root),
                "id": state["id"],
                "launcher": f"http://127.0.0.1:{state['launcher_port']}/",
                **{
                    name: f"http://127.0.0.1:{state[name]['http_port']}{state['route']}"
                    for name in SIDES
                },
            },
            indent=2,
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser(
        "capture",
        help="Freeze current runtime files, including untracked edits; no database operation.",
    )
    capture.add_argument("--repo", type=Path, default=REPO)
    capture.add_argument(
        "--git-ref", help="Read a local historical commit; never changes the checkout."
    )
    create = sub.add_parser(
        "create", help="Create independent source/PG pairs and start both real apps."
    )
    create.add_argument("--repo", type=Path, default=REPO)
    group = create.add_mutually_exclusive_group()
    group.add_argument("--before-snapshot", type=Path)
    group.add_argument(
        "--before-step7", type=Path, help="Legacy local-backup adapter; prefer capture --git-ref."
    )
    create.add_argument("--route", default="/crm/agent/dashboard/")
    for name, default in [
        ("before-port", 8780),
        ("after-port", 8781),
        ("launcher-port", 8782),
        ("before-pg-port", 55488),
        ("after-pg-port", 55489),
    ]:
        create.add_argument("--" + name, type=int, default=default)
    for name in [
        "start",
        "stop",
        "status",
        "refresh-after",
        "validate",
        "check-dashboard",
        "cleanup",
    ]:
        command = sub.add_parser(name)
        command.add_argument("--session", type=Path, required=True)
        if name in {"start", "stop"}:
            command.add_argument("--side", choices=["before", "after", "both"], default="both")
        if name == "refresh-after":
            command.add_argument("--repo", type=Path, default=REPO)
        if name == "cleanup":
            command.add_argument(
                "--confirm",
                required=True,
                help="Exact session id; refuses live processes/clusters.",
            )
        if name == "check-dashboard":
            command.add_argument(
                "--browser", action="store_true", help="Run the actual Django/Chromium suite too."
            )
    args = parser.parse_args()
    try:
        if args.command == "capture":
            root, _ = make_root("snapshot")
            if args.git_ref:
                snapshot_git(args.repo, root / "source", args.git_ref)
            else:
                snapshot(args.repo, root / "source")
            print(root)
            return
        if args.command == "create":
            root, state = new_session(
                args.repo,
                args.before_snapshot,
                args.before_step7,
                (
                    args.before_port,
                    args.after_port,
                    args.launcher_port,
                    args.before_pg_port,
                    args.after_pg_port,
                ),
                args.route,
            )
            print(f"Owned disposable session: {root}", flush=True)
            for name in SIDES:
                initialize(root, state, name)
                print(f"Verified, migrated and seeded {name} private cluster.", flush=True)
            before = json.loads((root / "before/fixtures.json").read_text())
            after = json.loads((root / "after/fixtures.json").read_text())
            if before != after:
                raise RuntimeError("Synthetic fixtures differ; previews are not started.")
            start(root, state)
            display(root, state)
            return
        root, state = load_session(args.session)
        if args.command == "start":
            start(root, state, SIDES if args.side == "both" else [args.side])
            display(root, state)
        elif args.command == "stop":
            for name in SIDES if args.side == "both" else [args.side]:
                stop_side(root, state, name)
            if args.side == "both":
                stop_process(state.get("launcher_process"), "ui_preview.launcher", root)
                state.pop("launcher_process", None)
                write_json(root / "session.json", state)
            print("Stopped only the selected owned preview processes/clusters.")
        elif args.command == "status":
            display(root, state)
            for name in SIDES:
                if (Path(state[name]["data_directory"]) / "postmaster.pid").exists():
                    identity = verify_database(root, state, name)
                    print(name, json.dumps(identity, sort_keys=True))
                else:
                    print(name, "PostgreSQL stopped")
                if process_alive(state[name].get("process")):
                    status = health(state, name)
                    print(
                        name,
                        "Django running; source",
                        status["source_sha256"],
                        "cookie",
                        status["cookie_name"],
                    )
        elif args.command == "refresh-after":
            verify_database(root, state, "after")
            current = Path(state["after"]["source"])
            candidate = root / "sources" / f"after-{time.time_ns()}"
            snapshot(args.repo, candidate)
            old = verify_source(current)["files"]
            new = verify_source(candidate)["files"]

            def migrations(data):
                return {k: v for k, v in data.items() if "/migrations/" in k and k.endswith(".py")}

            if migrations(old) != migrations(new):
                raise RuntimeError(
                    "Migration sources changed. Refresh refuses schema work; request separate scope."
                )
            stop_process(state["after"].get("process"), "ui_preview.runtime serve", root)
            state["after"].pop("process", None)
            state["after"]["source"] = str(candidate)
            if old != new:
                state["comparison"] = "captured"
            write_json(root / "session.json", state)
            start(root, state, ["after"])
            display(root, state)
        elif args.command == "validate":
            for name in SIDES:
                verify_database(root, state, name)
                verify_source(state[name]["source"])
                health(state, name)
            from ui_preview.validate import validate

            validate(root, state)
        elif args.command == "check-dashboard":
            from ui_preview.dashboard_checks import run

            run(root, state, browser=args.browser)
        elif args.command == "cleanup":
            if args.confirm != state["id"]:
                raise RuntimeError("Cleanup requires the exact session id.")
            if process_alive(state.get("launcher_process")) or any(
                process_alive(state[n].get("process"))
                or (Path(state[n]["data_directory"]) / "postmaster.pid").exists()
                for n in SIDES
            ):
                raise RuntimeError(
                    "Stop both previews before cleanup; no process is stopped implicitly."
                )
            owned_root(root)
            if not shutil.rmtree.avoids_symlink_attacks:
                raise RuntimeError("This platform does not support safe owned-directory cleanup.")
            shutil.rmtree(root)
            print("Removed only the stopped owned synthetic preview session.")
    except (RuntimeError, OSError, subprocess.CalledProcessError, ValueError) as error:
        parser.exit(
            1,
            f"Preview stopped: {error}\nNo fallback to an ordinary database or server is attempted.\n",
        )


if __name__ == "__main__":
    main()
