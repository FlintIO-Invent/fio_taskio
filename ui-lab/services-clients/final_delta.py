"""Verify final empty-history addition and retain pixel parity for existing screens."""

import asyncio
import hashlib
import json
import os
from pathlib import Path

from playwright.async_api import async_playwright
from validate import SIZES, matrix_case

ROOT = Path(__file__).resolve().parent


async def main():
    out = ROOT / "evidence/final-delta"
    out.mkdir(parents=True, exist_ok=False)
    (out / "screenshots").mkdir()
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ.get("PWA_CHROMIUM"))
        sem = asyncio.Semaphore(4)
        specs = [
            (s, "populated")
            for s in ["list", "profile", "create", "edit", "upload", "preview", "result", "draft"]
        ]
        specs.append(("profile", "no-history"))
        cases = await asyncio.gather(
            *(
                matrix_case(browser, sem, out, screen, scenario, w, h, t)
                for screen, scenario in specs
                for w, h in SIZES
                for t in ["light", "dark"]
            )
        )
        await browser.close()
    parity = []
    for case in cases:
        if case["scenario"] != "populated":
            continue
        for suffix in ["viewport", "full"]:
            name = f"{case['screen']}-populated-{case['width']}-{case['theme']}-{suffix}.png"
            old = ROOT / "evidence/run-02/screenshots" / name
            new = out / "screenshots" / name
            parity.append(
                {
                    "file": name,
                    "identical": hashlib.sha256(old.read_bytes()).digest()
                    == hashlib.sha256(new.read_bytes()).digest(),
                }
            )
    result = {
        "cases": cases,
        "pixel_parity": parity,
        "pass": all(c["pass"] for c in cases) and all(p["identical"] for p in parity),
    }
    (out / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "cases": len(cases),
                "passed": sum(c["pass"] for c in cases),
                "pixel_pairs": len(parity),
                "identical": sum(p["identical"] for p in parity),
                "pass": result["pass"],
            },
            indent=2,
        )
    )
    return result["pass"]


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(main()) else 1)
