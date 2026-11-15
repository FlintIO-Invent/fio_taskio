"""Read-only UI source/manifest checks; no Django initialization, browser or database."""

import ast
import hashlib
import json
import re
import subprocess
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs/design/motionmate-ui-lab"
OPTIONAL_REFERENCE_ROOTS = (
    Path("design_references/phoenix"),
    Path("ui-lab/services-dashboard/tabler/dist"),
    Path("ui-lab/services-appointments/dist"),
)
HISTORICAL_EVIDENCE_ROOTS = (
    Path("docs/design/motionmate-ui-lab/screenshots"),
    Path("ui-lab/services-dashboard/evidence"),
    Path("ui-lab/services-dashboard/daisyui/evidence/step4"),
    Path("ui-lab/services-appointments/evidence"),
)


def safe_relative(name):
    path = Path(name)
    return not path.is_absolute() and ".." not in path.parts


def manifest_failures(repo, names):
    failures = []
    if len(names) != len(set(names)):
        failures.append("Duplicate staging-manifest paths")
    for name in names:
        if not safe_relative(name) or not (repo / name).is_file():
            failures.append(f"Unsafe/missing proposed staging file: {name}")
    return failures


def documentation_link_failures(repo, names):
    """Only explicit local-reference/evidence roots are optional; manifest files win."""
    repo = repo.resolve()
    required = {(repo / name).resolve() for name in names if safe_relative(name)}
    failures, historical, optional = [], [], []
    for name in names:
        if not safe_relative(name) or not name.endswith(".md"):
            continue
        path = repo / name
        if not path.is_file():
            # manifest_failures reports missing committed documents without reading them.
            continue
        for match in re.finditer(r"\[[^\]]*\]\(([^)\s]+)\)", path.read_text()):
            link = match[1].strip("<>").split("#")[0].split("?")[0]
            if not link or "://" in link or link.startswith(("/", "mailto:")):
                continue
            target = (path.parent / link).resolve()
            if target not in required and target.is_relative_to(repo):
                relative = target.relative_to(repo)
                if any(relative.is_relative_to(root) for root in OPTIONAL_REFERENCE_ROOTS):
                    optional.append(relative.as_posix())
                    continue
                if any(relative.is_relative_to(root) for root in HISTORICAL_EVIDENCE_ROOTS) or (
                    relative == Path("docs/design/motionmate-ui-lab/baseline-metrics.json")
                ):
                    historical.append(relative.as_posix())
                    continue
            if not target.exists():
                failures.append(f"Broken local documentation/skill link: {name} -> {link}")
    return failures, historical, optional


def main():
    failures = []

    def check(condition, message):
        if not condition:
            failures.append(message)

    project = tomllib.loads((REPO / "pyproject.toml").read_text())
    lock = tomllib.loads((REPO / "uv.lock").read_text())
    check(
        project["project"]["optional-dependencies"].get("ui") == ["playwright==1.63.0"],
        "UI extra must pin Playwright 1.63.0",
    )
    packages = {p["name"]: p for p in lock["package"]}
    check(
        packages.get("playwright", {}).get("version") == "1.63.0",
        "Playwright lock missing/mismatched",
    )
    check(
        {"name": "playwright"}
        in packages["fio-taskio"].get("optional-dependencies", {}).get("ui", []),
        "Project lock must include the UI extra",
    )
    for package in ("playwright", "pyee", "greenlet"):
        check(package in packages, f"Locked UI dependency missing: {package}")

    preservation = json.loads((DOCS / "preservation-manifest.json").read_text())
    for name, expected in preservation["protected_step7_files"].items():
        path = REPO / name
        check(
            path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected,
            f"Approved Step 7 source changed: {name}",
        )
    for name, expected in preservation["protected_frozen_reference_files"].items():
        path = REPO / name
        check(
            path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected,
            f"Frozen Step 4 reference changed: {name}",
        )
    commit = preservation["historical_baseline"]["commit"]
    result = subprocess.run(
        ["git", "-C", str(REPO), "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True
    )
    check(result.returncode == 0, "Historical baseline commit is absent locally")

    screenshots = json.loads((DOCS / "essential-screenshots.json").read_text())["screenshots"]
    check(len(screenshots) == 18, "Expected six prototype and twelve real Django screenshots")
    for entry in screenshots:
        path = REPO / entry["path"]
        check(
            path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"],
            f"Missing/changed essential screenshot: {entry['path']}",
        )

    names = (DOCS / "staging-manifest.txt").read_text().splitlines()
    failures.extend(manifest_failures(REPO, names))
    ignored = subprocess.run(
        ["git", "-C", str(REPO), "check-ignore", "--stdin"],
        input="\n".join(names) + "\n",
        text=True,
        capture_output=True,
    )
    check(ignored.returncode in {0, 1}, "Could not check proposed ignore rules")
    check(not ignored.stdout, "Proposed staging files are ignored: " + ignored.stdout.strip())

    link_failures, archived, optional = documentation_link_failures(REPO, names)
    failures.extend(link_failures)

    for name in names:
        if (
            safe_relative(name)
            and name.endswith(".py")
            and name.startswith(("scripts/", "ui-lab/"))
            and (REPO / name).is_file()
        ):
            source = (REPO / name).read_text()
            ast.parse(source, filename=name)
            check(
                not re.search(r"/home/[^\s\"']+/[^\s\"']*chrome", source),
                f"User-specific browser path: {name}",
            )
    check(
        (
            REPO / "ui-lab/services-dashboard/shared/assets/nunito-sans-latin-wght-normal.woff2"
        ).is_file(),
        "Real previews require the preserved local Nunito font",
    )
    print(
        json.dumps(
            {
                "proposed_files": len(names),
                "essential_screenshots": len(screenshots),
                "protected_step7_files": len(preservation["protected_step7_files"]),
                "protected_frozen_reference_files": len(
                    preservation["protected_frozen_reference_files"]
                ),
                "historical_archive_link_targets": len(set(archived)),
                "optional_local_link_targets": len(set(optional)),
                "missing_optional_local_link_targets": sorted(
                    name for name in set(optional) if not (REPO / name).exists()
                ),
                "failures": failures,
            },
            indent=2,
        )
    )
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
