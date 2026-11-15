"""Compare existing-file hashes; read-only outside the requested evidence output."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {
    "AGENTS.md",
    ".agents/skills/motionmate-ui/SKILL.md",
    "ui-lab/services-dashboard/tools/serve.py",
}


def digest(mapping):
    return hashlib.sha256(
        json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def main(args):
    before = json.loads(args.before.read_text())
    protected = {key: value for key, value in before.items() if key not in ALLOWED}
    current = {
        key: hashlib.sha256((ROOT / key).read_bytes()).hexdigest()
        if (ROOT / key).is_file()
        else None
        for key in protected
    }
    changed = [key for key in protected if current[key] != protected[key]]
    groups = {
        "production_src": lambda key: key.startswith("src/"),
        "step4_daisyui": lambda key: key.startswith("ui-lab/services-dashboard/daisyui/"),
        "dashboard_shared": lambda key: key.startswith("ui-lab/services-dashboard/shared/"),
        "earlier_design_evidence": lambda key: key.startswith("docs/design/motionmate-ui-lab/"),
    }
    result = {
        "protectedFiles": len(protected),
        "unchanged": len(protected) - len(changed),
        "unexpectedChanges": changed,
        "protectedDigestBefore": digest(protected),
        "protectedDigestAfter": digest(current),
        "authorizedExistingEdits": sorted(ALLOWED),
        "groups": {
            name: {
                "files": sum(predicate(key) for key in protected),
                "unchanged": not any(predicate(key) for key in changed),
            }
            for name, predicate in groups.items()
        },
        "limits": "Existing-file byte preservation, not a runtime/database/provider test. New-file scope is also reviewed with git status and source-import checks.",
        "pass": not changed,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if changed:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args())
