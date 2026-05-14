from .utils import get_current_business


def current_business(request):
    return {"current_business": get_current_business(request)}
