from __future__ import annotations

from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ServiceCategory(TimeStampedModel):
    class CategoryChoices(models.TextChoices):
        SEPTIC_PUMPING = "SEPTIC_PUMPING", "Septic Pumping"
        SEPTIC_INSTALLATION = "SEPTIC_INSTALLATION", "Septic Installation"
        SEPTIC_REPAIR = "SEPTIC_REPAIR", "Septic Repair"
        GREASE_TRAP_SERVICES = "GREASE_TRAP_SERVICES", "Grease Trap Services"
        UNCLOGGING_SERVICES = "UNCLOGGING_SERVICES", "Unclogging Services"
        OTHER = "OTHER", "Other"

    code = models.CharField(max_length=60, choices=CategoryChoices.choices, unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Lead(TimeStampedModel):
    class LeadType(models.TextChoices):
        REQUEST = "REQUEST", "Service Request"
        INTEREST = "INTEREST", "Interested (no request yet)"

    class Status(models.TextChoices):
        NEW = "NEW", "New"
        CONTACTED = "CONTACTED", "Contacted"
        INVOICED = "INVOICED", "Invoiced"
        CLOSED = "CLOSED", "Closed"

    class DistrictChoices(models.TextChoices):
        MIDDLE_REGION = "MIDDLEREGION", "Middle Region"
        DUTCH_QUARTER = "DUTCH_QUARTER", "Dutch Quarter"
        MADAME_ESTATE = "MADAMEESTATE", "Madame Estate"
        UNION_FARM = "UNIONFARM", "Union Farm"
        OYSTER_POND = "OYSTERPOND", "Oyster Pond"
        DEFIANCE = "DEFIANCE", "Defiance"
        SUCKERGARDEN = "SUCKERGARDEN", "Sucker Garden"
        HOPE_ESTATE = "HOPE_ESTATE", "Hope Estate"
        POINT_BLANCHE = "POINT_BLANCHE", "Point Blanche"
        GUANA_BAY = "GUANA_BAY", "Guana Bay"
        ST_PETERS = "ST_PETERS", "St. Peters"
        SOUTH_REWARD = "SOUTH_REWARD", "South Reward"
        ST_JOHN = "ST_JOHN", "St. John"
        EBENEZER = "EBENEZER", "Ebenezer"
        SAUNDERS = "SAUNDERS", "Saunders"
        MARYS_FANCY = "MARYS_FANCY", "Mary's Fancy"
        PHILIPSBURG = "PHILIPSBURG", "Philipsburg"
        BELAIR = "BELAIR", "Belair"
        INDIGO_BAY = "INDIGO_BAY", "Indigo Bay"
        COLE_BAY = "COLE_BAY", "Cole Bay"
        PELICAN_KEY = "PELICAN_KEY", "Pelican Key"
        SIMPSON_BAY = "SIMPSON_BAY", "Simpson Bay"
        MAHO = "MAHO", "Maho"

    lead_type           = models.CharField(max_length=20, choices=LeadType.choices, db_index=True)
    status              = models.CharField(max_length=20,choices=Status.choices,default=Status.NEW, db_index=True)
    category            = models.ForeignKey(ServiceCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="leads",)
    first_name          = models.CharField(max_length=80)
    last_name           = models.CharField(max_length=80, blank=True)
    email               = models.EmailField()
    phone               = models.CharField(max_length=40, blank=True)
    company_name        = models.CharField(max_length=120, blank=False)
    message             = models.TextField(blank=True)
    street_address      = models.CharField(max_length=255, blank=True)
    district            = models.CharField( max_length=100, choices=DistrictChoices.choices,  blank=True)
    country             = models.CharField(max_length=100, blank=True, default="Sint Maarten")
    postal_code         = models.CharField(max_length=20, blank=True, default="N/A")
    notes               = models.TextField(blank=True)
    consent_to_contact  = models.BooleanField(default=True)
    is_active           = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        return name or self.email


class Client(TimeStampedModel):

    class DistrictChoices(models.TextChoices):
        MIDDLE_REGION = "MIDDLEREGION", "Middle Region"
        DUTCH_QUARTER = "DUTCH_QUARTER", "Dutch Quarter"
        MADAME_ESTATE = "MADAMEESTATE", "Madame Estate"
        UNION_FARM = "UNIONFARM", "Union Farm"
        OYSTER_POND = "OYSTERPOND", "Oyster Pond"
        DEFIANCE = "DEFIANCE", "Defiance"
        SUCKERGARDEN = "SUCKERGARDEN", "Sucker Garden"
        HOPE_ESTATE = "HOPE_ESTATE", "Hope Estate"
        POINT_BLANCHE = "POINT_BLANCHE", "Point Blanche"
        GUANA_BAY = "GUANA_BAY", "Guana Bay"
        ST_PETERS = "ST_PETERS", "St. Peters"
        SOUTH_REWARD = "SOUTH_REWARD", "South Reward"
        ST_JOHN = "ST_JOHN", "St. John"
        EBENEZER = "EBENEZER", "Ebenezer"
        SAUNDERS = "SAUNDERS", "Saunders"
        MARYS_FANCY = "MARYS_FANCY", "Mary's Fancy"
        PHILIPSBURG = "PHILIPSBURG", "Philipsburg"
        BELAIR = "BELAIR", "Belair"
        INDIGO_BAY = "INDIGO_BAY", "Indigo Bay"
        COLE_BAY = "COLE_BAY", "Cole Bay"
        PELICAN_KEY = "PELICAN_KEY", "Pelican Key"
        SIMPSON_BAY = "SIMPSON_BAY", "Simpson Bay"
        MAHO = "MAHO", "Maho"

    first_name          = models.CharField(max_length=80)
    last_name           = models.CharField(max_length=80, blank=True)
    email               = models.EmailField()
    phone               = models.CharField(max_length=40, blank=True)
    company_name        = models.CharField(max_length=120, blank=True)
    message             = models.TextField(blank=True)
    street_address      = models.CharField(max_length=255, blank=True)
    district            = models.CharField( max_length=100, choices=DistrictChoices.choices,  blank=True)
    state               = models.CharField(max_length=100, blank=True, default="Sint Maarten")
    postal_code         = models.CharField(max_length=20, blank=True, default="00000")
    notes               = models.TextField(blank=True)
    consent_to_contact  = models.BooleanField(default=True)
    is_active           = models.BooleanField(default=True)
   

    class Meta:
        ordering = ["first_name", "last_name"]

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class ActivityLog(TimeStampedModel):
    class ActionType(models.TextChoices):
        EMAIL_SENT = "EMAIL_SENT", "Email Sent"
        INVOICE_CREATED = "INVOICE_CREATED", "Invoice Created"
        STATUS_CHANGED = "STATUS_CHANGED", "Status Changed"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="activity_logs"
    )
    lead = models.ForeignKey(Lead, on_delete=models.SET_NULL, null=True, blank=True, related_name="activity_logs")
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="activity_logs")

    action_type = models.CharField(max_length=40, choices=ActionType.choices)
    summary = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.action_type} {self.created_at:%Y-%m-%d %H:%M}"