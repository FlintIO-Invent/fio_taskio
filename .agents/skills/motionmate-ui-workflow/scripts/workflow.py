"""Offline workflow records and approval consistency checks; stdlib only."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
ASSETS = Path(__file__).resolve().parents[1] / "assets"
PHASES = {
    "quick": ("audit", "plan", "before", "implementation", "validation", "report"),
    "full": (
        "audit",
        "brief",
        "prototype",
        "prototype_validation",
        "integration",
        "before",
        "implementation",
        "validation",
        "comparison",
        "report",
    ),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_file(repo, name):
    require(isinstance(name, str) and name, "Empty/non-string file path")
    path = Path(name)
    require(
        not path.is_absolute()
        and ".." not in path.parts
        and path.as_posix() == name
        and not any(c in name for c in "*?[]\\"),
        f"Expected an exact repository-relative path: {name}",
    )
    target = repo / path
    require(target.resolve().is_relative_to(repo.resolve()), f"Path escapes repository: {name}")
    require(
        not any(parent.is_symlink() for parent in (target, *target.parents) if parent != repo),
        f"Symlink path refused: {name}",
    )
    return target


def git_identity(repo, task_id):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()

    return {
        "branch": git("branch", "--show-current"),
        "head": git("rev-parse", "HEAD"),
        "status": git(
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            ".",
            f":(exclude)docs/design/motionmate-ui-lab/workflows/{task_id}",
        ),
    }


def evidence_record(record):
    require(isinstance(record, dict), "Expected an evidence/approval object")
    for key in ("source", "quote", "scope"):
        require(isinstance(record.get(key), str) and record[key].strip(), f"Approval lacks {key}")


def inspect_state(state, repo=REPO, pre_implementation=False):
    require(isinstance(state, dict), "Expected state object")
    require(state.get("schema_version") == 1, "Unsupported state schema")
    require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", state.get("task_id", "")), "Invalid task ID")
    require(state.get("vertical") in {"SERVICE", "LOGISTICS", "SHARED"}, "Invalid vertical")
    mode = state.get("mode")
    require(mode in PHASES, "Invalid workflow mode")
    for key in ("route", "objective"):
        require(isinstance(state.get(key), str) and state[key].strip(), f"Missing {key}")
    phases = PHASES[mode]
    done = state.get("completed_phases")
    require(
        isinstance(done, list) and done == list(phases[: len(done)]), "Phases skipped or reordered"
    )
    for phase in done:
        records = state.get("evidence", {}).get(phase)
        require(isinstance(records, list) and records, f"Missing evidence for {phase}")
        for record in records:
            require(
                isinstance(record, dict)
                and all(record.get(k) for k in ("kind", "reference", "summary")),
                f"Incomplete evidence for {phase}",
            )

    artifacts = state.get("design_artifacts", {})
    require(isinstance(artifacts, dict), "Expected design_artifacts map")
    for name, expected in artifacts.items():
        path = local_file(repo, name)
        require(
            path.is_file() and sha(path) == expected, f"Design artifact missing/changed: {name}"
        )
    if mode == "full":
        require(state.get("design_version"), "Full redesign needs a design version")
        if "prototype_validation" in done:
            require(artifacts, "Validated design requires versioned artifact hashes")
    else:
        require(state.get("design_version") is None, "Quick Change does not adopt a redesign")
    design_sha = digest({"version": state.get("design_version"), "artifacts": artifacts})

    manifest = state.get("manifest")
    require(isinstance(manifest, list), "Expected manifest list")
    paths = []
    for entry in manifest:
        require(isinstance(entry, dict), "Expected manifest entry object")
        name = entry.get("path")
        local_file(repo, name)
        require(name not in paths, f"Duplicate manifest path: {name}")
        paths.append(name)
        require(entry.get("action") in {"add", "modify"}, f"Invalid action: {name}")
        require(entry.get("purpose"), f"Missing purpose: {name}")
        require(isinstance(entry.get("shared"), bool), f"Missing shared assessment: {name}")
        if entry["shared"]:
            require(
                entry.get("shared_impact") and entry.get("shared_regression"),
                f"Missing shared impact/checks: {name}",
            )
    manifest_sha = digest(
        {
            "vertical": state["vertical"],
            "mode": mode,
            "route": state["route"],
            "objective": state["objective"],
            "design_sha256": design_sha if mode == "full" else None,
            "files": manifest,
        }
    )
    approvals = state.get("approvals", {})
    require(
        isinstance(approvals, dict)
        and set(approvals) == {"design", "implementation", "acceptance"},
        "Expected all three approval fields",
    )
    for record in approvals.values():
        if record is not None:
            evidence_record(record)
    design, implementation, acceptance = (
        approvals[k] for k in ("design", "implementation", "acceptance")
    )
    if design:
        require(mode == "full" and artifacts, "Design consent needs full mode and artifacts")
        require(
            design.get("design_version") == state["design_version"]
            and design.get("design_sha256") == design_sha,
            "Stale design approval",
        )
    if implementation:
        require(
            manifest and state.get("baseline"),
            "Implementation consent needs a manifest and baseline",
        )
        require(mode == "quick" or design, "Implementation consent cannot bypass Gate A")
        require(
            implementation.get("design_version") == state["design_version"]
            and implementation.get("manifest_sha256") == manifest_sha,
            "Stale implementation approval",
        )
    if state.get("baseline") is not None:
        baseline = state["baseline"]
        require(
            isinstance(baseline, dict)
            and set(baseline) == {"branch", "head", "status"}
            and all(isinstance(value, str) for value in baseline.values()),
            "Invalid Git baseline",
        )
        for entry in manifest:
            value = entry.get("before_sha256")
            require(
                (entry["action"] == "add" and value is None)
                or (
                    entry["action"] == "modify"
                    and isinstance(value, str)
                    and re.fullmatch(r"[0-9a-f]{64}", value)
                ),
                f"Invalid target baseline hash: {entry['path']}",
            )
    if mode == "full" and "integration" in done:
        require(design, "Integration cannot bypass Gate A")
    if "before" in done:
        require(implementation, "Implementation phases cannot bypass Gate B")
    if "validation" in done:
        results = state.get("validation")
        require(isinstance(results, list) and results, "Missing validation results")
        for result in results:
            require(
                isinstance(result, dict)
                and result.get("check")
                and result.get("evidence")
                and result.get("status") in {"pass", "fail", "blocked", "not_applicable"},
                "Validation needs actual results, including disclosed limitations",
            )
            if result["status"] != "pass":
                require(result.get("limitation"), "Non-pass validation needs an explanation")

    candidate_sha = None
    if "implementation" in done:
        candidate = {}
        for name in paths:
            path = local_file(repo, name)
            require(path.is_file(), f"Candidate file missing: {name}")
            candidate[name] = sha(path)
        candidate_sha = digest(candidate)
    if acceptance:
        require(
            mode == "full" and "report" in done,
            "Acceptance requires the full implementation report",
        )
        require(acceptance.get("candidate_sha256") == candidate_sha, "Stale candidate acceptance")

    next_phase = phases[len(done)] if len(done) < len(phases) else "done"
    gate = None
    if mode == "full" and next_phase == "integration" and not design:
        gate = "A"
    elif next_phase == "before" and not implementation:
        gate = "B"
    elif mode == "full" and next_phase == "done" and not acceptance:
        gate = "C"
    phase = f"gate_{gate.lower()}" if gate else next_phase
    action = (
        f"Stop for explicit Gate {gate} approval; preserve completed work."
        if gate
        else (
            "Workflow complete; no release or cleanup is authorized."
            if next_phase == "done"
            else f"Complete {next_phase} within current authorization."
        )
    )
    if pre_implementation:
        require(
            implementation and "implementation" not in done,
            "Pre-implementation requires B and no completed implementation",
        )
        require(
            state.get("baseline") == git_identity(repo, state["task_id"]),
            "Git branch/HEAD/status drift; reconcile concurrent work",
        )
        for entry in manifest:
            path = local_file(repo, entry["path"])
            current = sha(path) if path.is_file() else None
            require(
                current == entry.get("before_sha256"), f"Overlapping file changed: {entry['path']}"
            )
    return {
        "task_id": state["task_id"],
        "current_phase": phase,
        "gate": gate,
        "next_permitted_action": action,
        "design_sha256": design_sha,
        "manifest_sha256": manifest_sha,
        "candidate_sha256": candidate_sha,
        "notice": "Offline consistency only; verify real user authorization and resource ownership.",
    }


def write_json(path, value):
    # Atomic replacement keeps the previous checkpoint intact if a session stops.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def initialize(args):
    require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", args.task), "Invalid task ID")
    destination = args.output or REPO / "docs/design/motionmate-ui-lab/workflows" / args.task
    require(not destination.exists(), "Task directory already exists; resume instead")
    state = json.loads((ASSETS / "state.json").read_text())
    state.update(
        task_id=args.task,
        vertical=args.vertical,
        mode=args.mode,
        route=args.route,
        objective=args.objective,
    )
    state["design_version"] = "v1" if args.mode == "full" else None
    result = inspect_state(state)
    state.update(
        current_phase=result["current_phase"], next_permitted_action=result["next_permitted_action"]
    )
    destination.mkdir(parents=True, exist_ok=False)
    write_json(destination / "state.json", state)
    for name in ("brief.md", "prototype-review.md", "integration.md", "validation.md"):
        (destination / name).write_text((ASSETS / name).read_text())
    return {"state": str(destination / "state.json"), **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Create task records only; no runtime setup")
    init.add_argument("--task", required=True)
    init.add_argument("--vertical", choices=("SERVICE", "LOGISTICS", "SHARED"), required=True)
    init.add_argument("--mode", choices=tuple(PHASES), required=True)
    init.add_argument("--route", required=True)
    init.add_argument("--objective", required=True)
    init.add_argument("--output", type=Path)
    for command in ("check", "checkpoint", "baseline"):
        item = sub.add_parser(command)
        item.add_argument("state", type=Path)
        if command == "check":
            item.add_argument("--pre-implementation", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = initialize(args)
        else:
            require(not args.state.is_symlink(), "Symlink state refused")
            state = json.loads(args.state.read_text())
            inspect_state(state)
            if args.command == "baseline":
                require(
                    state["approvals"]["implementation"] is None
                    and "implementation" not in state["completed_phases"],
                    "Cannot rebaseline approved/in-progress implementation",
                )
                require(state["manifest"], "Baseline needs the exact manifest")
                require(
                    state.get("baseline") is None,
                    "Existing baseline retained; reconcile drift explicitly",
                )
                for entry in state["manifest"]:
                    path = local_file(REPO, entry["path"])
                    require(
                        path.is_file() if entry["action"] == "modify" else not path.exists(),
                        f"Action disagrees with existing file: {entry['path']}",
                    )
                    entry["before_sha256"] = sha(path) if path.is_file() else None
                state["baseline"] = git_identity(REPO, state["task_id"])
            result = inspect_state(
                state, pre_implementation=getattr(args, "pre_implementation", False)
            )
            if args.command in {"checkpoint", "baseline"}:
                state.update(
                    current_phase=result["current_phase"],
                    next_permitted_action=result["next_permitted_action"],
                    updated_at=datetime.now(UTC).isoformat(),
                )
                write_json(args.state, state)
        print(json.dumps(result, indent=2))
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Workflow check failed: {error}\n")


if __name__ == "__main__":
    main()
