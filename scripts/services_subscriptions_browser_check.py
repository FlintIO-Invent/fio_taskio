"""Real subscription review and native-form checks on verified owned resources only."""

import argparse
import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from services_clients_browser_check import axe, health, login
from ui_preview.core import load_session, verify_database, verify_source

SCOPE = ".mm-services-subscriptions"
METRICS = """() => {const root=document.querySelector('.mm-services-subscriptions')||document.querySelector('.content');const controls=[...root.querySelectorAll('a,button,input:not([type=hidden]),select,textarea,summary')].filter(e=>e.checkVisibility({checkVisibilityCSS:true})).map(e=>{const r=e.getBoundingClientRect();return {name:e.getAttribute('aria-label')||e.name||e.textContent.trim().slice(0,80),width:r.width,height:r.height};});return {width:innerWidth,documentWidth:document.documentElement.scrollWidth,h1:root.querySelectorAll('h1').length,font:getComputedStyle(root).fontFamily,smallTargets:controls.filter(e=>e.width<43.9||e.height<43.9),scope:root.matches('.mm-services-subscriptions')};}"""


def capture(session_path, side):
    root, state = load_session(session_path)
    if state["route"] != "/businesses/subscription/":
        raise RuntimeError("Subscription route required.")
    verify_source(state[side]["source"])
    verify_database(root, state, side)
    origin, identity = health(state, side)
    out = root / side / "evidence" / ("subscriptions-" + str(time.time_ns()))
    out.mkdir(parents=True)
    cases, scenarios, roles, errors = [], [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("PWA_CHROMIUM"),
            args=["--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1"],
        )
        context = browser.new_context(reduced_motion="reduce", service_workers="block")
        context.route(
            "**/*", lambda r: r.continue_() if r.request.url.startswith(origin + "/") else r.abort()
        )
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        login(page, origin, state, "subscriptions.owner@preview.test", allow_restricted=True)
        for width, height in [(1440, 1000), (768, 1024), (390, 844), (320, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            for theme in ["light", "dark"]:
                page.evaluate("t=>localStorage.setItem('phoenixTheme',t)", theme)
                response = page.goto(origin + state["route"], wait_until="networkidle")
                page.evaluate("document.fonts.ready")
                m = page.evaluate(METRICS)
                case = {
                    "screen": "subscription",
                    "width": width,
                    "theme": theme,
                    "status": response.status,
                    "metrics": m,
                    "axe": axe(page, SCOPE if m["scope"] else ".content"),
                }
                if width == 1440 and theme == "light":
                    case["full_page_axe"] = axe(page)
                page.screenshot(
                    path=str(out / f"subscription-{width}-{theme}.png"),
                    full_page=True,
                    animations="disabled",
                )
                cases.append(case)
                (out / "cases-progress.json").write_text(json.dumps(cases, indent=2) + "\n")
        page.set_viewport_size({"width": 390, "height": 844})
        for scenario in [
            "empty",
            "long",
            "trial",
            "pending",
            "cancel",
            "grace",
            "readonly",
            "stale",
            "missing-period",
            "cancelled",
            "beta",
            "free-test",
            "no-subscription",
        ]:
            login(
                page,
                origin,
                state,
                "subscriptions." + scenario + ".owner@preview.test",
                allow_restricted=True,
            )
            for theme in ["light", "dark"]:
                page.evaluate("t=>localStorage.setItem('phoenixTheme',t)", theme)
                response = page.goto(
                    origin
                    + state["route"]
                    + ("?billing_return=1" if scenario == "readonly" else ""),
                    wait_until="networkidle",
                )
                m = page.evaluate(METRICS)
                scope = SCOPE if m["scope"] else ".content"
                scenarios.append(
                    {
                        "scenario": scenario,
                        "theme": theme,
                        "status": response.status,
                        "metrics": m,
                        "axe": axe(page, scope),
                        "selection_forms": page.locator(".content form input[name=plan]").count(),
                        "return_notice": page.get_by_text(
                            "Your billing update is being confirmed.", exact=True
                        ).count(),
                        "resume": page.get_by_role(
                            "button", name="Complete payment setup", exact=True
                        ).count(),
                    }
                )
                if scenario in ["long", "readonly", "trial", "pending"] and theme == "dark":
                    page.screenshot(
                        path=str(out / f"{scenario}-390-{theme}.png"),
                        full_page=True,
                        animations="disabled",
                    )
        for scenario in ["populated", "logistics"]:
            for role in ["owner", "admin", "staff", "accountant", "viewer"]:
                email = (
                    "subscriptions."
                    + ("" if scenario == "populated" else "logistics.")
                    + role
                    + "@preview.test"
                )
                login(page, origin, state, email, allow_restricted=True)
                response = page.goto(origin + state["route"], wait_until="networkidle")
                roles.append(
                    {
                        "scenario": scenario,
                        "role": role,
                        "status": response.status,
                        "url": page.url,
                        "new_scope": page.locator(SCOPE).count(),
                        "new_asset": page.locator(
                            'link[href*="services-subscriptions.css"]'
                        ).count(),
                    }
                )
        browser.close()
    report = {
        "side": side,
        "source_sha256": identity["source_sha256"],
        "cases": cases,
        "scenarios": scenarios,
        "roles": roles,
        "page_errors": errors,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    failures = []
    if side == "after":
        for c in cases + scenarios:
            m = c["metrics"]
            if c["status"] != 200 or not m["scope"]:
                failures.append(
                    "Unexpected page "
                    + str(c.get("scenario", c["screen"] if "screen" in c else ""))
                )
            if m["documentWidth"] > m["width"]:
                failures.append("Page overflow")
            if m["smallTargets"]:
                failures.append("Small targets")
            if c["axe"]["violations"]:
                failures.append("Module accessibility")
        for c in scenarios:
            if (
                c["scenario"]
                in [
                    "readonly",
                    "pending",
                    "stale",
                    "missing-period",
                    "cancelled",
                    "no-subscription",
                ]
                and c["selection_forms"]
            ):
                failures.append("Restricted selection form")
            if c["scenario"] == "readonly" and c["return_notice"] != 1:
                failures.append("Return notice missing")
        for c in roles:
            if c["scenario"] == "logistics" and (c["new_scope"] or c["new_asset"]):
                failures.append("Logistics assets changed")
            if c["scenario"] == "populated" and c["role"] != "owner" and c["new_scope"]:
                failures.append("Owner boundary leaked")
    if errors:
        failures.append("JavaScript errors")
    print(
        json.dumps(
            {
                "evidence": str(out),
                "core_cases": len(cases),
                "states": len(scenarios),
                "roles": len(roles),
                "failures": sorted(set(failures)),
            },
            indent=2,
        )
    )
    if failures:
        raise SystemExit(1)


if __name__ != "__main__":
    from datetime import timedelta
    from types import SimpleNamespace
    from unittest import mock

    from django.contrib.staticfiles.testing import StaticLiveServerTestCase
    from django.test import override_settings
    from django.urls import reverse
    from django.utils import timezone

    from apps.businesses.models import BusinessSubscription, ClarivoPlan, UserOnboardingState
    from apps.businesses.test_service_allowances import ServicesFixture
    from apps.crm.models import Client
    from apps.crm.test_services_dashboard_ui import assert_disposable

    class SubscriptionsFormBrowserChecks(ServicesFixture, StaticLiveServerTestCase):
        port = 8768
        serialized_rollback = True

        def setUp(self):
            assert_disposable()
            super().setUp()
            UserOnboardingState.objects.create(
                business=self.business,
                user=self.owner,
                completed_welcome=True,
                selected_journey="setup_business",
            )

        def sign_in(self, page):
            page.goto(self.live_server_url + "/accounts/login/")
            page.locator("[name=email]").fill(self.owner.email)
            page.locator("[name=password]").fill("test-only-password")
            page.get_by_role("button", name="Sign In", exact=True).click()
            page.wait_for_load_state("networkidle")
            page.goto(
                self.live_server_url + reverse("business_subscription"), wait_until="networkidle"
            )

        def record(self, page, name):
            out = Path(os.environ["SERVICES_SUBSCRIPTIONS_EVIDENCE"]) / (
                "native-" + name + "-" + str(time.time_ns())
            )
            out.mkdir(parents=True)
            result = {"name": name, "metrics": page.evaluate(METRICS), "axe": axe(page, SCOPE)}
            (out / "report.json").write_text(json.dumps(result, indent=2) + "\n")
            page.screenshot(path=str(out / "screen.png"), full_page=True)
            self.assertFalse(result["axe"]["violations"])
            self.assertFalse(result["metrics"]["smallTargets"])
            self.assertEqual(result["metrics"]["documentWidth"], result["metrics"]["width"])

        def test_native_plan_cancel_confirm_keeps_clients(self):
            target = ClarivoPlan.objects.get(slug="starter")
            target.max_clients = 0
            target.save()
            before = list(Client.objects.order_by("pk").values())
            old = self.subscription.plan_id
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    executable_path=os.environ.get("PWA_CHROMIUM"),
                    args=[
                        "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1"
                    ],
                )
                context = browser.new_context(
                    reduced_motion="reduce",
                    service_workers="block",
                    viewport={"width": 390, "height": 844},
                )
                context.route(
                    "**/*",
                    lambda r: (
                        r.continue_()
                        if r.request.url.startswith(self.live_server_url + "/")
                        else r.abort()
                    ),
                )
                page = context.new_page()
                self.sign_in(page)
                page.locator(SCOPE + " .mm-actions a").first.focus()
                page.keyboard.press("Tab")
                focus = page.evaluate(
                    "() => ({href:document.activeElement.getAttribute('href'), outline:getComputedStyle(document.activeElement).outlineStyle})"
                )
                self.assertEqual(focus["href"], reverse("agent_dashboard"))
                self.assertEqual(focus["outline"], "solid")
                page.get_by_role("button", name="Select Starter", exact=True).click()
                page.wait_for_load_state("networkidle")
                self.assertIn("Confirm change to Starter", page.locator(SCOPE).inner_text())
                page.locator('label[for="themeControlToggle"]:visible').first.click()
                self.assertEqual(page.locator("[name=confirm_plan_change]").input_value(), "1")
                self.record(page, "confirmation-mobile")
                cancel = page.get_by_role("link", name="Cancel", exact=True)
                cancel.focus()
                with page.expect_navigation(wait_until="networkidle"):
                    page.keyboard.press("Enter")
                self.assertEqual(page.locator("[name=confirm_plan_change]").count(), 0)
                page.get_by_role("button", name="Select Starter", exact=True).click()
                page.wait_for_load_state("networkidle")
                confirm = page.get_by_role("button", name="Confirm Plan Change", exact=True)
                confirm.focus()
                with page.expect_navigation(wait_until="networkidle"):
                    page.keyboard.press("Enter")
                self.assertIn("Workspace plan updated to Starter", page.locator(SCOPE).inner_text())
                browser.close()
            self.subscription.refresh_from_db()
            self.assertNotEqual(self.subscription.plan_id, old)
            self.assertEqual(self.subscription.plan_id, target.pk)
            self.assertEqual(before, list(Client.objects.order_by("pk").values()))

        def provider_journey(self, kind):
            now = timezone.now()
            sub = self.subscription
            sub.plan = ClarivoPlan.objects.get(slug="pro")
            sub.payment_provider = "stripe"
            sub.billing_currency = "usd"
            sub.billing_interval = "monthly"
            sub.provider_customer_id = "cus_native_fixture"
            sub.provider_subscription_id = "sub_native_fixture"
            sub.provider_price_id = "price_pro_monthly_usd"
            sub.current_period_start = now - timedelta(days=1)
            sub.current_period_end = now + timedelta(days=29)
            if kind == "recovery":
                sub.status = "past_due"
                sub.past_due_since = now - timedelta(days=8)
                sub.grace_period_ends_at = now - timedelta(days=1)
            if kind == "resume":
                sub.status = "pending_checkout"
            sub.save()
            original = BusinessSubscription.objects.values().get(pk=sub.pk)
            settings = {
                "STRIPE_ENABLED": True,
                "STRIPE_PUBLISHABLE_KEY": "pk_test_synthetic",
                "STRIPE_SECRET_KEY": "sk_test_synthetic",
                "STRIPE_WEBHOOK_SECRET": "whsec_synthetic",
                "STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID": "bpc_test_synthetic",
                "STRIPE_PRICE_ID_MAP": {
                    (slug, interval, currency): f"price_{slug}_{interval}_{currency}"
                    for slug in ["starter", "pro", "business"]
                    for interval in ["monthly", "yearly"]
                    for currency in ["usd", "eur"]
                },
            }
            destination = (
                "https://checkout.stripe.test/synthetic"
                if kind == "resume"
                else "https://billing.stripe.test/synthetic"
            )
            api = mock.Mock(
                return_value={
                    "id": "cs_test_native" if kind == "resume" else "bps_native",
                    "url": destination,
                    "expires_at": int((now + timedelta(hours=1)).timestamp()),
                }
            )
            sdk = (
                SimpleNamespace(checkout=SimpleNamespace(Session=SimpleNamespace(create=api)))
                if kind == "resume"
                else SimpleNamespace(
                    billing_portal=SimpleNamespace(Session=SimpleNamespace(create=api))
                )
            )
            seam = (
                "apps.businesses.stripe_checkout.configure_stripe_sdk"
                if kind == "resume"
                else "apps.businesses.stripe_portal.configure_stripe_sdk"
            )
            external, captured = [], []
            post_path = reverse(
                {
                    "manage": "billing_customer_portal",
                    "recovery": "billing_payment_recovery",
                    "resume": "billing_checkout_resume",
                }[kind]
            )
            with (
                override_settings(**settings),
                mock.patch(seam, return_value=sdk),
                sync_playwright() as p,
            ):
                browser = p.chromium.launch(
                    executable_path=os.environ.get("PWA_CHROMIUM"),
                    args=[
                        "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1"
                    ],
                )
                context = browser.new_context(
                    reduced_motion="reduce",
                    service_workers="block",
                    viewport={"width": 390, "height": 844},
                )

                def transport(route):
                    if (
                        route.request.url == self.live_server_url + post_path
                        and route.request.method == "POST"
                    ):
                        response = route.fetch(max_redirects=0)
                        captured.append(
                            {
                                "status": response.status,
                                "location": response.headers.get("location"),
                            }
                        )
                        route.fulfill(
                            status=200,
                            content_type="text/plain",
                            body="Isolated test captured the provider redirect. No provider navigation was sent.",
                        )
                    elif route.request.url.startswith(self.live_server_url + "/"):
                        route.continue_()
                    else:
                        external.append(route.request.url)
                        route.abort()

                context.route("**/*", transport)
                page = context.new_page()
                self.sign_in(page)
                button = {
                    "manage": "Manage billing",
                    "recovery": "Fix payment",
                    "resume": "Complete payment setup",
                }[kind]
                self.assertEqual(page.get_by_role("button", name=button, exact=True).count(), 1)
                if kind == "recovery":
                    self.assertEqual(page.locator(SCOPE + " input[name=plan]").count(), 0)
                self.record(page, kind + "-mobile")
                page.get_by_role("button", name=button, exact=True).click()
                page.wait_for_load_state("networkidle")
                self.assertEqual(captured, [{"status": 302, "location": destination}])
                self.assertNotIn(destination, external)
                page.goto(
                    self.live_server_url + reverse("business_subscription") + "?billing_return=1",
                    wait_until="networkidle",
                )
                self.assertEqual(
                    page.get_by_text("Your billing update is being confirmed.", exact=True).count(),
                    1,
                )
                browser.close()
            api.assert_called_once()
            sub.refresh_from_db()
            current = BusinessSubscription.objects.values().get(pk=sub.pk)
            if kind == "resume":
                self.assertEqual(sub.provider_checkout_session_id, "cs_test_native")
                self.assertEqual(sub.status, "pending_checkout")
                self.assertFalse(sub.has_access)
                for key in [
                    "provider_checkout_session_id",
                    "checkout_session_expires_at",
                    "updated_at",
                ]:
                    original.pop(key)
                    current.pop(key)
            self.assertEqual(original, current)
            if kind == "recovery":
                self.assertEqual(sub.effective_access_state.code, "past_due_grace_expired")

        def test_native_manage_billing_csrf_post_and_safe_return(self):
            self.provider_journey("manage")

        def test_native_readonly_recovery_csrf_post_does_not_restore_access(self):
            self.provider_journey("recovery")

        def test_native_checkout_resume_csrf_post_does_not_activate(self):
            self.provider_journey("resume")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--side", choices=["before", "after"], required=True)
    args = parser.parse_args()
    capture(args.session, args.side)
