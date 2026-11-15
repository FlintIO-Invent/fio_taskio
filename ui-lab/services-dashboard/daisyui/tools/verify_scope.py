"""Hash preservation, output consistency and artifact verification for Step 4."""

import hashlib
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PIL import Image

LAB = Path(__file__).resolve().parents[2]
REPO = LAB.parents[1]
ROOT = LAB / "daisyui"
OUT = ROOT / "evidence/step4"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def output_hashes():
    return {
        str(p.relative_to(ROOT / "dist")): sha(p) for p in (ROOT / "dist").rglob("*") if p.is_file()
    }


def main():
    result = {"failures": []}
    before = output_hashes()
    subprocess.run(["npm", "run", "build", "--prefix", str(ROOT)], cwd=REPO, check=True)
    result["deterministic_build"] = before == output_hashes()
    if not result["deterministic_build"]:
        result["failures"].append("Build output changed on rebuild")
    maps = {
        "production_and_prior_documents": json.loads((LAB / "evidence/preflight.json").read_text())[
            "production_hashes"
        ],
        "tabler_shared_tools_original_evidence_and_design": json.loads(
            (OUT / "protected-before.json").read_text()
        ),
    }
    for name, files in maps.items():
        changed = [n for n, h in files.items() if not (REPO / n).is_file() or sha(REPO / n) != h]
        result[name] = {"count": len(files), "changed": changed}
        result["failures"].extend(changed)
    previous = json.loads((LAB / "evidence/results.json").read_text())
    result["frozen_original_matches_saved_assets"] = all(
        sha(OUT / "original-dist" / name) == metadata["sha256"]
        for name, metadata in previous["assets"]["daisyui"].items()
    )
    result["shared_font_and_mark_unchanged"] = all(
        sha(ROOT / "dist/assets" / name) == sha(LAB / "shared/assets" / name)
        for name in ("nunito-sans-latin-wght-normal.woff2", "motionmate-logo.svg")
    )
    result["bundle_inputs_are_daisyui_or_shared"] = all(
        str((ROOT / path).resolve()).startswith(
            (str(ROOT.resolve()) + "/", str((LAB / "shared").resolve()) + "/")
        )
        for path in json.loads((ROOT / "build-meta.json").read_text())["inputs"]
    )
    matrix = json.loads((OUT / "results.json").read_text())
    result["final_assets_match_validated_output"] = all(
        sha(ROOT / "dist" / name) == metadata["sha256"]
        for name, metadata in matrix["assets"]["daisyui"].items()
    )
    checked = 0
    for case in matrix["scenarios"]:
        for name in set(case["screenshots"]):
            with Image.open(OUT / name) as image:
                width, height = image.size
            if (
                width != case["width"]
                or ("viewport" in name and height != case["height"])
                or ("full" in name and height < case["height"])
            ):
                result["failures"].append(f"PNG dimensions: {name}")
            checked += 1
    result["standard_screenshot_dimensions_checked"] = checked
    result["render_passes"] = sum(not c["checks"] for c in matrix["scenarios"])
    result["interaction_checks"] = sum(len(c["passed"]) for c in matrix["interactions"])
    result["normal_motion_checks"] = sum(len(c["passed"]) for c in matrix["normal_motion"])
    result["parity_pairs"] = sum(c["fixture_equal"] and c["route_equal"] for c in matrix["parity"])
    result["matrix_pngs"] = len(list((OUT / "screenshots").glob("*.png")))
    result["supplemental_pngs"] = len(list((OUT / "details").glob("*.png")))
    for key in (
        "frozen_original_matches_saved_assets",
        "shared_font_and_mark_unchanged",
        "bundle_inputs_are_daisyui_or_shared",
        "final_assets_match_validated_output",
    ):
        if not result[key]:
            result["failures"].append(key)
    for name in ("details.json", "contrast-states.json"):
        result["failures"].extend(json.loads((OUT / name).read_text())["failures"])
    result["failures"].extend(
        c["state"]
        for c in json.loads((OUT / "contracts.json").read_text())
        if not all(c["matches"].values())
    )
    result["date"] = "2026-11-15"
    (OUT / "scope-check.json").write_text(json.dumps(result, indent=2) + "\n")
    missing = []
    for file in (
        REPO / "docs/design/motionmate-ui-lab/04-daisyui-refinement.md",
        OUT / "screenshot-index.md",
        OUT / "gallery.html",
    ):
        links = (
            re.findall(r'(?:href|src)=[\'"]([^\'"]+)', file.read_text())
            if file.suffix == ".html"
            else re.findall(r"\]\(([^)]+)\)", file.read_text())
        )
        for link in links:
            if link.startswith(("http:", "https:", "#")):
                continue
            target = unquote(urlsplit(link).path)
            if not (file.parent / target).exists():
                missing.append(f"{file}: {link}")
    result["missing_artifact_links"] = missing
    result["failures"].extend(missing)
    (OUT / "scope-check.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return len(result["failures"])


if __name__ == "__main__":
    raise SystemExit(main())
