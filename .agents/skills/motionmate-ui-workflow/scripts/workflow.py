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
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[4]
ASSETS = Path(__file__).resolve().parents[1] / "assets"
LEGACY_PHASES = {
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
PHASES = {
    "quick": LEGACY_PHASES["quick"],
    "full": (
        "audit",
        "brief",
        "integration",
        "before",
        "implementation",
        "validation",
        "comparison",
        "report",
    ),
}
CATEGORIES = {"implementation", "tests", "documentation", "required_asset", "generated"}
CORE_REPORTS = ("state.json", "brief.md", "integration.md", "validation.md")


def phases_for(state):
    return (LEGACY_PHASES if state["schema_version"] == 1 else PHASES)[state["mode"]]


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


def task_prefix(state):
    return f"docs/design/motionmate-ui-lab/workflows/{state['task_id']}"


def protected_workspace(repo, state):
    """Hash pre-existing dirty files; Git status detects newly changed paths."""
    exclusions = [task_prefix(state), *(entry["path"] for entry in state["manifest"])]
    exclusions.extend(
        entry["path"]
        for entry in state.get("artifact_inventory", [])
        if entry["category"] == "generated" and not Path(entry["path"]).is_absolute()
    )
    spec = [".", *(f":(exclude,literal){name}" for name in exclusions)]
    status = subprocess.check_output(
        ["git", "-C", str(repo), "status", "--porcelain=v1", "--untracked-files=all", "--", *spec],
        text=True,
    )
    changed = (
        subprocess.check_output(
            ["git", "-C", str(repo), "diff", "--name-only", "-z", "HEAD", "--", *spec]
        )
        .decode()
        .split("\0")
    )
    untracked = (
        subprocess.check_output(
            [
                "git",
                "-C",
                str(repo),
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                *spec,
            ]
        )
        .decode()
        .split("\0")
    )
    files = {}
    for name in sorted(set(changed + untracked) - {""}):
        path = local_file(repo, name)
        files[name] = sha(path) if path.is_file() else None
    index = subprocess.check_output(
        [
            "git",
            "-C",
            str(repo),
            "diff",
            "--cached",
            "--binary",
            "HEAD",
            "--",
            ".",
            f":(exclude,literal){task_prefix(state)}",
        ]
    )
    return {"status": status, "files": files, "index_sha256": hashlib.sha256(index).hexdigest()}


def disposable_category(entry):
    name = entry["path"]
    if entry["category"] == "generated" and not Path(name).is_absolute():
        require(
            not (name.startswith("src/") and not name.startswith("src/staticfiles/"))
            and not name.endswith(".py"),
            f"Runtime source/assets cannot be excluded as generated: {name}",
        )


def artifact_path(repo, entry):
    name = entry.get("path")
    require(isinstance(name, str) and name, "Artifact needs a path")
    if not Path(name).is_absolute():
        return local_file(repo, name)
    path = Path(name)
    require(
        entry.get("category") == "generated" and not path.resolve().is_relative_to(repo.resolve()),
        "Only excluded generated artifacts may use external absolute paths",
    )
    require(not any(p.is_symlink() for p in (path, *path.parents)), "Symlink artifact refused")
    return path


def inspect_v2(state, repo, candidate_sha, pre_implementation, resume):
    done = state["completed_phases"]
    prototype = state.get("optional_prototype")
    require(
        isinstance(prototype, dict) and isinstance(prototype.get("enabled"), bool),
        "Expected optional_prototype setting",
    )
    if prototype["enabled"]:
        require(
            prototype.get("reason"),
            "Optional prototype needs a request or major design uncertainty",
        )
        evidence_record(prototype.get("authorization"))
    else:
        require(
            not any(
                record.get("kind") == "synthetic_prototype"
                for records in state["evidence"].values()
                for record in records
            ),
            "Synthetic prototype requires explicit authorization",
        )

    inventory = state.get("artifact_inventory")
    require(isinstance(inventory, list), "Expected artifact_inventory")
    seen = set()
    for entry in inventory:
        require(
            isinstance(entry, dict) and entry.get("category") in CATEGORIES,
            "Invalid artifact category",
        )
        require(
            entry.get("purpose") and entry.get("ownership") in {"task", "unrelated"},
            "Artifact needs purpose and ownership",
        )
        disposable_category(entry)
        path = artifact_path(repo, entry)
        require(path not in seen, "Duplicate inventory path")
        seen.add(path)

    if state.get("baseline"):
        require(
            isinstance(state.get("protected_workspace"), dict),
            "Missing protected workspace baseline",
        )
        identity = git_identity(repo, state["task_id"])
        require(
            all(identity[k] == state["baseline"][k] for k in ("branch", "head")),
            "Git branch/HEAD drift; reconcile concurrent work",
        )
        require(
            protected_workspace(repo, state) == state["protected_workspace"],
            "Concurrent edits outside approved scope; preserve and reconcile",
        )
        if "before" not in done or pre_implementation:
            for entry in state["manifest"]:
                path = local_file(repo, entry["path"])
                require(
                    (sha(path) if path.is_file() else None) == entry.get("before_sha256"),
                    f"Overlapping file changed before implementation: {entry['path']}",
                )
    if resume and state.get("approvals", {}).get("implementation"):
        expected = state.get("implementation_checkpoint")
        if expected is None:
            expected = {entry["path"]: entry["before_sha256"] for entry in state["manifest"]}
        current = target_hashes(repo, state)
        require(
            current == expected,
            "Interrupted implementation drift; reconcile against the last checkpoint",
        )

    if "before" not in done:
        return
    preview = state.get("preview")
    if state["mode"] == "quick" and preview is None:
        if "validation" in done:
            require(
                any(
                    result["status"] == "blocked" and result.get("limitation")
                    for result in state["validation"]
                ),
                "Quick Change without a runtime needs a disclosed blocked validation result",
            )
        return
    require(
        isinstance(preview, dict) and preview.get("kind") == "django",
        "Actual Django preview required; synthetic prototypes cannot substitute",
    )
    require(
        preview.get("vertical") == state["vertical"] and preview.get("synthetic_records") is True,
        "Django preview must use this vertical and synthetic records",
    )
    require(
        set(preview.get("contracts", []))
        == {"templates", "routes", "authentication", "forms", "permissions"},
        "Django preview must exercise actual templates/routes/authentication/forms/permissions",
    )
    if state.get("before_identity_sha256") is not None:
        require(
            state["before_identity_sha256"] == digest(preview.get("before")),
            "Frozen Django BEFORE identity changed",
        )
    sides = ["before", "after"] if "comparison" in done else ["before"]
    environments = state.get("environments", [])
    require(
        isinstance(environments, list) and all(isinstance(e, dict) for e in environments),
        "Expected disposable environments",
    )
    ids = [env.get("id") for env in environments]
    require(len(ids) == len(set(ids)), "Duplicate environment identity")
    for side in sides:
        record = preview.get(side)
        require(isinstance(record, dict), f"Missing actual Django {side} preview")
        url = urlparse(record.get("url", ""))
        require(
            url.scheme == "http"
            and url.hostname in {"127.0.0.1", "localhost", "::1"}
            and not url.username
            and not url.password,
            "Preview needs a credential-free loopback Django URL",
        )
        for key in ("source_sha256", "initial_fixture_sha256"):
            require(
                isinstance(record.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", record[key]),
                f"Missing preview identity: {side}/{key}",
            )
        env = next((e for e in environments if e.get("id") == record.get("environment_id")), None)
        require(
            env
            and env.get("engine") == "postgresql"
            and env.get("disposable") is True
            and env.get("ownership_verified") is True,
            "Only verified disposable PostgreSQL is permitted",
        )
        for key in (
            "settings",
            "database",
            "cluster_directory",
            "system_identifier",
            "port",
            "process",
            "identity_evidence",
        ):
            require(env.get(key), f"Missing verified PostgreSQL identity: {key}")
        require(str(env["port"]) != "5432", "Ordinary PostgreSQL port refused")
        authorization = next(
            (
                r
                for r in state.get("resource_authorizations", [])
                if r.get("environment_id") == env["id"]
            ),
            None,
        )
        evidence_record(authorization)
    if "comparison" in done:
        before, after = preview["before"], preview["after"]
        require(
            before["url"] != after["url"] and before["environment_id"] != after["environment_id"],
            "Django BEFORE/AFTER need independent apps and databases",
        )
        before_env, after_env = (
            next(e for e in environments if e["id"] == side["environment_id"])
            for side in (before, after)
        )
        for key in ("cluster_directory", "system_identifier", "port"):
            require(
                before_env[key] != after_env[key],
                "Django BEFORE/AFTER need independent PostgreSQL clusters",
            )
        require(
            before["initial_fixture_sha256"] == after["initial_fixture_sha256"],
            "Django BEFORE/AFTER require equivalent initial synthetic fixtures",
        )
        require(
            after.get("candidate_sha256") == candidate_sha,
            "Django AFTER does not identify the current candidate",
        )
        if any(entry["shared"] for entry in state["manifest"]) or state["vertical"] == "SHARED":
            covered = {
                result.get("vertical")
                for result in state["validation"]
                if result["status"] == "pass"
            }
            require(
                {"SERVICE", "LOGISTICS"} <= covered,
                "Shared change needs regression evidence in both verticals",
            )


def target_hashes(repo, state):
    return {
        entry["path"]: sha(path) if (path := local_file(repo, entry["path"])).is_file() else None
        for entry in state["manifest"]
    }


def inspect_state(state, repo=REPO, pre_implementation=False, resume=False):
    require(isinstance(state, dict), "Expected state object")
    require(state.get("schema_version") in {1, 2}, "Unsupported state schema")
    v2 = state["schema_version"] == 2
    require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", state.get("task_id", "")), "Invalid task ID")
    require(state.get("vertical") in {"SERVICE", "LOGISTICS", "SHARED"}, "Invalid vertical")
    mode = state.get("mode")
    require(mode in PHASES, "Invalid workflow mode")
    for key in ("route", "objective"):
        require(isinstance(state.get(key), str) and state[key].strip(), f"Missing {key}")
    phases = phases_for(state)
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
        if ("brief" if v2 else "prototype_validation") in done:
            require(
                artifacts,
                "Design brief requires versioned artifact hashes"
                if v2
                else "Validated design requires versioned artifact hashes",
            )
    else:
        require(state.get("design_version") is None, "Quick Change does not adopt a redesign")
    design_identity = {"version": state.get("design_version"), "artifacts": artifacts}
    if v2:
        design_identity.update(
            {key: state[key] for key in ("task_id", "vertical", "route", "objective")}
        )
    design_sha = digest(design_identity)

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
        if v2:
            require(entry.get("category") in CATEGORIES, f"Missing artifact category: {name}")
            disposable_category(entry)
            require(
                entry.get("vertical") == ("SHARED" if entry["shared"] else state["vertical"]),
                f"Manifest vertical outside task scope: {name}",
            )
            if entry["shared"]:
                require(
                    set(entry.get("regression_verticals", [])) == {"SERVICE", "LOGISTICS"},
                    f"Shared file needs both regression verticals: {name}",
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
        if v2:
            require("brief" in done, "Gate A requires the completed design brief")
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
        if v2:
            require(
                ("plan" if mode == "quick" else "integration") in done,
                "Gate B requires the exact completed integration plan",
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
    if v2:
        inspect_v2(state, repo, candidate_sha, pre_implementation, resume)
    review_sha = (
        digest(
            {
                "candidate_sha256": candidate_sha,
                "preview": state.get("preview"),
                "environments": state.get("environments"),
                "validation": state.get("validation"),
            }
        )
        if v2 and "comparison" in done
        else None
    )
    if acceptance:
        require(
            mode == "full" and "report" in done,
            "Acceptance requires the full implementation report",
        )
        require(acceptance.get("candidate_sha256") == candidate_sha, "Stale candidate acceptance")
        if v2:
            require(acceptance.get("review_sha256") == review_sha, "Stale Django review acceptance")

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
    if v2 and acceptance:
        action = "Automatically prepare the exact commit manifest; one commit per redesign is recommended. Explicit commit authorization is still required; no release or cleanup is authorized."
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
        **({"review_sha256": review_sha} if v2 else {}),
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


def generated_path(name):
    path = Path(name)
    if path.suffix == ".py":
        return False  # Fixture/check source remains reproducible source, even under evidence/.
    return (
        any(
            part
            in {
                "dist",
                "node_modules",
                "__pycache__",
                ".cache",
                "screenshots",
                "evidence",
                "logs",
                "tmp",
            }
            for part in path.parts
        )
        or path.suffix.lower()
        in {".log", ".tmp", ".pyc", ".sqlite3", ".db", ".png", ".jpg", ".pdf"}
        or path.name.startswith(("runtime-", "diagnostic-", "capture-"))
    )


def prepare_commit(state, state_path, repo=REPO):
    """Prepare a deterministic exact selection. Never stage or execute Git writes."""
    result = inspect_state(state, repo, resume=True)
    require(
        state["schema_version"] == 2 and state["mode"] == "full",
        "Commit preparation is for v2 Full Redesign; preserve legacy records",
    )
    require(
        result["current_phase"] == "done" and state["approvals"]["acceptance"],
        "Commit preparation requires Gate C acceptance",
    )
    task = state_path.parent.resolve()
    require(
        task.is_relative_to(repo.resolve())
        and task.relative_to(repo.resolve()).as_posix() == task_prefix(state),
        "Commit preparation requires the conventional task directory inside the repository",
    )
    output = local_file(repo, f"{task_prefix(state)}/commit-manifest.json")
    core_paths = {f"{task_prefix(state)}/{name}" for name in CORE_REPORTS}
    require(
        all(local_file(repo, name).is_file() for name in core_paths),
        "Commit preparation requires the essential audit/design/integration/validation records",
    )
    entries = {entry["path"]: {**entry, "ownership": "task"} for entry in state["manifest"]}
    accepted_paths = set(entries)
    for name in state["design_artifacts"]:
        entries.setdefault(
            name,
            {
                "path": name,
                "category": "documentation",
                "purpose": "Approved design direction",
                "ownership": "task",
            },
        )
    for path in sorted(task.rglob("*")):
        if not path.is_file() or path == output:
            continue
        name = path.relative_to(repo).as_posix()
        require(
            name in entries
            or generated_path(name)
            or path.suffix in {".md", ".json", ".txt"}
            or any(entry["path"] == name for entry in state["artifact_inventory"]),
            f"Unclassified task file; record its category and ownership: {name}",
        )
        entries.setdefault(
            name,
            {
                "path": name,
                "category": "generated" if generated_path(name) else "documentation",
                "purpose": "Task evidence"
                if generated_path(name)
                else "Audit, approval, design or test record",
                "ownership": "task",
            },
        )
    for entry in state["artifact_inventory"]:
        name = entry["path"]
        if name in core_paths:
            require(
                entry["category"] == "documentation" and entry["ownership"] == "task",
                f"Essential workflow records cannot be excluded: {name}",
            )
        if name in accepted_paths:
            require(
                entry["category"] == entries[name]["category"] and entry["ownership"] == "task",
                f"Inventory cannot reclassify accepted scope: {name}",
            )
        entries[name] = entry
    files, excluded = [], []
    for name, entry in sorted(entries.items()):
        path = artifact_path(repo, entry)
        include = entry["ownership"] == "task" and entry["category"] != "generated"
        if include:
            require(
                name in accepted_paths
                or name in state["design_artifacts"]
                or path.is_relative_to(task),
                f"Task source outside approved manifest: {name}",
            )
            require(path.is_file(), f"Required commit file missing: {name}")
        require(
            not (
                entry["category"] == "generated"
                and name.startswith("src/")
                and not name.startswith("src/staticfiles/")
            ),
            f"Runtime source/assets cannot be excluded as generated: {name}",
        )
        record = {
            "path": name,
            "category": entry["category"],
            "purpose": entry["purpose"],
            "sha256": sha(path) if include else None,
        }
        (files if include else excluded).append(record)
    # A manifest cannot hash itself. Its exact path is selected explicitly.
    files.append(
        {
            "path": output.relative_to(repo).as_posix(),
            "category": "documentation",
            "purpose": "Exact commit selection (self descriptor)",
            "sha256": None,
        }
    )
    document = {
        "schema_version": 2,
        "task_id": state["task_id"],
        "vertical": state["vertical"],
        "candidate_sha256": result["candidate_sha256"],
        "manifest_sha256": result["manifest_sha256"],
        "review_sha256": result["review_sha256"],
        "recommendation": "One commit for this completed redesign; explicit user commit authorization required.",
        "files": files,
        "excluded": excluded,
        "notice": "Preparation only. Nothing staged, committed, pushed, merged, deployed or deleted.",
    }
    if output.exists():
        require(
            json.loads(output.read_text()) == document,
            "Existing commit manifest differs; preserve it and reconcile candidate/concurrent changes",
        )
    else:
        write_json(output, document)
    return {
        "commit_manifest": str(output),
        "included": len(files),
        "excluded": len(excluded),
        "candidate_sha256": result["candidate_sha256"],
        "notice": document["notice"],
    }


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
    for name in CORE_REPORTS[1:]:
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
    for command in ("check", "checkpoint", "baseline", "prepare-commit"):
        item = sub.add_parser(command)
        item.add_argument("state", type=Path)
        if command == "check":
            item.add_argument("--pre-implementation", action="store_true")
            item.add_argument("--resume", action="store_true")
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
                if state["schema_version"] == 2:
                    state["protected_workspace"] = protected_workspace(REPO, state)
            result = inspect_state(
                state,
                pre_implementation=getattr(args, "pre_implementation", False),
                resume=getattr(args, "resume", False),
            )
            if args.command == "prepare-commit":
                result = prepare_commit(state, args.state)
            if args.command in {"checkpoint", "baseline"}:
                if state["schema_version"] == 2 and "before" in state["completed_phases"]:
                    state["implementation_checkpoint"] = target_hashes(REPO, state)
                    if state.get("preview"):
                        state["before_identity_sha256"] = digest(state["preview"]["before"])
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
