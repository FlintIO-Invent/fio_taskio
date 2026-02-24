from apps.accounts.models import TaskIOUser
from .forms import CustomerForm
from django.shortcuts import render
from django.shortcuts import redirect
from django.contrib.auth import authenticate, login
from loguru import logger


def agent_login(request):
    """
    Authenticate and log in an internal agent user (Employee or Management).

    This view handles authentication for users with internal roles.
    It validates submitted credentials, checks the user's role, and
    logs them into the system if authorized.

    Args:
        request (HttpRequest):
            The incoming Django HTTP request object. Supports both
            GET (renders login page) and POST (processes login form).

    Returns:
        HttpResponse:
            - Renders the login template on GET requests.
            - Renders the login template again if authentication fails.
            - (Future implementation) Redirects to the appropriate
              dashboard upon successful login.

    Notes:
        - Uses Django's `authenticate()` and `login()` functions.
        - Assumes a custom user model with a `role` field.
        - Only users with roles:
            * 'EMPLOYEE'
            * 'MANAGEMENT'
          are permitted to log in via this endpoint.
        - Logging is performed for successful and failed login attempts.
        - Redirects are currently commented out and should be implemented
          once dashboard URLs are finalized.

    Example:
        >>> response = client.post("/accounts/agent-login/", {
        ...     "email": "agent@example.com",
        ...     "password": "securepassword123"
        ... })
        >>> response.status_code
        200  # or 302 if redirect is enabled
    """
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')

        user = authenticate(request, email=email, password=password)

        if user is not None:
            if hasattr(user, 'role') and user.role == 'EMPLOYEE':
                login(request, user)
                logger.info(f"User {user.email} logged in successfully as an employee.")
                # return redirect('/dashboards/employee_dashboard')
            elif user.role == 'MANAGEMENT':
                login(request, user)
                logger.info(f"User {user.email} logged in successfully as management.")
                # return redirect('/dashboards/management_dashboard')
            else:
                logger.warning(f"User {user.email} is not an employee or management.")
        else:
            logger.warning("Invalid login credentials.")


    context = {}

    return render(request, 'accounts/forms/agent_login.html', context)



# def customer_view(request):
#     customer_list = (
#         TaskIOUser.objects
#         .only( "first_name", "last_name", "email", "created_at")     
#         .order_by("-created_at") 
#     )

#     context = {'customer_list': customer_list}

#     return render(request, 'main/customer_view.html', context)



# def customer_registration(request):
#     if request.method == 'POST':
#         customer_form = CustomerForm(request.POST)
#         if customer_form.is_valid():
#             customer_form.save()
#             return redirect('customer_view')
#     else: 
#         customer_form = CustomerForm()

#     context = {'customer_form': customer_form}
#     return render(request, 'main/customer_registration.html', context)



