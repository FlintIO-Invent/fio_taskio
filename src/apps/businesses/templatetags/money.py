from django import template

from apps.businesses.localization import format_money_for_business

register = template.Library()


@register.filter(name="money")
def money(value, business):
    return format_money_for_business(value, business)
