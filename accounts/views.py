from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required


def login_view(request):

    # Already logged-in user
    if request.user.is_authenticated:

        if request.user.is_staff:
            return redirect("admin_dashboard")

        return redirect("distributor_dashboard")

    if request.method == "POST":

        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        if not username or not password:

            return render(
                request,
                "accounts/login.html",
                {
                    "error": "Please enter username and password."
                }
            )

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user is not None:

            login(request, user)

            if user.is_staff:
                return redirect("admin_dashboard")

            return redirect("distributor_dashboard")

        return render(
            request,
            "accounts/login.html",
            {
                "error": "Invalid username or password."
            }
        )

    return render(request, "accounts/login.html")


@login_required
def logout_view(request):

    logout(request)

    return redirect("login")


@login_required
def admin_dashboard(request):

    if not request.user.is_staff:
        return redirect("distributor_dashboard")

    return render(
        request,
        "admin/dashboard.html"
    )


@login_required
def distributor_dashboard(request):

    if request.user.is_staff:
        return redirect("admin_dashboard")

    return render(
        request,
        "distributor/dashboard.html"
    )