from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def admin_required(view_func):
    """
    Task 75: Custom decorator to restrict view access exclusively to Admin/Staff users.
    If an authenticated distributor attempts access, redirect to distributor dashboard.
    If unauthenticated, redirect to login page.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.warning(request, "Please log in to access this page.")
            return redirect("login")
        if not (request.user.is_staff or request.user.is_superuser):
            messages.error(request, "Access restricted to Administrator accounts.")
            return redirect("distributor_dashboard")
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def distributor_required(view_func):
    """
    Task 75: Custom decorator to restrict view access exclusively to Distributor users.
    If an admin accesses it, redirect to admin dashboard.
    If unauthenticated, redirect to login page.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.warning(request, "Please log in to access this page.")
            return redirect("login")
        if request.user.is_staff or request.user.is_superuser:
            return redirect("admin_dashboard")
        return view_func(request, *args, **kwargs)
    return _wrapped_view
