from django.urls import path

from .views import (
    account_logout,
    agent_login,
    business_login,
    customer_registration,
    register_business,
    saas_profile,
)

urlpatterns = [
    path("login/", business_login, name="business_login"),
    path("logout/", account_logout, name="logout"),
    path('agent_login', agent_login, name='agent_login'),
    path('customer_registration', customer_registration, name='customer_registration'),
    path('register-business/', register_business, name='register_business'),
    path('profile', saas_profile, name='saas_profile'),
]
