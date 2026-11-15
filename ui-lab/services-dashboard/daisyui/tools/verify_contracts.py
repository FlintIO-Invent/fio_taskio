"""Compare all navigation/form/hook contracts with the frozen original DaisyUI."""

import asyncio
import json
import threading

from playwright.async_api import async_playwright
from validate_details import CHROME, OUT, STATES, make_server

CONTRACT = """()=>({
 fixture:window.labState,
 routes:[...document.querySelectorAll('[data-route]')].map(e=>({route:e.dataset.route,id:e.dataset.id||null,query:e.dataset.query||'',href:e.getAttribute('href'),target:e.getAttribute('target'),rel:e.getAttribute('rel')})),
 forms:[...document.querySelectorAll('form')].map(e=>({method:e.getAttribute('method'),action:e.getAttribute('action'),route:e.dataset.intentRoute,fields:[...e.querySelectorAll('input')].map(i=>({name:i.name,value:i.value,type:i.type}))})),
 hooks:[...document.querySelectorAll('[data-onboarding-target]')].map(e=>e.dataset.onboardingTarget),
 overlays:[...document.querySelectorAll('[data-overlay]')].map(e=>({id:e.id,backdrop:e.dataset.bsBackdrop,keyboard:e.dataset.bsKeyboard}))
})"""


async def main():
    server = make_server()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=CHROME, headless=True)
        page = await browser.new_page(
            viewport={"width": 390, "height": 844}, reduced_motion="reduce"
        )
        await page.route(
            "**/*",
            lambda route: (
                route.continue_()
                if route.request.method == "GET" and route.request.url.startswith(origin + "/")
                else route.abort()
            ),
        )
        for state in STATES:
            pair = []
            for path in ("daisyui/evidence/step4/original-dist", "daisyui/dist"):
                await page.goto(
                    f"{origin}/{path}/?theme=light&state={state}", wait_until="networkidle"
                )
                await page.wait_for_function("window.labReady")
                pair.append(await page.evaluate(CONTRACT))
            results.append(
                {
                    "state": state,
                    "matches": {key: pair[0][key] == pair[1][key] for key in pair[0]},
                    "original": pair[0],
                    "refined": pair[1],
                }
            )
        await browser.close()
    server.shutdown()
    server.server_close()
    (OUT / "contracts.json").write_text(json.dumps(results, indent=2) + "\n")
    failures = [r["state"] for r in results if not all(r["matches"].values())]
    print(
        json.dumps(
            {
                "states": len(results),
                "dimensions": ["fixture", "routes", "forms", "hooks", "overlays"],
                "failures": failures,
            }
        ),
        flush=True,
    )
    return len(failures)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
