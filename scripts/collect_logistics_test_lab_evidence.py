"""Bind successful isolated-suite artifacts to a lab report; never attest manual checks."""

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

SUITE_CHECKS = {
    "logistics": ("automated_suite", "workflow", "security", "fixture_reset"),
    "service": ("service_regression",),
    "postgresql": ("postgresql_concurrency",),
    "browser": ("browser",),
    "pwa": ("pwa",),
}
BINDING_KEYS = (
    "schema",
    "environment",
    "database_id",
    "business_id",
    "foundation_version",
    "dataset_version",
    "commit_sha",
    "tree_digest",
    "configuration_digest",
)


def collect(report, directories, operator):
    if report.get("schema") != "motionmate-logistics-acceptance-v2" or not operator.strip():
        raise ValueError("Select an acceptance V2 report and an accountable operator.")
    checks = {}
    seen = set()
    for directory in directories:
        root = Path(directory)
        results = json.loads((root / "results.json").read_text())
        suite = results.get("suite")
        if suite not in SUITE_CHECKS or suite in seen:
            raise ValueError("Each supported suite may appear once.")
        seen.add(suite)
        if (
            results.get("status") != "PASS"
            or results.get("code_changed_during_run") is not False
            or results.get("interrupted") is not False
            or results.get("tests") != results.get("planned_tests")
            or results.get("exit_code") != 0
            or type(results.get("tests")) is not int
            or results["tests"] <= 0
            or any(results.get(key) != 0 for key in ("failures", "errors", "skipped"))
            or any(results.get(key) != report.get(key) for key in ("commit_sha", "tree_digest"))
            or not report.get("commit_sha")
            or not report.get("tree_digest")
            or hashlib.sha256((root / "tests.log").read_bytes()).hexdigest()
            != results.get("log_sha256")
            or suite == "postgresql"
            and results.get("database_vendor") != "postgresql"
        ):
            raise ValueError(
                "Suite evidence must be complete, untampered, successful and match this code."
            )
        for name in SUITE_CHECKS[suite]:
            kind = (
                "postgresql"
                if suite == "postgresql"
                else "browser-emulation" if suite in {"browser", "pwa"} else "automated"
            )
            checks[name] = {
                "status": "PASS",
                "kind": kind,
                "operator": operator,
                "reference": str(root / "tests.log"),
                **{
                    key: results[key]
                    for key in ("tests", "failures", "errors", "skipped", "exit_code", "log_sha256")
                },
            }
    return {
        "binding": {key: report[key] for key in BINDING_KEYS},
        "recorded_at": datetime.now(UTC).isoformat(),
        "checks": checks,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--suite-dir", action="append", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--output", required=True, help="New 0600 evidence JSON outside Git.")
    args = parser.parse_args()
    try:
        evidence = collect(json.loads(Path(args.report).read_text()), args.suite_dir, args.operator)
        with os.fdopen(
            os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w"
        ) as artifact:
            json.dump(evidence, artifact, indent=2, sort_keys=True)
            artifact.write("\n")
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
