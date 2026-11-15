"""Source snapshots and ownership/identity gates, independent of Django settings."""

import hashlib
import json
import os
import pwd
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg2

REPO = Path(__file__).resolve().parents[2]
RUNTIME_DIRS = ("apps", "taskio", "templates", "static")
RUNTIME_FILES = ("config.py", "helpers.py", "manage.py")
SKIP = {"__pycache__", ".DS_Store"}
SIDES = ("before", "after")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def owned_root(path, kind="session"):
    raw = Path(path).absolute()
    if raw.is_symlink() or raw != raw.resolve():
        raise RuntimeError("Preview paths must be real directories, without symlink ancestors.")
    if raw.parent != Path(tempfile.gettempdir()).resolve() or not raw.name.startswith(
        "motionmate-preview-"
    ):
        raise RuntimeError("Refusing a directory outside the owned temporary preview namespace.")
    marker = json.loads((raw / "owner.json").read_text())
    if marker["uid"] != os.getuid() or raw.stat().st_uid != os.getuid() or marker["kind"] != kind:
        raise RuntimeError("Preview ownership/kind does not match.")
    return raw, marker


def make_root(kind):
    root = Path(tempfile.mkdtemp(prefix=f"motionmate-preview-{kind}-"))
    root.chmod(0o700)
    marker = {"version": 1, "kind": kind, "uid": os.getuid(), "id": secrets.token_hex(8)}
    write_json(root / "owner.json", marker)
    return root, marker


def runtime_paths(repo):
    repo = Path(repo).resolve()
    paths = []
    for name in RUNTIME_DIRS:
        start = repo / "src" / name
        if start.is_symlink() or not start.is_dir() or not start.resolve().is_relative_to(repo):
            raise RuntimeError(
                "Runtime source roots must be real directories inside the selected source."
            )
        for parent, dirs, files in os.walk(start, followlinks=False):
            for entry in dirs + files:
                if (Path(parent) / entry).is_symlink():
                    raise RuntimeError(f"Runtime snapshot refuses symlink: {Path(parent) / entry}")
            dirs[:] = sorted(d for d in dirs if d not in SKIP)
            paths.extend(
                Path(parent) / f for f in sorted(files) if f not in SKIP and not f.endswith(".pyc")
            )
    paths += sorted((repo / "src").glob("*.py"))
    if any(path.is_symlink() for path in paths):
        raise RuntimeError("Runtime source files must not be symlinks.")
    return paths


def snapshot(source, target):
    """Copy runtime sources, including uncommitted/untracked bytes; no data/secrets."""
    source, target = Path(source).resolve(), Path(target)
    target.mkdir(parents=True, exist_ok=False)
    for name in RUNTIME_DIRS:
        (target / "src" / name).mkdir(parents=True)
    hashes = {}
    for path in runtime_paths(source):
        name = path.relative_to(source).as_posix()
        before = digest(path)
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        if digest(destination) != before or digest(path) != before:
            raise RuntimeError(f"Source changed during snapshot: {name}")
        hashes[name] = before
    metadata = {"version": 1, "files": hashes, "sha256": source_digest(hashes)}
    prior = source / "source.json"
    if prior.is_file():
        origin = json.loads(prior.read_text())
        if origin.get("files") == hashes and origin.get("sha256") == metadata["sha256"]:
            if origin.get("git_commit"):
                metadata["git_commit"] = origin["git_commit"]
    write_json(target / "source.json", metadata)
    return target


def source_digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def snapshot_git(repo, target, ref):
    """Read runtime blobs from a local commit without checkout/reset or database work."""
    repo, target = Path(repo).resolve(), Path(target)
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1"}
    command = ["git", "-C", str(repo)]
    commit = subprocess.check_output(
        [*command, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
        env=env,
        text=True,
    ).strip()
    tree = subprocess.check_output(
        [*command, "ls-tree", "-rz", "--full-tree", commit, "--", "src"],
        env=env,
    )
    selected = []
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        metadata, encoded_name = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        name = encoded_name.decode()
        path = Path(name)
        runtime = name.startswith(tuple(f"src/{d}/" for d in RUNTIME_DIRS)) or (
            path.parent == Path("src") and path.suffix == ".py"
        )
        if not runtime or any(part in SKIP for part in path.parts) or name.endswith(".pyc"):
            continue
        if (
            path.is_absolute()
            or ".." in path.parts
            or kind != "blob"
            or mode
            not in {
                "100644",
                "100755",
            }
        ):
            raise RuntimeError(f"Git runtime snapshot refuses unsafe entry: {name}")
        selected.append((name, oid))
    for directory in RUNTIME_DIRS:
        if not any(name.startswith(f"src/{directory}/") for name, _ in selected):
            raise RuntimeError(f"Git baseline is missing runtime directory: {directory}")
    if target.exists() or target.is_symlink():
        raise RuntimeError("Git snapshot destination must be new.")
    target.mkdir(parents=True)
    hashes = {}
    with subprocess.Popen(
        [*command, "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env=env,
    ) as blobs:
        try:
            for name, oid in selected:
                blobs.stdin.write((oid + "\n").encode())
                blobs.stdin.flush()
                header = blobs.stdout.readline().decode().strip().split()
                if len(header) != 3 or header[:2] != [oid, "blob"]:
                    raise RuntimeError(f"Unexpected Git blob response: {name}")
                content = blobs.stdout.read(int(header[2]))
                if len(content) != int(header[2]) or blobs.stdout.read(1) != b"\n":
                    raise RuntimeError(f"Incomplete Git blob: {name}")
                destination = target / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
                hashes[name] = hashlib.sha256(content).hexdigest()
        except BaseException:
            blobs.kill()
            raise
        finally:
            blobs.stdin.close()
        if blobs.wait() != 0:
            raise RuntimeError("Git snapshot failed; no preview is started.")
    write_json(
        target / "source.json",
        {
            "version": 1,
            "files": hashes,
            "sha256": source_digest(hashes),
            "git_commit": commit,
        },
    )
    verify_source(target)
    return target


def verify_source(path):
    path = Path(path)
    saved = json.loads((path / "source.json").read_text())
    actual = {p.relative_to(path).as_posix(): digest(p) for p in runtime_paths(path)}
    if saved["files"] != actual or source_digest(actual) != saved["sha256"]:
        raise RuntimeError(f"Frozen source was modified: {path}")
    if (path / ".env").exists():
        raise RuntimeError("Environment files are forbidden in a preview snapshot.")
    return saved


def restore_step7_before(source, saved):
    """Reconstruct only if every included pre-change byte has a proven source."""
    saved = Path(saved).resolve()
    before = json.loads((saved / "before-sha256.json").read_text())
    current = json.loads((source / "source.json").read_text())["files"]
    restored, removed = [], []
    for name in list(current):
        if name not in before:
            # New Step 7 runtime files have no place in the original source.
            (source / name).unlink()
            del current[name]
            removed.append(name)
        elif current[name] != before[name]:
            original = saved / "original" / name
            if not original.is_file() or digest(original) != before[name]:
                raise RuntimeError(f"Cannot reconstruct verified original: {name}")
            shutil.copyfile(original, source / name)
            current[name] = before[name]
            restored.append(name)
    for name, expected in before.items():
        if name.startswith(tuple(f"src/{d}/" for d in RUNTIME_DIRS)) or (
            Path(name).parent == Path("src") and name.endswith(".py")
        ):
            if current.get(name) != expected:
                raise RuntimeError(f"Saved baseline file is missing: {name}")
    write_json(
        source / "source.json",
        {
            "version": 1,
            "files": current,
            "sha256": source_digest(current),
            "reconstruction": {
                "saved": str(saved),
                "restored": restored,
                "excluded_step7_files": removed,
            },
        },
    )
    verify_source(source)


def free_port(port):
    if not 1024 <= port <= 65535 or port == 5432:
        raise RuntimeError(
            "Preview ports must be unprivileged and cannot use PostgreSQL port 5432."
        )
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))


def load_session(path):
    root, marker = owned_root(path)
    state = json.loads((root / "session.json").read_text())
    if state["id"] != marker["id"] or state["root"] != str(root):
        raise RuntimeError("Session marker/manifest mismatch.")
    for side in SIDES:
        item = state[side]
        expected = root / side
        if (
            item["directory"] != str(expected)
            or item["host"] != "127.0.0.1"
            or item["data_directory"] != str(expected / "pgdata")
        ):
            raise RuntimeError("Preview side escaped its owned session directory.")
        if not item["database"].startswith(f"mm_preview_{state['id']}_"):
            raise RuntimeError("Database name is not owned by this preview session.")
        if item["port"] == 5432 or not Path(item["source"]).resolve().is_relative_to(
            root / "sources"
        ):
            raise RuntimeError("Unsafe preview source or PostgreSQL port.")
    return root, state


def pg_bin():
    pg_config = shutil.which("pg_config")
    if not pg_config:
        raise RuntimeError("Installed PostgreSQL tools are required; no installation is attempted.")
    return Path(subprocess.check_output([pg_config, "--bindir"], text=True).strip())


def control_identity(side):
    directory = Path(side["data_directory"])
    if directory.is_symlink() or directory.resolve() != directory:
        raise RuntimeError("PostgreSQL data directory is a symlink.")
    output = subprocess.check_output(
        [str(pg_bin() / "pg_controldata"), str(directory)],
        text=True,
        env={**os.environ, "LC_ALL": "C"},
    )
    identifier = next(
        line.split(":", 1)[1].strip()
        for line in output.splitlines()
        if line.startswith("Database system identifier:")
    )
    if identifier != side["system_identifier"]:
        raise RuntimeError("PostgreSQL on-disk system identifier changed.")


def verify_database(root, state, name, database=None):
    """Offline ownership/process proof precedes the first identity-only connection."""
    loaded_root, loaded_state = load_session(root)
    if loaded_root != root or loaded_state["id"] != state["id"]:
        raise RuntimeError("Session ownership changed.")
    side = state[name]
    control_identity(side)
    pid_lines = (Path(side["data_directory"]) / "postmaster.pid").read_text().splitlines()
    if (
        Path(pid_lines[1]) != Path(side["data_directory"])
        or int(pid_lines[3]) != side["port"]
        or pid_lines[5] != "127.0.0.1"
    ):
        raise RuntimeError(
            "PostgreSQL live PID file does not match the private directory/listener."
        )
    command = Path(f"/proc/{int(pid_lines[0])}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    if side["data_directory"] not in command:
        raise RuntimeError("Postmaster process is not the owned preview cluster.")
    target = database or side["database"]
    if target not in {"postgres", side["database"]}:
        raise RuntimeError("Refusing an unowned database name.")
    with psycopg2.connect(
        host=side["host"],
        port=side["port"],
        dbname=target,
        user=state["db_user"],
        connect_timeout=3,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT host(inet_server_addr()), inet_server_port(), current_setting('data_directory'), (SELECT system_identifier::text FROM pg_control_system()), current_database()"
            )
            actual = cursor.fetchone()
            expected = (
                "127.0.0.1",
                side["port"],
                side["data_directory"],
                side["system_identifier"],
                target,
            )
            if actual != expected:
                raise RuntimeError(
                    "Live PostgreSQL identity differs from the owned preview manifest."
                )
            cursor.execute(
                "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname"
            )
            if {row[0] for row in cursor.fetchall()} - {"postgres", side["database"]}:
                raise RuntimeError("Private cluster contains an unrecognized database; stopping.")
            return dict(
                zip(
                    ("host", "port", "data_directory", "system_identifier", "database"),
                    actual,
                    strict=True,
                )
            )


def child_env(root, state, name, phase):
    side = state[name]
    # Do not inherit DATABASE_URL, provider credentials, proxies or ordinary settings.
    env = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR")
        if key in os.environ
    }
    env.update(
        {
            "ENV": "local",
            "DEBUG": "true",
            "SECRET_KEY": side["secret"],
            "LOGISTICS_LOCAL_BILLING_BYPASS": "true",
            "DJANGO_SETTINGS_MODULE": "ui_preview.settings",
            "DJANGO_BASE_DIR": str(Path(side["source"]) / "src"),
            "BASE_DIR": side["source"],
            "DATA_DIR": str(Path(side["directory"]) / "media"),
            "DB_HOST": "127.0.0.1",
            "DB_PORT": str(side["port"]),
            "DB_NAME": side["database"],
            "DB_USER": state["db_user"],
            "DB_PASSWORD": "",
            "PGHOST": "127.0.0.1",
            "PGPORT": str(side["port"]),
            "PGDATABASE": side["database"],
            "PGUSER": state["db_user"],
            "PYTHONPATH": os.pathsep.join(
                [str(root / "tooling"), str(Path(side["source"]) / "src")]
            ),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONMALLOC": "debug",
            "PYTHONFAULTHANDLER": "1",
            "MOTIONMATE_PREVIEW_ROOT": str(root),
            "MOTIONMATE_PREVIEW_SIDE": name,
            "MOTIONMATE_PREVIEW_PHASE": phase,
            "MOTIONMATE_PUBLIC_BASE_URL": f"http://127.0.0.1:{side['http_port']}",
        }
    )
    return env


def execute(root, state, name, action):
    verify_source(state[name]["source"])
    verify_database(root, state, name)
    side = state[name]
    with (Path(side["directory"]) / f"{action}.log").open("a") as log:
        subprocess.run(
            [state["python"], "-m", "ui_preview.runtime", action],
            cwd=side["source"],
            env=child_env(root, state, name, "setup"),
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )


def spawn(root, state, name):
    side = state[name]
    verify_source(side["source"])
    verify_database(root, state, name)
    if process_alive(side.get("process")):
        return
    free_port(side["http_port"])
    with (Path(side["directory"]) / "server.log").open("a") as log:
        child = subprocess.Popen(
            [state["python"], "-m", "ui_preview.runtime", "serve"],
            cwd=side["source"],
            env=child_env(root, state, name, "serve"),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    side["process"] = process_record(child.pid)
    write_json(root / "session.json", state)


def process_record(pid):
    return {
        "pid": pid,
        "start": Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19],
    }


def process_alive(record):
    if not record:
        return False
    try:
        return (
            process_record(record["pid"]) == record
            and Path(f"/proc/{record['pid']}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
        )
    except (FileNotFoundError, ProcessLookupError):
        return False


def stop_process(record, expected, root=None):
    if not process_alive(record):
        return
    command = Path(f"/proc/{record['pid']}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    if expected not in command:
        raise RuntimeError("Refusing to stop a process that is not the preview service.")
    if root is not None:
        environment = dict(
            entry.split("=", 1)
            for entry in Path(f"/proc/{record['pid']}/environ").read_text().split("\0")
            if "=" in entry
        )
        if environment.get("MOTIONMATE_PREVIEW_ROOT") != str(root) and str(root) not in command:
            raise RuntimeError("Refusing to stop a process belonging to another preview session.")
    os.kill(record["pid"], signal.SIGTERM)
    for _ in range(100):
        if not process_alive(record):
            return
        time.sleep(0.05)
    raise RuntimeError("Preview process did not stop; no other process was signalled.")


def new_session(
    repo,
    before_snapshot=None,
    step7=None,
    ports=(8780, 8781, 8782, 55488, 55489),
    route="/crm/agent/dashboard/",
):
    if len(set(ports)) != len(ports):
        raise RuntimeError("All five preview ports must differ.")
    for port in ports:
        free_port(port)
    if not route.startswith("/") or route.startswith("//"):
        raise RuntimeError("Preview route must be a local absolute path.")
    root, marker = make_root("session")
    state = {
        "version": 1,
        "id": marker["id"],
        "root": str(root),
        "python": str(Path(sys.executable).absolute()),
        "db_user": pwd.getpwuid(os.getuid()).pw_name,
        "clock": datetime.now(UTC).replace(second=0, microsecond=0).isoformat(),
        "password": "preview-" + secrets.token_urlsafe(12),
        "route": route,
        "comparison": "step7" if step7 else "captured",
        "allocator": "debug",
        "launcher_port": ports[2],
    }
    (root / "sources").mkdir()
    snapshot(repo, root / "sources/after")
    if before_snapshot:
        captured, _ = owned_root(before_snapshot, "snapshot")
        verify_source(captured / "source")
        snapshot(captured / "source", root / "sources/before")
    else:
        snapshot(repo, root / "sources/before")
        if step7:
            restore_step7_before(root / "sources/before", step7)
    shutil.copytree(
        Path(__file__).parent,
        root / "tooling/ui_preview",
        ignore=shutil.ignore_patterns("__pycache__", "test_*.py"),
    )
    vendor = root / "vendor"
    vendor.mkdir()
    font = (
        Path(repo) / "ui-lab/services-dashboard/shared/assets/nunito-sans-latin-wght-normal.woff2"
    )
    shutil.copyfile(font, vendor / "nunito.woff2")
    for index, name in enumerate(SIDES):
        directory = root / name
        directory.mkdir()
        state[name] = {
            "directory": str(directory),
            "source": str(root / "sources" / name),
            "host": "127.0.0.1",
            "port": ports[3 + index],
            "http_port": ports[index],
            "data_directory": str(directory / "pgdata"),
            "database": f"mm_preview_{state['id']}_{name}",
            "secret": secrets.token_urlsafe(48),
            "system_identifier": "uninitialized",
        }
    write_json(root / "session.json", state)
    return root, state


def initialize(root, state, name):
    side = state[name]
    directory = Path(side["data_directory"])
    if directory.exists():
        raise RuntimeError("Refusing to initialize an existing PostgreSQL directory.")
    binary = pg_bin()
    with (Path(side["directory"]) / "initdb.log").open("w") as log:
        subprocess.run(
            [
                str(binary / "initdb"),
                "-D",
                str(directory),
                "--auth-local=trust",
                "--auth-host=trust",
                "--encoding=UTF8",
                "--username=" + state["db_user"],
                "--locale=C.UTF-8",
                "--no-instructions",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )
    output = subprocess.check_output(
        [str(binary / "pg_controldata"), str(directory)],
        text=True,
        env={**os.environ, "LC_ALL": "C"},
    )
    side["system_identifier"] = next(
        line.split(":", 1)[1].strip()
        for line in output.splitlines()
        if line.startswith("Database system identifier:")
    )
    write_json(root / "session.json", state)
    pg_start(root, state, name)
    verify_database(root, state, name, "postgres")
    connection = psycopg2.connect(
        host="127.0.0.1", port=side["port"], dbname="postgres", user=state["db_user"]
    )
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
            )
            if cursor.fetchone()[0]:
                raise RuntimeError("New cluster is not empty.")
            from psycopg2 import sql

            cursor.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                    sql.Identifier(side["database"])
                )
            )
    finally:
        connection.close()
    verify_database(root, state, name)
    execute(root, state, name, "migrate")
    execute(root, state, name, "seed")


def pg_start(root, state, name):
    side = state[name]
    control_identity(side)
    pid = Path(side["data_directory"]) / "postmaster.pid"
    if pid.exists():
        verify_database(root, state, name, "postgres")
        return
    free_port(side["port"])
    socket_dir = Path(side["directory"]) / "socket"
    socket_dir.mkdir(exist_ok=True)
    subprocess.run(
        [
            str(pg_bin() / "pg_ctl"),
            "-D",
            side["data_directory"],
            "-l",
            str(Path(side["directory"]) / "postgres.log"),
            "-o",
            f"-h 127.0.0.1 -p {side['port']} -k {socket_dir}",
            "-w",
            "start",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    verify_database(root, state, name, "postgres")


def stop_side(root, state, name):
    side = state[name]
    stop_process(side.get("process"), "ui_preview.runtime serve", root)
    side.pop("process", None)
    write_json(root / "session.json", state)
    if (Path(side["data_directory"]) / "postmaster.pid").exists():
        verify_database(root, state, name)
        subprocess.run(
            [str(pg_bin() / "pg_ctl"), "-D", side["data_directory"], "-m", "fast", "-w", "stop"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
