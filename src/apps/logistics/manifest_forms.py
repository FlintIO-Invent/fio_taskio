"""Calendar periods for the read-only registration manifest."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django import forms
from django.utils import timezone

from .dashboard_forms import style_dashboard_fields


class ManifestPeriodForm(forms.Form):
    period = forms.ChoiceField(
        label="Registration period",
        choices=(
            ("today", "Today"),
            ("yesterday", "Yesterday"),
            ("7_days", "Last 7 days"),
            ("30_days", "Last 30 days"),
            ("custom", "Custom range"),
        ),
        initial="today",
    )
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        input_formats=["%Y-%m-%d"],
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        input_formats=["%Y-%m-%d"],
    )

    def __init__(self, *args, business, now=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.business_timezone = ZoneInfo(business.timezone)
        self.today = (now or timezone.now()).astimezone(self.business_timezone).date()
        self.fields["start_date"].initial = self.today
        self.fields["end_date"].initial = self.today
        style_dashboard_fields(self.fields)

    def clean(self):
        data = super().clean()
        period = data.get("period")
        if period == "custom":
            for field in ("start_date", "end_date"):
                if not data.get(field) and field not in self.errors:
                    self.add_error(field, "Enter a date for the custom range.")
            if self.errors:
                return data
            start, end = data["start_date"], data["end_date"]
            if end < start:
                self.add_error("end_date", "End date must be on or after start date.")
                return data
        elif period in ("today", "yesterday", "7_days", "30_days"):
            end = self.today - timedelta(days=period == "yesterday")
            start = end - timedelta(days={"7_days": 6, "30_days": 29}.get(period, 0))
        else:
            return data
        try:
            # Local calendar midnights, rather than fixed 24-hour durations, handle DST.
            data["start_at"] = datetime.combine(start, time.min, self.business_timezone).astimezone(
                UTC
            )
            data["end_at"] = datetime.combine(
                end + timedelta(days=1), time.min, self.business_timezone
            ).astimezone(UTC)
        except (OverflowError, ValueError):
            raise forms.ValidationError("Choose a date range supported by the calendar.") from None
        data["start_date"], data["end_date"] = start, end
        return data
