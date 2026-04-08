from django.contrib.auth import views as auth_views
from django.urls import path

from .views import (
    DashboardView,
    DeleteAccountView,
    EmailDiagnosticsView,
    LoginView,
    MobilePasswordResetApiView,
    MobilePushDeviceApiView,
    MobileSessionLoginView,
    MobileSignInApiView,
    MobileUsernameRecoveryApiView,
    PrivacyView,
    SignupView,
    ThrottledPasswordResetView,
    TermsView,
    TwoFactorChallengeView,
    UsernameRecoveryView,
)
from .forms import StyledPasswordResetForm


urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("dashboard/email-diagnostics/", EmailDiagnosticsView.as_view(), name="email_diagnostics"),
    path("dashboard/delete-account/", DeleteAccountView.as_view(), name="delete_account"),
    path("signup/", SignupView.as_view(), name="signup"),
    path("login/", LoginView.as_view(), name="login"),
    path("login/2fa/", TwoFactorChallengeView.as_view(), name="login_2fa"),
    path("mobile-api/login/", MobileSignInApiView.as_view(), name="mobile_login_api"),
    path("mobile-api/recover-username/", MobileUsernameRecoveryApiView.as_view(), name="mobile_recover_username_api"),
    path("mobile-api/password-reset/", MobilePasswordResetApiView.as_view(), name="mobile_password_reset_api"),
    path("mobile-api/push-devices/", MobilePushDeviceApiView.as_view(), name="mobile_push_device_api"),
    path("mobile/session-login/", MobileSessionLoginView.as_view(), name="mobile_session_login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("recover-username/", UsernameRecoveryView.as_view(), name="recover_username"),
    path(
        "password-reset/",
        ThrottledPasswordResetView.as_view(
            template_name="registration/password_reset_form.html",
            form_class=StyledPasswordResetForm,
            email_template_name="registration/password_reset_email.txt",
            html_email_template_name="registration/password_reset_email.html",
            subject_template_name="registration/password_reset_subject.txt",
        ),
        name="password_reset",
    ),
    path("password-reset/done/", auth_views.PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(template_name="registration/password_reset_confirm.html"), name="password_reset_confirm"),
    path("reset/done/", auth_views.PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"), name="password_reset_complete"),
    path("terms/", TermsView.as_view(), name="terms"),
    path("privacy/", PrivacyView.as_view(), name="privacy"),
]