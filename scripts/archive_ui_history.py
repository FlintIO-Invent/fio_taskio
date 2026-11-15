"""Archive allowlisted synthetic UI history outside the repository, without cleanup."""

import argparse
import hashlib
import io
import json
import re
import tarfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OMIT = {"node_modules", "__pycache__", ".git", "pgdata", "socket"}
LOCAL_ONLY_NAMES = {"session.json", "owner.json", "postmaster.pid", "DISPOSABLE"}
LOCAL_ONLY_SUFFIXES = {
    ".log",
    ".zip",
    ".pyc",
    ".sqlite3",
    ".sqlite",
    ".db",
    ".dump",
    ".backup",
    ".sql",
    ".jsonl",
}
SECRET = re.compile(
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    rb"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}|"
    rb"\b(?:ghp_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{25,})|"
    rb"(?:postgres(?:ql)?|mysql|redis)://[^\s/]+:[^\s@]+@"
)
SENSITIVE_FIELD = re.compile(
    r"^(?:password|secret|secret_key|access_token|refresh_token|"
    r"csrfmiddlewaretoken|sessionid|csrftoken|cookie_value)$",
    re.I,
)


def files(root):
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in OMIT for part in relative.parts):
            continue
        if path.is_symlink():
            raise RuntimeError(f"Archive refuses symlinks: {path}")
        if path.name.startswith(".env") or path.name in LOCAL_ONLY_NAMES:
            continue
        if path.is_file() and path.suffix not in LOCAL_ONLY_SUFFIXES:
            yield path


def check_json(value, source):
    if isinstance(value, dict):
        for key, item in value.items():
            if SENSITIVE_FIELD.fullmatch(key) and item:
                raise RuntimeError(f"Credential field in archive candidate: {source}")
            check_json(item, source)
    elif isinstance(value, list):
        for item in value:
            check_json(item, source)


def candidates(step7, step8):
    for root in (REPO / "ui-lab", REPO / "docs/design"):
        for path in files(root):
            yield path, "repository/" + path.relative_to(REPO).as_posix()
    for side in ("before", "after"):
        for path in files(step7 / "evidence" / side):
            yield path, "runtime/step7/" + path.relative_to(step7).as_posix()
    for name in (
        "evidence/index.html",
        "evidence/gallery-review.png",
        "before-sha256.json",
        "handoff-sha256.json",
        "source-preservation.json",
        "existing-regression-comparison.json",
        "existing-labels.json",
        "final-labels.json",
    ):
        yield step7 / name, "runtime/step7/" + name
    for path in files(step8 / "evidence"):
        if path.name == "launcher.png" or "failure" in path.name:
            continue
        if path.suffix in {".png", ".json"}:
            yield path, "runtime/step8/" + path.relative_to(step8).as_posix()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step7", required=True, type=Path)
    parser.add_argument("--step8", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.absolute()
    if output.resolve().is_relative_to(REPO) or output.exists():
        parser.error("Choose a new archive outside the repository; existing files are preserved.")
    entries = list(candidates(args.step7.resolve(), args.step8.resolve()))
    # Inspect every text candidate before creating the final archive.
    for source, _ in entries:
        if source.is_symlink() or not source.is_file():
            raise RuntimeError(f"Missing or unsafe archive source: {source}")
        if source.suffix != ".png" and source.suffix != ".woff2":
            content = source.read_bytes()
            if SECRET.search(content):
                raise RuntimeError(f"Credential pattern in archive candidate: {source}")
            if source.suffix == ".json":
                check_json(json.loads(content), source)
    output.parent.mkdir(parents=True, exist_ok=True)
    provenance = {
        "created_utc": datetime.now(UTC).isoformat(),
        "historical_baseline_commit": "34eacc9ce9b412b0ffeb5ffa492a69f5de49ca4c",
        "exclusions": [
            "Dependencies, caches, logs, duplicate screenshot ZIP, databases and session files",
            "Step 7 after-development captures",
            "Step 8 launcher.png (displays generated password) and failure screenshots",
        ],
        "screenshots": "Synthetic application/prototype captures only; no credential screenshot included.",
        "files": [],
    }
    readme = """Motionmate historical UI evidence

Extract into a NEW local directory, never over an existing checkout.
repository/ preserves the complete UI Lab galleries, sources and their relative links.
runtime/step7/evidence/index.html is the actual Django Step 7 comparison gallery.
runtime/step8/evidence contains selected final real-application captures and JSON reports.
MANIFEST.json records original source paths, byte sizes and SHA-256 for every file.
Historical local URLs and paths are provenance, not current setup requirements.
No session files, databases, credentials, logs or duplicate screenshot ZIP are included.
The credential-bearing launcher screenshot and unreviewed failure captures are excluded.
Serve repository/ui-lab or runtime/step7/evidence on loopback for gallery review.
The archive does not restore running application sessions or authorize any database work.
"""
    with output.open("xb") as raw:
        with tarfile.open(fileobj=raw, mode="w:gz") as archive:
            for source, name in entries:
                content = source.read_bytes()
                provenance["files"].append(
                    {
                        "path": name,
                        "source": str(source),
                        "bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(content), 0o600
                archive.addfile(info, io.BytesIO(content))
            for name, content in (
                ("MANIFEST.json", json.dumps(provenance, indent=2).encode() + b"\n"),
                ("README.txt", readme.encode()),
            ):
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(content), 0o600
                archive.addfile(info, io.BytesIO(content))
    output.chmod(0o600)
    print(
        json.dumps({"archive": str(output), "files": len(entries), "bytes": output.stat().st_size})
    )


if __name__ == "__main__":
    main()
