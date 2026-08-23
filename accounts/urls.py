from django.urls import path
from . import views


urlpatterns = [

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
        "admin-dashboard/",
        views.admin_dashboard, 
        name="admin_dashboard"
        ),

    path(
        "distributor/dashboard/",
        views.distributor_dashboard,
        name="distributor_dashboard"
    ),

    
]