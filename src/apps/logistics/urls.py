from django.urls import path

from . import billing_views, location_access_views, location_views, scan_views, shipment_views
from .public_tracking_views import public_tracking
from .views import (
    application_checkout,
    application_create,
    application_enroll,
    application_received,
    enrollment_complete,
    parcel_detail,
    parcel_edit,
    parcel_list,
    parcel_register,
    parcel_update,
)

urlpatterns = [
    path("locations/access/", location_access_views.location_access_settings, name="logistics_location_access"),
    path("locations/work/", location_access_views.work_location, name="logistics_work_location"),
    path("locations/", location_views.location_settings, name="logistics_location_settings"),
    path(
        "locations/<int:location_id>/edit/",
        location_views.location_settings,
        name="logistics_location_edit",
    ),
    path("parcels/scan/", scan_views.scan_parcel, name="logistics_parcel_scan"),
    path(
        "parcels/scan/<int:parcel_id>/action/",
        scan_views.scan_action,
        name="logistics_parcel_scan_action",
    ),
    path(
        "parcels/<int:parcel_id>/billing/charge/",
        billing_views.charge_create,
        name="logistics_parcel_charge",
    ),
    path(
        "parcels/<int:parcel_id>/billing/invoice/",
        billing_views.charge_invoice,
        name="logistics_parcel_invoice",
    ),
    path(
        "shipments/<int:shipment_id>/billing/charge/",
        billing_views.charge_create,
        name="logistics_shipment_charge",
    ),
    path(
        "shipments/<int:shipment_id>/billing/invoice/",
        billing_views.charge_invoice,
        name="logistics_shipment_invoice",
    ),
    path("shipments/", shipment_views.shipment_list, name="logistics_shipment_list"),
    path("shipments/create/", shipment_views.shipment_create, name="logistics_shipment_create"),
    path(
        "shipments/<int:shipment_id>/",
        shipment_views.shipment_detail,
        name="logistics_shipment_detail",
    ),
    path(
        "shipments/<int:shipment_id>/edit/",
        shipment_views.shipment_edit,
        name="logistics_shipment_edit",
    ),
    path(
        "shipments/<int:shipment_id>/assign/",
        shipment_views.shipment_assign,
        name="logistics_shipment_assign",
    ),
    path(
        "shipments/<int:shipment_id>/remove/<int:parcel_id>/",
        shipment_views.shipment_remove,
        name="logistics_shipment_remove",
    ),
    path(
        "shipments/<int:shipment_id>/status/",
        shipment_views.shipment_status,
        name="logistics_shipment_status",
    ),
    path(
        "shipments/<int:shipment_id>/manifest/",
        shipment_views.shipment_manifest,
        name="logistics_shipment_manifest",
    ),
    path("track/", public_tracking, name="logistics_public_tracking"),
    path("parcels/", parcel_list, name="logistics_parcel_list"),
    path("parcels/register/", parcel_register, name="logistics_parcel_register"),
    path("parcels/<int:parcel_id>/", parcel_detail, name="logistics_parcel_detail"),
    path("parcels/<int:parcel_id>/edit/", parcel_edit, name="logistics_parcel_edit"),
    path("parcels/<int:parcel_id>/update/", parcel_update, name="logistics_parcel_update"),
    path(
        "enroll/<uuid:application_id>/checkout/",
        application_checkout,
        name="logistics_application_checkout",
    ),
    path("enroll/complete/", enrollment_complete, name="logistics_enrollment_complete"),
    path("enroll/<str:token>/", application_enroll, name="logistics_application_enroll"),
    path("apply/", application_create, name="logistics_application_create"),
    path("apply/received/", application_received, name="logistics_application_received"),
]
