from django.urls import path

from .views import (
    application_checkout,
    application_create,
    application_enroll,
    application_received,
    enrollment_complete,
    parcel_detail,
    parcel_list,
    parcel_register,
    parcel_update,
)

urlpatterns = [
    path("parcels/", parcel_list, name="logistics_parcel_list"),
    path("parcels/register/", parcel_register, name="logistics_parcel_register"),
    path("parcels/<int:parcel_id>/", parcel_detail, name="logistics_parcel_detail"),
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
