"""Additive Services-only fixtures for freshly owned UI preview clusters."""

import os
from datetime import datetime, time, timedelta
from unittest.mock import patch


def seed(session):
    # Refuse standalone/ordinary settings before importing any application models.
    if (
        os.environ.get("DJANGO_SETTINGS_MODULE") != "ui_preview.settings"
        or os.environ.get("MOTIONMATE_PREVIEW_PHASE") != "setup"
    ):
        raise RuntimeError("Appointment fixtures require the verified preview setup phase.")
    from ui_preview.core import load_session, verify_database

    root, owned = load_session(os.environ["MOTIONMATE_PREVIEW_ROOT"])
    if owned["id"] != session["id"]:
        raise RuntimeError("Fixture session identity differs.")
    verify_database(root, owned, os.environ["MOTIONMATE_PREVIEW_SIDE"])
    from apps.accounts.models import TaskIOUser
    from apps.appointments.models import Appointment
    from apps.businesses.models import (
        Business,
        BusinessBookingSettings,
        BusinessSubscription,
        BusinessUser,
        ClarivoPlan,
        UserOnboardingState,
        WeeklyAvailability,
    )
    from apps.crm.models import BusinessService, Client, Lead

    with patch("django.utils.timezone.now", return_value=datetime.fromisoformat(session["clock"])):
        business = Business.objects.create(
            name="Harbour Services",
            slug="preview-appointments",
            timezone="America/Lower_Princes",
            country="Sint Maarten",
            currency="USD",
        )
        BusinessSubscription.objects.create(
            business=business,
            plan=ClarivoPlan.objects.get(slug="preview-services"),
            status="active",
            payment_provider="local",
        )
        accounts = []
        for role in ("owner", "admin", "staff", "accountant", "viewer"):
            email = f"bookings.{role}@preview.test"
            user = TaskIOUser.objects.create_user(
                email=email,
                password=session["password"],
                first_name="Alex",
                last_name=role.title(),
            )
            BusinessUser.objects.create(business=business, user=user, role=role)
            if role in {"owner", "admin"}:
                UserOnboardingState.objects.create(
                    business=business, user=user, completed_welcome=True
                )
            accounts.append({"email": email, "role": role})
        service = BusinessService.objects.create(
            business=business,
            name="Property maintenance consultation",
            unit_price="125.00",
            is_bookable_online=True,
            default_duration_minutes=60,
        )
        BusinessBookingSettings.objects.create(
            business=business,
            booking_enabled=True,
            minimum_notice_hours=0,
        )
        for day in range(7):
            WeeklyAvailability.objects.create(
                business=business,
                day_of_week=day,
                start_time=time(8),
                end_time=time(18),
                is_active=True,
            )
        client = Client.objects.create(
            business=business,
            first_name="Jamie",
            last_name="Rivera",
            company_name="Harbour View Apartments",
            email="jamie@appointments.preview.test",
            phone="+17215550190",
            street_address="12 Harbour Road",
            country="Sint Maarten",
            client_status="ACTIVE",
        )
        start = (datetime.fromisoformat(session["clock"]) + timedelta(days=2)).replace(
            hour=14, minute=0, second=0, microsecond=0
        )
        requests = []
        for label in ("ready", "missing", "linked"):
            lead = Lead.objects.create(
                business=business,
                lead_type="REQUEST",
                status="NEW",
                first_name="Taylor",
                last_name=label.title(),
                email=client.email if label != "missing" else "missing@appointments.preview.test",
                phone="+17215550191",
                company_name="Island Property Services",
                requested_service=service,
                request_source="public_booking" if label == "ready" else "staff",
                message="Please contact me to arrange maintenance.",
            )
            requests.append(lead)
        appointments = []
        staff = TaskIOUser.objects.get(email="bookings.staff@preview.test")
        for i, status in enumerate(("scheduled", "completed", "cancelled", "no_show")):
            item = Appointment.objects.create(
                business=business,
                client=client,
                service=service,
                staff_member=staff,
                title="Property maintenance consultation" if i == 0 else f"Site visit · {status}",
                start_time=start + timedelta(days=i),
                end_time=start + timedelta(days=i, hours=1),
                location="12 Harbour Road, Sint Maarten",
                notes="Use the courtyard entrance.",
                status=status,
                source_lead=requests[2] if i == 0 else None,
            )
            appointments.append(item)
        return {
            "accounts": accounts,
            "business_id": business.pk,
            "slug": business.slug,
            "appointments": [
                {
                    "id": a.pk,
                    "status": a.status,
                    "source_lead_id": a.source_lead_id,
                    "start": a.start_time.isoformat(),
                }
                for a in appointments
            ],
            "requests": {
                label: lead.pk
                for label, lead in zip(("ready", "missing", "linked"), requests, strict=True)
            },
        }
