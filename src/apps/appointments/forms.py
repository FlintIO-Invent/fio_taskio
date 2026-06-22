from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.businesses.models import BusinessUser
from apps.crm.models import BusinessService, Client

from .models import Appointment


class AppointmentForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = [
            "client",
            "service",
            "staff_member",
            "title",
            "start_time",
            "end_time",
            "location",
            "notes",
        ]
        widgets = {
            "client": forms.Select(attrs={"class": "form-select"}),
            "service": forms.Select(attrs={"class": "form-select"}),
            "staff_member": forms.Select(attrs={"class": "form-select"}),
            "title": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Site visit"}
            ),
            "start_time": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "end_time": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "location": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Main office or client site"}
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Internal appointment notes...",
                }
            ),
        }

    def __init__(self, *args, current_business=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_business = current_business

        if current_business is not None:
            self.instance.business = current_business

        self.fields["service"].required = False
        self.fields["staff_member"].required = False
        self.fields["start_time"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["end_time"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["client"].queryset = self._client_queryset()
        self.fields["service"].queryset = self._service_queryset()
        self.fields["staff_member"].queryset = self._staff_member_queryset()

    def _client_queryset(self):
        if self.current_business is None:
            return Client.objects.none()

        filters = Q(business=self.current_business, is_active=True)
        if self.instance.pk and self.instance.client_id:
            filters |= Q(pk=self.instance.client_id)
        return Client.objects.filter(filters).distinct().order_by("first_name", "last_name", "pk")

    def _service_queryset(self):
        if self.current_business is None:
            return BusinessService.objects.none()

        filters = Q(business=self.current_business, is_active=True)
        if self.instance.pk and self.instance.service_id:
            filters |= Q(pk=self.instance.service_id)
        return (
            BusinessService.objects.filter(filters)
            .select_related("category", "business")
            .distinct()
            .order_by("name", "pk")
        )

    def _staff_member_queryset(self):
        if self.current_business is None:
            return get_user_model().objects.none()

        filters = Q(
            business_memberships__business=self.current_business,
            business_memberships__is_active=True,
            business_memberships__business__is_active=True,
        )
        if self.instance.pk and self.instance.staff_member_id:
            filters |= Q(pk=self.instance.staff_member_id)
        return (
            get_user_model()
            .objects.filter(filters)
            .distinct()
            .order_by("first_name", "last_name", "email")
        )

    def clean(self):
        cleaned_data = super().clean()

        if self.current_business is None:
            raise forms.ValidationError("A current business is required to manage appointments.")

        client = cleaned_data.get("client")
        service = cleaned_data.get("service")
        staff_member = cleaned_data.get("staff_member")
        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")

        self.instance.business = self.current_business

        if client is not None:
            if client.business_id is None:
                self.add_error("client", "Appointments require a client from the current workspace.")
            elif client.business_id != self.current_business.id:
                self.add_error("client", "Selected client must belong to the current workspace.")

        if service is not None and service.business_id != self.current_business.id:
            self.add_error("service", "Selected service must belong to the current workspace.")

        if staff_member is not None:
            has_membership = BusinessUser.objects.filter(
                user=staff_member,
                business=self.current_business,
                is_active=True,
                business__is_active=True,
            ).exists()
            if not has_membership:
                self.add_error(
                    "staff_member",
                    "Selected staff member must belong to the current workspace.",
                )

        if start_time and end_time and end_time <= start_time:
            self.add_error("end_time", "End time must be after the start time.")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.business = self.current_business
        if commit:
            instance.save()
            self.save_m2m()
        return instance

