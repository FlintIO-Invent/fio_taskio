import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest import mock

import stripe
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.businesses.admin import CommercialPlanAdminForm
from apps.businesses.models import (
    BillingProviderWebhookEvent,
    Business,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    SubscriptionNotification,
)
from apps.businesses.stripe_checkout import (
    StripeCheckoutAlreadyCompleted,
    StripeCheckoutError,
    create_trial_checkout_session,
    resume_trial_checkout_session,
)
from apps.businesses.stripe_config import StripeConfigurationError, configure_stripe_sdk
from apps.businesses.stripe_portal import (
    get_customer_portal_availability,
    get_payment_recovery_portal_availability,
)
from apps.businesses.subscription_notifications import build_subscription_notification_email_context
from apps.businesses.test_logistics_billing import stripe_settings
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

from .billing import checkout_for_application, validate_offering_activation
from .enrollment import enroll_application, issue_enrollment_link
from .models import LogisticsApplication, LogisticsEnrollmentToken
from .test_enrollment import PASSWORD, approve, reviewer
from .tests import PILOT_POLICY, application_data

# Test-only amounts. No production commercial prices are introduced.
TEST_PRICE = Decimal("123.45")


def annual_price(price_id):
    return {
        "id": price_id,
        "active": True,
        "livemode": False,
        "type": "recurring",
        "currency": price_id.rsplit("_", 1)[-1],
        "unit_amount": 12345,
        "billing_scheme": "per_unit",
        "recurring": {"interval": "year", "interval_count": 1, "usage_type": "licensed"},
    }


class LogisticsCheckoutFixture:
    def create_application(self):
        return LogisticsApplication.objects.create(**application_data())

    def setUp(self):
        self.actor = reviewer()
        self.application = self.create_application()
        token = issue_enrollment_link(self.application.pk, actor=self.actor, expected_revision=1)
        result = enroll_application(token, password=PASSWORD)
        self.user, self.business, self.subscription = (
            result.user,
            result.business,
            result.subscription,
        )
        self.application.refresh_from_db()
        self.plan = self.subscription.plan
        self.plan.regional_prices = {
            currency: {"currency": currency.upper(), "yearly": str(TEST_PRICE)}
            for currency in ("usd", "eur")
        }
        self.plan.is_active = True
        self.plan.save(update_fields=["regional_prices", "is_active"])
        self.now = timezone.now()
        self.factory = RequestFactory()
        self.sessions = SimpleNamespace(
            create=mock.Mock(), retrieve=mock.Mock(), expire=mock.Mock()
        )
        self.sessions.create.side_effect = lambda **kwargs: {
            "id": f"cs_logistics_{self.sessions.create.call_count}",
            "url": "https://checkout.stripe.test/logistics",
            "expires_at": int((self.now + timedelta(hours=24)).timestamp()),
        }
        self.sessions.retrieve.side_effect = lambda *args, **kwargs: self.remote_session()
        self.sdk = SimpleNamespace(
            checkout=SimpleNamespace(Session=self.sessions),
            Price=SimpleNamespace(retrieve=mock.Mock(side_effect=annual_price)),
            Subscription=SimpleNamespace(
                retrieve=mock.Mock(side_effect=lambda *args, **kwargs: self.remote_subscription())
            ),
        )
        self.configure = self.enterContext(
            mock.patch(
                "apps.businesses.stripe_checkout.configure_stripe_sdk", return_value=self.sdk
            )
        )
        self.enterContext(
            mock.patch("apps.logistics.billing.configure_stripe_sdk", return_value=self.sdk)
        )
        self.enterContext(
            mock.patch(
                "apps.businesses.stripe_webhooks.configure_stripe_sdk", return_value=self.sdk
            )
        )

    def checkout(self):
        return checkout_for_application(
            self.application.pk,
            request=self.factory.post("/", HTTP_HOST="localhost"),
            user=self.user,
        )

    def login(self):
        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()

    def metadata(self, subscription=None):
        sub = subscription or self.subscription
        return {
            "motionmate_business_id": str(sub.business_id),
            "motionmate_subscription_id": str(sub.pk),
            "motionmate_user_id": str(self.user.pk),
            "plan_slug": sub.plan.slug,
            "billing_interval": sub.billing_interval,
            "billing_currency": sub.billing_currency,
        }

    def remote_session(self, **changes):
        self.subscription.refresh_from_db()
        value = {
            "id": self.subscription.provider_checkout_session_id,
            "mode": "subscription",
            "status": "open",
            "url": "https://checkout.stripe.test/logistics",
            "expires_at": int((self.now + timedelta(hours=24)).timestamp()),
            "metadata": self.metadata(),
            "client_reference_id": f"business:{self.business.pk}:subscription:{self.subscription.pk}",
            "customer": "cus_logistics",
            "subscription": "sub_logistics",
            "line_items": {
                "data": [{"quantity": 1, "price": annual_price("price_logistics_yearly_eur")}]
            },
        }
        value.update(changes)
        return value

    def remote_subscription(self, **changes):
        value = {
            "id": "sub_logistics",
            "customer": "cus_logistics",
            "status": "active",
            "metadata": self.metadata(),
            "trial_start": None,
            "trial_end": None,
            "current_period_start": int(self.now.timestamp()),
            "current_period_end": int((self.now + timedelta(days=365)).timestamp()),
            "cancel_at_period_end": False,
            "canceled_at": None,
            "items": {"data": [{"price": annual_price("price_logistics_yearly_eur")}]},
        }
        value.update(changes)
        return value

    def webhook(
        self,
        *,
        event_type="checkout.session.completed",
        event_id="evt_logistics_paid",
        remote=None,
        offset=0,
    ):
        if remote is not None:
            self.sdk.Subscription.retrieve.side_effect = None
            self.sdk.Subscription.retrieve.return_value = remote
        obj = (
            self.remote_session(status="complete")
            if event_type.startswith("checkout")
            else (remote or self.remote_subscription())
        )
        body = json.dumps(
            {
                "id": event_id,
                "object": "event",
                "type": event_type,
                "created": int(self.now.timestamp()) + offset,
                "livemode": False,
                "data": {"object": obj},
            },
            sort_keys=True,
        )
        timestamp = int(timezone.now().timestamp())
        signature = hmac.new(
            b"whsec_logistics", f"{timestamp}.{body}".encode(), hashlib.sha256
        ).hexdigest()
        return self.client.post(
            reverse("stripe_billing_webhook"),
            data=body,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=f"t={timestamp},v1={signature}",
        )


@override_settings(LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY, **stripe_settings())
class LogisticsCheckoutTests(LogisticsCheckoutFixture, TestCase):
    def test_local_live_keys_rejected_before_provider_call(self):
        with (
            override_settings(
                MOTIONMATE_ENVIRONMENT="local",
                STRIPE_PUBLISHABLE_KEY="pk_live_fixture",
                STRIPE_SECRET_KEY="sk_live_fixture",
            ),
            self.assertRaises(StripeConfigurationError) as caught,
        ):
            self.checkout()
        self.assertEqual(caught.exception.code, "logistics_test_mode_required")
        self.sessions.create.assert_not_called()

    def test_production_uses_same_pipeline_with_live_price(self):
        self.sdk.Price.retrieve.side_effect = lambda price_id: {
            **annual_price(price_id),
            "livemode": True,
        }
        with override_settings(
            MOTIONMATE_ENVIRONMENT="production",
            STRIPE_PUBLISHABLE_KEY="pk_live_fixture",
            STRIPE_SECRET_KEY="sk_live_fixture",
        ):
            self.checkout()
        self.assertEqual(
            set(self.sessions.create.call_args.kwargs["subscription_data"]), {"metadata"}
        )

    def test_price_mode_mismatch_rejected_before_session_creation(self):
        self.sdk.Price.retrieve.side_effect = lambda price_id: {
            **annual_price(price_id),
            "livemode": True,
        }
        with self.assertRaises(StripeConfigurationError):
            self.checkout()
        self.sessions.create.assert_not_called()

    def test_readiness_command_verifies_prices_without_creating_records(self):
        output = StringIO()
        with mock.patch(
            "apps.logistics.management.commands.check_logistics_checkout.configure_stripe_sdk",
            return_value=self.sdk,
        ):
            call_command(
                "check_logistics_checkout",
                application_id=self.application.pk,
                verify_provider=True,
                stdout=output,
            )
        self.assertIn("both annual Stripe Prices verified", output.getvalue())
        self.assertEqual(self.sdk.Price.retrieve.call_count, 2)
        self.sessions.create.assert_not_called()
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.provider_checkout_session_id, "")
        self.assertEqual(self.subscription.status, "pending_checkout")

    def test_readiness_command_reports_seeded_offering_and_disabled_stripe(self):
        self.plan.is_active = False
        self.plan.save(update_fields=["is_active"])
        output = StringIO()
        with override_settings(STRIPE_ENABLED=False), self.assertRaises(CommandError):
            call_command(
                "check_logistics_checkout",
                application_id=self.application.pk,
                stdout=StringIO(),
                stderr=output,
            )
        self.assertIn("stripe_disabled", output.getvalue())
        self.assertIn("logistics_offering_inactive", output.getvalue())
        self.sessions.create.assert_not_called()

    def test_signed_current_sdk_webhook_preserves_item_billing_periods_and_retry(self):
        self.checkout()
        remote = self.remote_subscription()
        start, end = (remote.pop(field) for field in ("current_period_start", "current_period_end"))
        remote["items"]["data"][0].update(current_period_start=start, current_period_end=end)
        for _ in range(2):
            self.assertEqual(self.webhook(remote=remote).status_code, 200)
        self.subscription.refresh_from_db()
        self.assertEqual(int(self.subscription.current_period_start.timestamp()), start)
        self.assertEqual(int(self.subscription.current_period_end.timestamp()), end)
        self.assertTrue(self.subscription.has_access)
        self.assertEqual(BillingProviderWebhookEvent.objects.count(), 1)
        self.assertEqual(SubscriptionNotification.objects.count(), 1)

    def test_test_mode_sdk_checkout_uses_local_urls_and_both_annual_currencies(self):
        # Exercise the real shared configuration/SDK adapter; mock only its HTTP
        # boundary. This does not claim to make a payment with a Stripe account.
        self.configure.side_effect = configure_stripe_sdk
        self.login()
        with (
            mock.patch.object(stripe, "api_key", None),
            mock.patch.object(stripe.Price, "retrieve", side_effect=annual_price),
            mock.patch.object(stripe.checkout.Session, "create", self.sessions.create),
        ):
            for currency in ("eur", "usd"):
                with self.subTest(currency=currency):
                    LogisticsApplication.objects.filter(pk=self.application.pk).update(
                        preferred_currency=currency.upper()
                    )
                    BusinessSubscription.objects.filter(pk=self.subscription.pk).update(
                        billing_currency=currency, provider_checkout_session_id=""
                    )
                    response = self.client.post(
                        reverse("logistics_application_checkout", args=[self.application.pk]),
                        HTTP_HOST="localhost:8000",
                    )
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(stripe.api_key, "sk_test_logistics")
                    params = self.sessions.create.call_args.kwargs
                    self.assertEqual(params["mode"], "subscription")
                    self.assertEqual(
                        params["line_items"],
                        [{"price": f"price_logistics_yearly_{currency}", "quantity": 1}],
                    )
                    self.assertEqual(
                        params["success_url"],
                        "http://localhost:8000/billing/checkout/success/"
                        "?session_id={CHECKOUT_SESSION_ID}",
                    )
                    self.assertEqual(
                        params["cancel_url"],
                        "http://localhost:8000/billing/checkout/cancelled/",
                    )
                    self.assertEqual(set(params["subscription_data"]), {"metadata"})
                    self.subscription.refresh_from_db()
                    self.assertEqual(self.subscription.status, "pending_checkout")
                    self.assertFalse(self.subscription.has_access)
                    self.assertEqual(Business.objects.count(), 1)
                    self.assertEqual(BusinessSubscription.objects.count(), 1)

    def test_operator_logs_inactive_offering_before_other_configuration(self):
        self.login()
        self.plan.is_active = False
        self.plan.save(update_fields=["is_active"])
        with (
            override_settings(STRIPE_ENABLED=False, STRIPE_SECRET_KEY=""),
            self.assertLogs("apps.logistics.views", level="WARNING") as logs,
        ):
            response = self.client.post(
                reverse("logistics_application_checkout", args=[self.application.pk])
            )
        self.assertContains(response, "Logistics offering is inactive", status_code=503)
        self.assertIn("reason=logistics_offering_inactive", logs.output[0])
        self.configure.assert_not_called()
        self.sessions.create.assert_not_called()

    def test_operator_logs_zero_amount_missing_price_and_disabled_stripe(self):
        self.login()
        scenarios = (
            ({"STRIPE_ENABLED": False}, "stripe_disabled"),
            (
                {"STRIPE_PRICE_ID_MAP": stripe_settings(logistics=False)["STRIPE_PRICE_ID_MAP"]},
                "motionmate_stripe.E008",
            ),
            ({}, "logistics_annual_amount_invalid"),
        )
        for overrides, reason in scenarios:
            with self.subTest(reason=reason):
                if reason == "logistics_annual_amount_invalid":
                    self.plan.regional_prices = {}
                    self.plan.price_yearly = Decimal("0")
                    self.plan.save(update_fields=["regional_prices", "price_yearly"])
                with (
                    override_settings(**overrides),
                    self.assertLogs("apps.logistics.views", level="WARNING") as logs,
                ):
                    response = self.client.post(
                        reverse("logistics_application_checkout", args=[self.application.pk])
                    )
                self.assertEqual(response.status_code, 503)
                self.assertIn(f"reason={reason}", logs.output[0])
        self.sessions.create.assert_not_called()

    def test_real_shared_sdk_missing_secret_logs_existing_configuration_code(self):
        self.configure.side_effect = configure_stripe_sdk
        self.login()
        with (
            override_settings(STRIPE_SECRET_KEY=""),
            self.assertLogs("apps.logistics.views", level="WARNING") as logs,
        ):
            response = self.client.post(
                reverse("logistics_application_checkout", args=[self.application.pk])
            )
        self.assertContains(response, "STRIPE_SECRET_KEY is required", status_code=503)
        self.assertIn("reason=motionmate_stripe.E002", logs.output[0])
        self.sessions.create.assert_not_called()

    def test_provider_error_diagnostics_never_expose_chained_provider_details(self):
        self.login()
        sensitive_detail = "sk_test_private whsec_private provider-sensitive-response"
        for boundary, reason, status in (
            (self.sdk.Price.retrieve, "stripe_price_verification_failed", 503),
            (self.sessions.create, "stripe_provider_error", 409),
        ):
            with self.subTest(reason=reason):
                original = boundary.side_effect
                boundary.side_effect = RuntimeError(sensitive_detail)
                with self.assertLogs("apps.logistics.views", level="WARNING") as logs:
                    response = self.client.post(
                        reverse("logistics_application_checkout", args=[self.application.pk])
                    )
                boundary.side_effect = original
                self.assertEqual(response.status_code, status)
                self.assertIn(f"reason={reason}", logs.output[0])
                for secret in sensitive_detail.split():
                    self.assertNotIn(secret, response.content.decode())
                    self.assertNotIn(secret, "\n".join(logs.output))
                self.subscription.refresh_from_db()
                self.assertEqual(self.subscription.provider_checkout_session_id, "")
                self.assertEqual(self.subscription.status, "pending_checkout")

    def test_operator_logs_application_revision_and_subscription_eligibility_separately(self):
        self.login()
        LogisticsApplication.objects.filter(pk=self.application.pk).update(approved_revision=0)
        with self.assertLogs("apps.logistics.views", level="WARNING") as logs:
            response = self.client.post(
                reverse("logistics_application_checkout", args=[self.application.pk])
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn("reason=logistics_application_invalid", logs.output[0])
        LogisticsApplication.objects.filter(pk=self.application.pk).update(approved_revision=1)
        BusinessSubscription.objects.filter(pk=self.subscription.pk).update(
            billing_interval="monthly"
        )
        with self.assertLogs("apps.logistics.views", level="WARNING") as logs:
            response = self.client.post(
                reverse("logistics_application_checkout", args=[self.application.pk])
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn("reason=logistics_subscription_not_eligible", logs.output[0])
        self.sessions.create.assert_not_called()

    def test_converted_owner_enters_shared_annual_checkout_with_no_trial(self):
        self.assertEqual(self.checkout(), "https://checkout.stripe.test/logistics")
        params = self.sessions.create.call_args.kwargs
        self.assertEqual(
            params["line_items"], [{"price": "price_logistics_yearly_eur", "quantity": 1}]
        )
        self.assertNotIn("trial_period_days", params["subscription_data"])
        self.assertEqual(params["metadata"], self.metadata())
        self.assertEqual(params["subscription_data"]["metadata"], params["metadata"])
        self.assertEqual(
            params["idempotency_key"], f"motionmate-checkout-{self.subscription.pk}-yearly-eur-new"
        )
        self.assertIn(reverse("billing_checkout_success"), params["success_url"])
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.provider_price_id, "price_logistics_yearly_eur")
        self.assertFalse(self.subscription.has_access)

    def test_checkout_accepts_installed_stripe_sdk_objects(self):
        self.sdk.Price.retrieve.side_effect = lambda price_id: stripe.Price.construct_from(
            annual_price(price_id), "sk_test_fixture"
        )
        self.sessions.create.side_effect = lambda **kwargs: stripe.checkout.Session.construct_from(
            {
                "id": "cs_sdk",
                "url": "https://checkout.stripe.test/logistics",
                "expires_at": int((self.now + timedelta(hours=24)).timestamp()),
            },
            "sk_test_fixture",
        )
        self.checkout()
        self.sessions.retrieve.side_effect = (
            lambda *args, **kwargs: stripe.checkout.Session.construct_from(
                self.remote_session(), "sk_test_fixture"
            )
        )
        self.assertEqual(self.checkout(), "https://checkout.stripe.test/logistics")
        self.assertEqual(self.sessions.create.call_count, 1)
        self.sdk.Subscription.retrieve.side_effect = (
            lambda *args, **kwargs: stripe.Subscription.construct_from(
                self.remote_subscription(), "sk_test_fixture"
            )
        )
        self.assertEqual(self.webhook().status_code, 200)
        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.has_access)

    def test_non_approved_revoked_and_stale_approval_rejected_before_stripe(self):
        for status in ("SUBMITTED", "UNDER_REVIEW", "DECLINED", "WITHDRAWN"):
            LogisticsApplication.objects.filter(pk=self.application.pk).update(status=status)
            with self.subTest(status=status), self.assertRaises(StripeCheckoutError):
                self.checkout()
        LogisticsApplication.objects.filter(pk=self.application.pk).update(status="APPROVED")
        for field in ("approved_revision", "evaluated_revision", "converted_revision"):
            LogisticsApplication.objects.filter(pk=self.application.pk).update(**{field: 2})
            with self.subTest(field=field), self.assertRaises(StripeCheckoutError):
                self.checkout()
            LogisticsApplication.objects.filter(pk=self.application.pk).update(**{field: 1})
        self.configure.assert_not_called()

    def test_material_changes_and_reapproval_do_not_reuse_old_conversion(self):
        self.application.phone = "+31 20 000 1111"
        self.application.save()
        approve(self.application, self.actor)
        with self.assertRaises(StripeCheckoutError):
            self.checkout()
        self.configure.assert_not_called()

    def test_unconverted_approved_application_cannot_checkout(self):
        other = LogisticsApplication.objects.create(
            **application_data(
                email="other@example.com", business_name="Other company", registration_number="REG2"
            )
        )
        approve(other, self.actor)
        with self.assertRaises(StripeCheckoutError):
            checkout_for_application(other.pk, request=self.factory.post("/"), user=self.user)
        self.sessions.create.assert_not_called()

    def test_identity_active_owner_and_business_required(self):
        for user in (AnonymousUser(), self.actor):
            with self.subTest(user=user), self.assertRaises(StripeCheckoutError):
                checkout_for_application(
                    self.application.pk, request=self.factory.post("/"), user=user
                )
        BusinessUser.objects.filter(user=self.user).update(is_active=False)
        with self.assertRaises(StripeCheckoutError):
            self.checkout()
        BusinessUser.objects.filter(user=self.user).update(
            is_active=True, role=BusinessUser.Role.ADMIN
        )
        with self.assertRaises(StripeCheckoutError):
            self.checkout()
        self.configure.assert_not_called()

    def test_invalid_subscription_family_monthly_currency_trial_provider_state_reject(self):
        for changes in (
            {"billing_interval": "monthly"},
            {"billing_currency": "usd"},
            {"plan_id": ClarivoPlan.objects.get(slug="pro").pk},
            {"payment_provider": "local"},
            {"status": "active"},
            {"trial_start": self.now},
        ):
            original = {key: getattr(self.subscription, key) for key in changes}
            BusinessSubscription.objects.filter(pk=self.subscription.pk).update(**changes)
            with self.subTest(changes=changes), self.assertRaises(StripeCheckoutError):
                self.checkout()
            BusinessSubscription.objects.filter(pk=self.subscription.pk).update(**original)
        Business.objects.filter(pk=self.business.pk).update(vertical="SERVICE")
        with self.assertRaises(StripeCheckoutError):
            self.checkout()
        self.configure.assert_not_called()

    def test_shared_checkout_cannot_bypass_approval(self):
        LogisticsApplication.objects.filter(pk=self.application.pk).update(status="DECLINED")
        for method in (create_trial_checkout_session, resume_trial_checkout_session):
            with self.subTest(method=method.__name__), self.assertRaises(StripeCheckoutError):
                method(
                    request=self.factory.post("/", HTTP_HOST="localhost"),
                    subscription=self.subscription,
                    user=self.user,
                )
        self.configure.assert_not_called()

    def test_missing_price_inactive_offering_and_placeholder_price_fail_closed(self):
        with (
            override_settings(
                STRIPE_PRICE_ID_MAP=stripe_settings(logistics=False)["STRIPE_PRICE_ID_MAP"]
            ),
            self.assertRaisesMessage(StripeConfigurationError, "not configured"),
        ):
            self.checkout()
        self.plan.is_active = False
        self.plan.save(update_fields=["is_active"])
        with self.assertRaisesMessage(StripeConfigurationError, "inactive"):
            self.checkout()
        self.plan.is_active = True
        self.plan.regional_prices = {}
        self.plan.save(update_fields=["is_active", "regional_prices"])
        with self.assertRaises(StripeConfigurationError):
            self.checkout()
        self.sessions.create.assert_not_called()

    def test_mismatched_or_unusable_remote_price_fails_closed(self):
        for changes in (
            {"active": False},
            {"unit_amount": 0},
            {"unit_amount": 9999},
            {"currency": "usd"},
            {"id": "price_pro_yearly_eur"},
            {"type": "one_time"},
            {"recurring": "invalid configuration"},
            {"recurring": {"interval": "month", "interval_count": 1, "usage_type": "licensed"}},
            {"recurring": {"interval": "year", "interval_count": 2, "usage_type": "licensed"}},
        ):
            remote = annual_price("price_logistics_yearly_eur")
            remote.update(changes)
            self.sdk.Price.retrieve.side_effect = None
            self.sdk.Price.retrieve.return_value = remote
            with self.subTest(changes=changes), self.assertRaises(StripeConfigurationError):
                self.checkout()
        self.sessions.create.assert_not_called()

    def test_invalid_regional_price_configuration_returns_configuration_error(self):
        for pricing in (["invalid"], "invalid", {"eur": ["invalid"]}):
            self.plan.regional_prices = pricing
            self.plan.save(update_fields=["regional_prices"])
            with self.subTest(pricing=pricing), self.assertRaises(StripeConfigurationError):
                self.checkout()
        self.sessions.create.assert_not_called()

    def test_service_price_alias_and_reverse_family_alias_reject(self):
        mapping = dict(stripe_settings()["STRIPE_PRICE_ID_MAP"])
        mapping[("logistics", "yearly", "eur")] = mapping[("pro", "yearly", "eur")]
        with (
            override_settings(STRIPE_PRICE_ID_MAP=mapping),
            self.assertRaises(StripeConfigurationError),
        ):
            self.checkout()
        business = Business.objects.create(name="Service", slug="service-price-check")
        sub = BusinessSubscription.objects.create(
            business=business,
            plan=ClarivoPlan.objects.get(slug="pro"),
            status="pending_checkout",
            payment_provider="stripe",
            billing_interval="yearly",
            billing_currency="eur",
        )
        mapping = dict(stripe_settings()["STRIPE_PRICE_ID_MAP"])
        mapping[("pro", "yearly", "eur")] = mapping[("logistics", "yearly", "eur")]
        with (
            override_settings(STRIPE_PRICE_ID_MAP=mapping),
            self.assertRaises(StripeConfigurationError),
        ):
            create_trial_checkout_session(
                request=self.factory.post("/", HTTP_HOST="localhost"),
                subscription=sub,
                user=self.user,
            )
        self.sessions.create.assert_not_called()

    def test_missing_enrolled_currency_does_not_fall_back_to_another_price(self):
        mapping = dict(stripe_settings()["STRIPE_PRICE_ID_MAP"])
        del mapping[("logistics", "yearly", "eur")]
        with (
            override_settings(STRIPE_PRICE_ID_MAP=mapping),
            self.assertRaises(StripeConfigurationError),
        ):
            self.checkout()
        self.sessions.create.assert_not_called()

    def test_entry_requires_authenticated_post_and_csrf(self):
        url = reverse("logistics_application_checkout", args=[self.application.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.login()
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(url).status_code, 403)
        self.assertEqual(self.client.post(url).status_code, 302)

    def test_client_plan_price_interval_and_currency_tampering_rejected_on_both_entries(self):
        self.login()
        for url in (
            reverse("logistics_application_checkout", args=[self.application.pk]),
            reverse("billing_checkout_resume"),
        ):
            for key, value in (
                ("price_id", "price_pro_monthly_usd"),
                ("plan", "pro"),
                ("billing_interval", "monthly"),
                ("currency", "usd"),
            ):
                with self.subTest(url=url, key=key):
                    self.assertEqual(self.client.post(url, {key: value}).status_code, 400)
            self.assertEqual(self.client.post(url + "?currency=usd").status_code, 400)
        self.sessions.create.assert_not_called()

    def test_other_applicant_cannot_use_application_uuid(self):
        self.client.force_login(self.actor)
        self.assertEqual(
            self.client.post(
                reverse("logistics_application_checkout", args=[self.application.pk])
            ).status_code,
            403,
        )
        self.sessions.create.assert_not_called()

    def test_configuration_error_is_clear_in_browser(self):
        self.login()
        with override_settings(
            STRIPE_PRICE_ID_MAP=stripe_settings(logistics=False)["STRIPE_PRICE_ID_MAP"]
        ):
            response = self.client.post(
                reverse("logistics_application_checkout", args=[self.application.pk])
            )
        self.assertContains(response, "Stripe Price ID is not configured", status_code=503)

    def test_open_pending_session_reused_without_duplicates(self):
        self.checkout()
        for _ in range(3):
            self.assertEqual(self.checkout(), "https://checkout.stripe.test/logistics")
        self.assertEqual(self.sessions.create.call_count, 1)
        self.sessions.retrieve.assert_called_with(
            "cs_logistics_1", expand=["line_items.data.price"]
        )
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(BusinessSubscription.objects.count(), 1)
        self.assertEqual(BusinessUser.objects.count(), 1)
        self.assertEqual(LogisticsApplication.objects.count(), 1)

    def test_expired_session_replaced_once_then_reused(self):
        self.checkout()
        expired = self.remote_session(status="expired")
        self.sessions.retrieve.side_effect = None
        self.sessions.retrieve.return_value = expired
        self.checkout()
        self.assertEqual(self.sessions.create.call_count, 2)
        self.assertTrue(
            self.sessions.create.call_args.kwargs["idempotency_key"].endswith("-cs_logistics_1")
        )
        self.sessions.retrieve.side_effect = lambda *args, **kwargs: self.remote_session()
        self.checkout()
        self.assertEqual(self.sessions.create.call_count, 2)

    def test_stored_service_price_or_revoked_approval_cannot_resume(self):
        self.checkout()
        remote = self.remote_session()
        remote["line_items"]["data"][0]["price"] = annual_price("price_pro_yearly_eur")
        self.sessions.retrieve.side_effect = None
        self.sessions.retrieve.return_value = remote
        with self.assertRaises(StripeCheckoutError):
            self.checkout()
        LogisticsApplication.objects.filter(pk=self.application.pk).update(status="DECLINED")
        with self.assertRaises(StripeCheckoutError):
            self.checkout()
        self.assertEqual(self.sessions.create.call_count, 1)

    def test_expired_enrollment_token_does_not_require_reenrollment(self):
        LogisticsEnrollmentToken.objects.filter(application=self.application).update(
            expires_at=self.now - timedelta(days=1)
        )
        self.checkout()
        self.assertEqual(Business.objects.count(), 1)

    def test_network_failure_retry_preserves_idempotency_and_enrollment(self):
        self.sessions.create.side_effect = RuntimeError("Provider unavailable")
        with self.assertRaises(StripeCheckoutError):
            self.checkout()
        key = self.sessions.create.call_args.kwargs["idempotency_key"]
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.provider_checkout_session_id, "")
        self.sessions.create.side_effect = None
        self.sessions.create.return_value = {
            "id": "cs_recovered",
            "url": "https://checkout.stripe.test/recovered",
        }
        self.checkout()
        self.assertEqual(self.sessions.create.call_args.kwargs["idempotency_key"], key)
        self.assertEqual(BusinessSubscription.objects.count(), 1)

    def test_remote_success_local_failure_preserves_provider_idempotency(self):
        original_save = BusinessSubscription.save

        def fail_save(sub, *args, **kwargs):
            if "provider_checkout_session_id" in kwargs.get("update_fields", []):
                raise RuntimeError("Local write failed")
            return original_save(sub, *args, **kwargs)

        with (
            mock.patch.object(BusinessSubscription, "save", fail_save),
            self.assertRaises(RuntimeError),
        ):
            self.checkout()
        key = self.sessions.create.call_args.kwargs["idempotency_key"]
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.provider_checkout_session_id, "")
        self.checkout()
        self.assertEqual(self.sessions.create.call_args.kwargs["idempotency_key"], key)
        self.assertEqual(BusinessSubscription.objects.count(), 1)

    def test_return_pages_do_not_activate_access_or_advertise_service_trial(self):
        self.checkout()
        self.login()
        for route in ("billing_checkout_success", "billing_checkout_cancelled"):
            response = self.client.get(reverse(route), {"session_id": "cs_fake", "paid": "true"})
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "14-day trial")
            self.assertContains(response, "annual")
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "pending_checkout")
        self.assertFalse(self.subscription.has_access)
        self.assertFalse(SubscriptionNotification.objects.exists())

    def test_completed_session_waits_for_webhook_and_does_not_duplicate_checkout(self):
        self.checkout()
        self.sessions.retrieve.side_effect = None
        self.sessions.retrieve.return_value = self.remote_session(status="complete")
        with self.assertRaises(StripeCheckoutAlreadyCompleted):
            self.checkout()
        self.login()
        self.assertRedirects(
            self.client.post(reverse("billing_checkout_resume")),
            reverse("billing_checkout_success"),
        )
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "pending_checkout")
        self.assertEqual(self.sessions.create.call_count, 1)

    def test_signed_webhook_activates_existing_subscription_and_is_idempotent(self):
        self.checkout()
        for _ in range(2):
            self.assertEqual(self.webhook().status_code, 200)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "active")
        self.assertEqual(self.subscription.provider_customer_id, "cus_logistics")
        self.assertEqual(self.subscription.provider_subscription_id, "sub_logistics")
        self.assertIsNone(self.subscription.trial_start)
        self.assertIsNone(self.subscription.trial_end)
        self.assertTrue(self.subscription.has_access)
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(BusinessSubscription.objects.count(), 1)
        self.assertEqual(TaskIOUser.objects.count(), 2)
        self.assertEqual(BillingProviderWebhookEvent.objects.count(), 1)
        notification = SubscriptionNotification.objects.get()
        self.assertEqual(
            notification.notification_type,
            SubscriptionNotification.NotificationType.SUBSCRIPTION_ACTIVATED,
        )
        self.assertIn(
            "annual Motionmate Logistics payment is confirmed",
            build_subscription_notification_email_context(notification)["body_intro"],
        )

    def test_invalid_signature_cannot_activate(self):
        self.checkout()
        response = self.client.post(
            reverse("stripe_billing_webhook"),
            data='{"id":"fake"}',
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=invalid",
        )
        self.assertEqual(response.status_code, 400)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "pending_checkout")
        self.assertFalse(BillingProviderWebhookEvent.objects.exists())

    def test_service_price_and_trial_events_cannot_activate_logistics(self):
        self.checkout()
        for index, remote in enumerate(
            (
                self.remote_subscription(
                    items={"data": [{"price": annual_price("price_pro_yearly_eur")}]}
                ),
                self.remote_subscription(
                    status="trialing",
                    trial_start=int(self.now.timestamp()),
                    trial_end=int((self.now + timedelta(days=14)).timestamp()),
                ),
            )
        ):
            with self.subTest(index=index):
                self.assertEqual(
                    self.webhook(event_id=f"evt_invalid_{index}", remote=remote).status_code, 200
                )
                self.assertEqual(
                    BillingProviderWebhookEvent.objects.get(event_id=f"evt_invalid_{index}").status,
                    "failed",
                )
                self.subscription.refresh_from_db()
                self.assertEqual(self.subscription.status, "pending_checkout")
        self.assertFalse(SubscriptionNotification.objects.exists())

    def test_abandoned_checkout_keeps_enrollment_and_can_resume(self):
        self.checkout()
        self.assertEqual(
            self.webhook(event_type="checkout.session.expired", event_id="evt_expired").status_code,
            200,
        )
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "pending_checkout")
        self.checkout()
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(self.sessions.create.call_count, 1)

    @override_settings(SUBSCRIPTION_PAYMENT_GRACE_DAYS=7)
    def test_paid_past_due_recovery_and_notifications_use_shared_lifecycle(self):
        self.checkout()
        self.assertEqual(self.webhook().status_code, 200)
        remote = self.remote_subscription(status="past_due")
        self.assertEqual(
            self.webhook(
                event_type="customer.subscription.updated",
                event_id="evt_past_due",
                remote=remote,
                offset=1,
            ).status_code,
            200,
        )
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "past_due")
        self.assertTrue(self.subscription.has_access)
        self.assertFalse(self.subscription.has_restricted_access)
        self.assertTrue(
            self.subscription.has_restricted_access_at(self.subscription.grace_period_ends_at)
        )
        notification = SubscriptionNotification.objects.get(
            notification_type=SubscriptionNotification.NotificationType.PAYMENT_GRACE_STARTED
        )
        self.assertIn(
            "Contact support for help with your Logistics subscription payment.",
            build_subscription_notification_email_context(notification)["body_lines"],
        )
        remote = self.remote_subscription(status="active")
        self.assertEqual(
            self.webhook(
                event_type="customer.subscription.updated",
                event_id="evt_recovered",
                remote=remote,
                offset=2,
            ).status_code,
            200,
        )
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "active")
        self.assertEqual(
            SubscriptionNotification.objects.filter(
                notification_type=SubscriptionNotification.NotificationType.PAYMENT_RECOVERED
            ).count(),
            1,
        )

    def test_portal_remains_disabled(self):
        self.checkout()
        self.webhook()
        self.subscription.refresh_from_db()
        for helper in (get_customer_portal_availability, get_payment_recovery_portal_availability):
            self.assertEqual(
                helper(
                    business=self.business, user=self.user, subscription=self.subscription
                ).reason,
                "logistics_portal_disabled",
            )

    def test_activation_requires_positive_configured_annual_prices_not_monthly(self):
        validate_offering_activation(self.plan)
        self.assertCountEqual(
            [call.args[0] for call in self.sdk.Price.retrieve.call_args_list],
            ["price_logistics_yearly_usd", "price_logistics_yearly_eur"],
        )
        with (
            override_settings(
                STRIPE_PRICE_ID_MAP=stripe_settings(logistics=False)["STRIPE_PRICE_ID_MAP"]
            ),
            self.assertRaises(StripeConfigurationError),
        ):
            validate_offering_activation(self.plan)

    def test_one_currency_offering_does_not_require_other_currency_or_monthly(self):
        mapping = dict(stripe_settings()["STRIPE_PRICE_ID_MAP"])
        del mapping[("logistics", "yearly", "usd")]
        with override_settings(STRIPE_PRICE_ID_MAP=mapping):
            validate_offering_activation(self.plan)
            self.checkout()

    def test_admin_prevents_unconfigured_activation_and_preserves_service_form(self):
        pricing = dict(self.plan.regional_prices)
        data = {
            "name": "Logistics",
            "slug": "logistics",
            "family": "LOGISTICS",
            "price_monthly": "0",
            "price_yearly": "0",
            "regional_prices": "{}",
            "is_active": "on",
        }
        form = CommercialPlanAdminForm(data=data, instance=self.plan)
        self.assertFalse(form.is_valid())
        self.assertIn("Configure a positive", str(form.errors))
        data["regional_prices"] = json.dumps(pricing)
        self.assertTrue(CommercialPlanAdminForm(data=data, instance=self.plan).is_valid())
        service = ClarivoPlan.objects.get(slug="pro")
        data.update(
            {
                "name": "Pro",
                "slug": "pro",
                "family": "SERVICE",
                "regional_prices": "{}",
                "price_yearly": "490",
                "price_monthly": "49",
            }
        )
        self.assertTrue(CommercialPlanAdminForm(data=data, instance=service).is_valid())
