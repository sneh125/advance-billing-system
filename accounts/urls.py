from django.urls import path
from . import views


urlpatterns = [

    path(
        "",
        views.login_view,
        name="home"
    ),

    path(
        "login/",
        views.login_view,
        name="login"
    ),

    path(
        "logout/",
        views.logout_view,
        name="logout"
        ),

    path(
        "register/",
        views.register_view,
        name="register"
        ),


    path(
        "forgot-password/",
        views.forgot_password,
        name="forgot_password"
        ), 

    path(
        "verify-otp/",
        views.verify_otp,
        name="verify_otp"
        ),

    path(
        "resend-otp/",
        views.resend_otp,
        name="resend_otp"
    ),

    path(
        "reset-password/",
        views.reset_password,
        name="reset_password"
    ),    

    path(
        "admin-dashboard/",
        views.admin_dashboard, 
        name="admin_dashboard"
        ),

    path(
        "distributor/dashboard/",
        views.distributor_dashboard,
        name="distributor_dashboard"
    ),

    path(
        "distributor/profile/",
        views.distributor_profile,
        name="distributor_profile"
    ),

    path(
        "distributor/profile/update/",
        views.update_profile,
        name="update_profile"
    ),

    path(
        "api/admin/register/",
        views.admin_register_api,
        name="admin_register_api"
    ),

    path(
        "admin-register/",
        views.admin_register_view,
        name="admin_register"
    ),

    path(
        "register/admin/",
        views.admin_register_view,
        name="register_admin"
    ),

    # Admin Password Recovery
    path(
        "admin/forgot-password/",
        views.admin_forgot_password,
        name="admin_forgot_password"
    ),
    path(
        "admin/verify-otp/",
        views.admin_verify_otp,
        name="admin_verify_otp"
    ),
    path(
        "admin/reset-password/",
        views.admin_reset_password,
        name="admin_reset_password"
    ),

    # API endpoints for Admin Password Recovery
    path(
        "api/admin/forgot-password/",
        views.admin_forgot_password,
        name="api_admin_forgot_password"
    ),
    path(
        "api/admin/verify-otp/",
        views.admin_verify_otp,
        name="api_admin_verify_otp"
    ),
    path(
        "api/admin/reset-password/",
        views.admin_reset_password,
        name="api_admin_reset_password"
    ),

]