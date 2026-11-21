"""Team-specific setup through existing ownership guards; no shared adapter edits."""

import argparse
import json
import subprocess
from pathlib import Path

from ui_preview.cli import display, start
from ui_preview.core import REPO, SIDES, child_env, initialize, new_session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-snapshot", type=Path, required=True)
    args = parser.parse_args()
    root, state = new_session(
        REPO,
        args.before_snapshot,
        ports=(8810, 8811, 8812, 55510, 55511),
        route="/businesses/team/",
    )
    print(f"Owned team review session: {root}", flush=True)
    for side in SIDES:
        initialize(root, state, side)
        with (Path(state[side]["directory"]) / "team-setup.log").open("x") as log:
            subprocess.run(
                [state["python"], "-B", "-m", "ui_preview.team_fixtures"],
                cwd=state[side]["source"],
                env=child_env(root, state, side, "setup"),
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
        print(f"Verified team fixtures for {side}.", flush=True)
    before = json.loads((root / "before/fixtures.json").read_text())
    after = json.loads((root / "after/fixtures.json").read_text())
    if before != after:
        raise RuntimeError("Initial canonical team fixtures differ; apps are not started.")
    start(root, state)
    display(root, state)


if __name__ == "__main__":
    main()
