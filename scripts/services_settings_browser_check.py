"""Real Settings and availability browser review on independently owned resources."""

import argparse
import json
import os
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image
from playwright.sync_api import sync_playwright
from services_clients_browser_check import axe, health, login
from ui_preview.core import load_session, verify_database, verify_source

SCOPE = ".mm-services-settings"


def section(page, target):
    page.locator('.mm-settings-index a[href="#' + target + '"]').click()
    assert page.locator('#' + target).is_visible()
    assert page.locator('[data-mm-settings-panel]:visible').count() == 1


def submit(page, button):
    with page.expect_navigation(wait_until="networkidle"):
        button.click()


def capture(session_path, side):
    root, state = load_session(session_path)
    verify_source(state[side]["source"])
    verify_database(root, state, side)
    origin, _ = health(state, side)
    out = Path(state[side]["directory"]) / "evidence/settings-revision-1"
    out.mkdir(parents=True, exist_ok=True)
    cases, scenarios, roles, errors, shots, sections = [], [], [], [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("PWA_CHROMIUM"))
        context = browser.new_context(reduced_motion="reduce", service_workers="block")
        context.route(
            "**/*", lambda r: r.continue_() if r.request.url.startswith(origin + "/") else r.abort()
        )
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        login(page, origin, state, "owner@preview.test", allow_restricted=True)
        for width, height in [(1440, 1000), (768, 1024), (390, 844), (320, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            for theme in ["light", "dark"]:
                page.evaluate("t=>localStorage.setItem('phoenixTheme',t)", theme)
                for name, path in [
                    ("settings", "/businesses/settings/"),
                    ("booking", "/businesses/settings/booking/"),
                ]:
                    response = page.goto(origin + path, wait_until="networkidle")
                    page.evaluate("document.fonts.ready")
                    metrics = page.evaluate(
                        """() => {const r=document.querySelector('.mm-services-settings')||document.querySelector('.content');const es=[...r.querySelectorAll('[id]')];const ids=es.map(e=>e.id);return {overflow:document.documentElement.scrollWidth>innerWidth,h1:r.querySelectorAll('h1').length,font:getComputedStyle(r).fontFamily,duplicateIds:ids.filter((id,i)=>ids.indexOf(id)!==i),small:[...r.querySelectorAll('a,button,input:not([type=hidden]),select,textarea,summary')].filter(e=>e.checkVisibility({checkVisibilityCSS:true})).map(e=>{let hit=e.type==='checkbox'?(e.labels[0]||e):e;const b=hit.getBoundingClientRect();return {name:e.name||e.textContent.trim().slice(0,40),w:b.width,h:b.height}}).filter(e=>e.w<43.9||e.h<43.9)};}"""
                    )
                    result = {
                        "screen": name,
                        "width": width,
                        "theme": theme,
                        "status": response.status,
                        "metrics": metrics,
                        "axe": axe(page, SCOPE if side == "after" else ".content"),
                    }
                    if name == "booking" and side == "after":
                        page.get_by_role("tab", name="Bulk", exact=True).click()
                        day = page.locator("#id_bulk_days_1")
                        day.evaluate("e=>e.scrollIntoView({block:'center'})")
                        result["bulk_pointer_target"] = day.evaluate(
                            "e=>{const r=e.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===e}"
                        )
                        result["bulk_axe"] = axe(page, SCOPE)
                        assert result["bulk_pointer_target"], result
                        assert not result["bulk_axe"]["violations"], result["bulk_axe"][
                            "violations"
                        ]
                        page.get_by_role("tab", name="Single", exact=True).click()
                    cases.append(result)
                    (out / "cases-progress.json").write_text(json.dumps(cases, indent=2) + "\n")
                    if (width, theme) in [(1440, "light"), (390, "dark")]:
                        shot = out / (name + "-" + str(width) + "-" + theme + ".png")
                        page.screenshot(path=str(shot), full_page=True, animations="disabled")
                        shots.append(str(shot))
                    if side == "after":
                        assert (
                            response.status == 200
                            and metrics["h1"] == 1
                            and not metrics["overflow"]
                        ), result
                        assert not metrics["duplicateIds"], metrics
                        assert not result["axe"]["violations"], result["axe"]["violations"]
                        assert not metrics["small"], metrics["small"]
                    if name == "settings" and side == "after":
                        assert page.locator('#workspace-tools').is_visible()
                        assert page.locator('#workspace-profile-title').is_visible()
                        assert page.locator('#account-profile-title').is_visible()
                        for link in page.locator('[data-mm-settings-link]').all():
                            target = link.get_attribute('href')[1:]
                            section(page, target)
                            current = {
                                'section': target, 'width': width, 'theme': theme,
                                'axe': axe(page, SCOPE),
                                'overflow': page.evaluate('document.documentElement.scrollWidth>innerWidth'),
                                'small': page.locator(SCOPE).evaluate("""r=>[...r.querySelectorAll('a,button,input:not([type=hidden]),select,textarea')].filter(e=>e.checkVisibility({checkVisibilityCSS:true})).map(e=>{const b=(e.type==='checkbox'?(e.labels[0]||e):e).getBoundingClientRect();return {name:e.name||e.textContent.trim(),w:b.width,h:b.height}}).filter(e=>e.w<43.9||e.h<43.9)"""),
                            }
                            sections.append(current)
                            (out/'sections-progress.json').write_text(json.dumps(sections,indent=2)+'\n')
                            assert not current['axe']['violations'], current
                            assert not current['overflow'] and not current['small'], current
                            assert page.locator('[data-mm-settings-link][aria-current=page]').get_attribute('href') == '#' + target
                            if (width, theme) == (1440, 'light') and target in ['business-details','invoice-defaults','my-account']:
                                page.evaluate('window.scrollTo(0,0)')
                                page.screenshot(path=str(out/(target+'-1440-light.png')),full_page=True,animations='disabled')
        for scenario in ["empty", "long", "restricted", "locked", "eur"]:
            login(page, origin, state, scenario + ".owner@preview.test", allow_restricted=True)
            response = page.goto(origin + "/businesses/settings/", wait_until="networkidle")
            scenarios.append(
                {
                    "scenario": scenario,
                    "status": response.status,
                    "overflow": page.evaluate("document.documentElement.scrollWidth>innerWidth"),
                }
            )
            assert response.status == 200 and not scenarios[-1]["overflow"]
        for role in ["admin", "staff", "accountant", "viewer"]:
            login(page, origin, state, role + "@preview.test", allow_restricted=True)
            page.goto(origin + "/businesses/settings/", wait_until="networkidle")
            roles.append(
                {
                    "role": role,
                    "business_form": page.locator("#business-settings-form").count(),
                    "personal_form": page.locator("[name=account-email]").count(),
                }
            )
            assert (
                roles[-1]["business_form"] == (1 if role == "admin" else 0)
                and roles[-1]["personal_form"] == 1
            )
        login(page, origin, state, "settings.logistics.owner@preview.test", allow_restricted=True)
        page.goto(origin + "/businesses/settings/", wait_until="networkidle")
        logistics = {
            "new_assets": page.locator('[href*="services-settings.css"]').count(),
            "transport": page.locator("[name=section][value=logistics_transport]").count(),
        }
        assert logistics["new_assets"] == 0
        journeys = {}
        if side == "after":
            login(page, origin, state, "owner@preview.test", allow_restricted=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(origin + "/businesses/settings/", wait_until="networkidle")
            section(page, 'my-account')
            personal = page.locator("form").filter(
                has=page.locator('[name="section"][value="account"]')
            )
            personal.locator("[name=account-first_name]").fill("Browser")
            submit(page, personal.get_by_role("button", name="Save personal details", exact=True))
            assert page.locator("[name=account-first_name]").input_value() == "Browser"
            section(page, 'business-details')
            business = page.locator("#business-settings-form")
            newname = "Harbour Settings " + uuid4().hex[:8]
            business.locator("[name=name]").fill(newname)
            section(page, 'invoice-defaults')
            png = BytesIO()
            Image.new("RGBA", (140, 50), (57, 73, 219, 255)).save(png, format="PNG")
            business.locator("[name=invoice_logo]").set_input_files(
                {"name": "synthetic-logo.png", "mimeType": "image/png", "buffer": png.getvalue()}
            )
            submit(page, business.get_by_role("button", name="Save business settings", exact=True))
            assert page.locator("[name=name]").input_value() == newname
            assert page.get_by_alt_text("Current company invoice logo").count() == 1
            assert page.locator('.mm-business-avatar img').count() == 1
            assert page.locator('#workspace-profile-title').inner_text() == newname
            section(page, 'business-details')
            business = page.locator("#business-settings-form")
            business.locator("[name=name]").fill("")
            section(page, 'invoice-defaults')
            submit(page, business.get_by_role("button", name="Save business settings", exact=True))
            assert page.locator("[name=name]").get_attribute("aria-invalid") == "true"
            assert page.locator('#business-details').is_visible()
            assert page.get_by_alt_text("Current company invoice logo").count() == 1
            page.goto(origin + "/businesses/settings/", wait_until="networkidle")
            section(page, 'invoice-defaults')
            business = page.locator("#business-settings-form")
            business.locator("[name=remove_invoice_logo]").check()
            submit(page, business.get_by_role("button", name="Save business settings", exact=True))
            assert page.get_by_alt_text("Current company invoice logo").count() == 0
            section(page, 'business-details')
            page.locator("[name=name]").fill("Unsaved draft")
            section(page, 'regional-defaults')
            original_timezone = page.locator('[name=timezone]').input_value()
            section(page, 'invoice-defaults')
            business.locator('[name=invoice_logo]').set_input_files({'name':'draft-logo.png','mimeType':'image/png','buffer':png.getvalue()})
            section(page, 'my-account')
            page.locator('[name=account-first_name]').fill('Unsaved personal draft')
            section(page, 'business-details')
            assert page.locator('[name=name]').input_value() == 'Unsaved draft'
            assert page.locator('[name=account-first_name]').input_value() == 'Unsaved personal draft'
            assert page.locator('[name=timezone]').input_value() == original_timezone
            assert page.locator('[name=invoice_logo]').evaluate('e=>e.files[0].name') == 'draft-logo.png'
            assert 'Unsaved business changes' in page.locator('[data-mm-draft-status]').inner_text()
            assert 'Unsaved personal changes' in page.locator('[data-mm-draft-status]').inner_text()
            page.evaluate("document.documentElement.dataset.bsTheme='dark'")
            assert page.locator("[name=name]").input_value() == "Unsaved draft"
            page.locator("[name=name]").focus()
            page.keyboard.press("Tab")
            assert page.locator("[name=email]").evaluate("e=>e===document.activeElement")
            page.goto(origin+'/businesses/settings/#security',wait_until='networkidle')
            assert page.locator('#security').is_visible()
            section(page, 'my-account')
            page.go_back(wait_until='networkidle')
            assert page.locator('#security').is_visible()
            page.go_forward(wait_until='networkidle')
            assert page.locator('#my-account').is_visible()
            page.goto(origin + "/businesses/settings/booking/", wait_until="networkidle")
            initial = page.locator("[data-availability-id]").count()
            page.get_by_role("tab", name="Bulk", exact=True).click()
            panel = page.locator("#availability-bulk-panel")
            panel.locator("[name=start_time]").fill("17:00")
            panel.locator("[name=end_time]").fill("09:00")
            submit(page, panel.get_by_role("button", name="Add selected days", exact=True))
            assert (
                page.locator("#availability-bulk-panel").get_attribute("class").find("active") >= 0
            )
            assert page.locator("#id_bulk_end_time").get_attribute("aria-invalid") == "true"
            panel = page.locator("#availability-bulk-panel")
            for checkbox in panel.locator("[name=days]").all():
                checkbox.uncheck()
            for day in ["0", "1"]:
                panel.locator('[name=days][value="' + day + '"]').check()
            panel.locator("[name=start_time]").fill("09:00")
            panel.locator("[name=end_time]").fill("17:00")
            submit(page, panel.get_by_role("button", name="Add selected days", exact=True))
            assert page.locator("[data-availability-id]").count() == initial + 2
            submit(
                page,
                page.get_by_role("button", name="Deactivate Monday 09:00 availability", exact=True),
            )
            assert page.locator("[data-availability-id]").count() == initial + 1
            page.evaluate("document.documentElement.dir='rtl'")
            assert not page.evaluate("document.documentElement.scrollWidth>innerWidth")
            journeys = {
                "personal_save": True,
                "business_logo_save": True,
                "invalid_preserves_logo": True,
                "remove_logo": True,
                "theme_draft": True,
                "keyboard": True,
                "bulk_invalid_panel_ids": True,
                "bulk_native_two_rows": True,
                "deactivate": True,
                "rtl": True,
                "focused_section_navigation": True,
                "cross_section_text_select_file_and_personal_drafts": True,
                "deep_link_and_back_forward": True,
                "hidden_section_server_errors_revealed": True,
                "saved_logo_in_business_profile": True,
            }
        browser.close()
    report = {
        "side": side,
        "cases": cases,
        "scenarios": scenarios,
        "roles": roles,
        "logistics": logistics,
        "journeys": journeys,
        "page_errors": errors,
        "screenshots": shots,
        "sections": sections,
    }
    (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    assert not errors, errors
    print(
        json.dumps(
            {
                "side": side,
                "cases": len(cases),
                "scenarios": len(scenarios),
                "roles": roles,
                "logistics": logistics,
                "journeys": journeys,
                "evidence": str(out),
            }
        )
    )


def supplemental(session_path):
    """Revision-specific native fallback, clipboard, profile and reflow evidence."""
    root, state = load_session(session_path)
    verify_source(state['after']['source'])
    verify_database(root, state, 'after')
    origin, _ = health(state, 'after')
    out = Path(state['after']['directory'])/'evidence/settings-revision-1'
    out.mkdir(parents=True, exist_ok=True)
    result, errors, failed, console = {}, [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get('PWA_CHROMIUM'))
        context = browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce',service_workers='block')
        context.route('**/*', lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        context.grant_permissions(['clipboard-read','clipboard-write'], origin=origin)
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('requestfailed', lambda r:failed.append({'url':r.url,'failure':r.failure}))
        page.on('console', lambda m:console.append(m.text) if m.type=='error' else None)
        login(page, origin, state, 'owner@preview.test', allow_restricted=True)
        page.goto(origin+'/businesses/settings/',wait_until='networkidle')
        section(page,'online-booking')
        share = page.locator('#online-booking')
        expected = share.locator('input[type=url]').input_value()
        share.get_by_role('button',name='Copy online booking link').click()
        assert page.evaluate('navigator.clipboard.readText()') == expected
        result['existing_copy_action'] = True
        if share.locator('a[target=_blank]').count():
            with page.expect_popup() as popup:
                share.locator('a[target=_blank]').click()
            opened = popup.value
            opened.wait_for_load_state('networkidle')
            assert opened.url.startswith(origin+'/')
            result['existing_open_action'] = {'local_path':opened.url.removeprefix(origin)}
            opened.close()
        section(page,'my-account')
        personal=page.locator('form').filter(has=page.locator('[name=section][value=account]'))
        personal.locator('[name=account-email]').fill('')
        submit(page,personal.get_by_role('button',name='Save personal details',exact=True))
        assert page.locator('#my-account').is_visible()
        assert page.locator('[name=account-email]').get_attribute('aria-invalid')=='true'
        result['personal_server_errors_revealed']=True
        page.goto(origin+'/businesses/settings/',wait_until='networkidle')
        nojs=browser.new_context(storage_state=context.storage_state(),java_script_enabled=False,service_workers='block')
        nojs.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        native=nojs.new_page()
        native.goto(origin+'/businesses/settings/',wait_until='networkidle')
        visible=native.locator('[data-mm-settings-panel]:visible').count()
        assert visible==8, visible
        native_personal=native.locator('form').filter(has=native.locator('[name=section][value=account]'))
        same_name=native_personal.locator('[name=account-first_name]').input_value()
        submit(native,native_personal.get_by_role('button',name='Save personal details',exact=True))
        assert native.locator('[name=account-first_name]').input_value()==same_name
        assert native.locator('#business-settings-form').is_visible()
        result['javascript_disabled_native_forms']={'visible_sections':visible,'personal_save':True}
        nojs.close()
        page.goto(origin+'/businesses/settings/',wait_until='networkidle')
        link=page.locator('.mm-settings-index a[href="#business-details"]')
        link.focus();page.keyboard.press('Enter')
        assert page.locator('#business-details').is_visible()
        assert page.locator('#business-details-title').evaluate('e=>e===document.activeElement')
        result['keyboard_navigation_heading_focus']=True
        section(page,'invoice-defaults')
        image_file=BytesIO()
        Image.new('RGBA',(140,50),(57,73,219,255)).save(image_file,format='PNG')
        page.locator('[name=invoice_logo]').set_input_files({'name':'synthetic-company-logo.png','mimeType':'image/png','buffer':image_file.getvalue()})
        remove=page.locator('[name=remove_invoice_logo]')
        if remove.count():remove.uncheck()
        submit(page,page.get_by_role('button',name='Save business settings',exact=True))
        assert page.locator('.mm-business-avatar img').count()==1
        result['final_synthetic_invoice_logo_saved_and_present_in_profile']=True
        for width, theme in [(1440,'light'),(390,'dark')]:
            page.set_viewport_size({'width':width,'height':1000 if width==1440 else 844})
            page.evaluate("t=>localStorage.setItem('phoenixTheme',t)",theme)
            page.goto(origin+'/businesses/settings/',wait_until='networkidle')
            page.evaluate('document.fonts.ready')
            page.screenshot(path=str(out/f'settings-final-{width}-{theme}.png'),full_page=True,animations='disabled')
            if width==1440:
                section(page,'invoice-defaults')
                page.evaluate('window.scrollTo(0,0)')
                page.screenshot(path=str(out/'invoice-final-1440-light.png'),full_page=True,animations='disabled')
            page.evaluate("document.documentElement.dir='rtl'")
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        result['rtl_desktop_and_mobile']=True
        page.set_viewport_size({'width':720,'height':1000})
        page.evaluate("document.documentElement.dir='ltr'")
        result['reflow720']=[]
        for path in ['/businesses/settings/','/businesses/settings/booking/']:
            page.goto(origin+path,wait_until='networkidle')
            record={'path':path,'overflow':page.evaluate('document.documentElement.scrollWidth>innerWidth'),'scoped_axe':axe(page,SCOPE),'full_page_axe':axe(page)}
            assert not record['overflow'] and not record['scoped_axe']['violations'],record
            result['reflow720'].append(record)
        result['page_errors']=errors
        result['blocked_requests']=failed
        result['console_errors']=console
        browser.close()
    (out/'supplemental.json').write_text(json.dumps(result,indent=2)+'\n')
    assert not errors,errors
    print(json.dumps({'supplemental':str(out/'supplemental.json'),'native_fallback':True,'clipboard':True,'logo':True,'page_errors':errors}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--side", choices=["before", "after"], required=True)
    parser.add_argument("--supplemental", action="store_true")
    args = parser.parse_args()
    if args.supplemental:
        if args.side != 'after':parser.error('Supplemental revision checks require AFTER.')
        supplemental(args.session)
    else:
        capture(args.session, args.side)
