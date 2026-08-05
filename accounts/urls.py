from django.urls import path
from .views.auth import (
    PlatformRegisterView, LoginView, MeView, LogoutView, 
    ChangePasswordView, ForgotPasswordView, 
    PasswordResetConfirmView, PasswordResetCompleteView
)
from .views.admin import (
    AdminRegistrationListView, AdminRegistrationApproveView, 
    AdminRegistrationRejectView, AdminUserListView, 
    AdminOrganizationListView
)

app_name = 'accounts'

urlpatterns = [
    # Platform Auth & Registrations
    path('register/', PlatformRegisterView.as_view(), name='api_register'),
    path('login/', LoginView.as_view(), name='api_login'),
    path('me/', MeView.as_view(), name='api_me'),
    path('logout/', LogoutView.as_view(), name='api_logout'),
    path('auth/change-password/', ChangePasswordView.as_view(), name='api_change_password'),
    path('auth/forgot-password/', ForgotPasswordView.as_view(), name='api_forgot_password'),
    path('auth/reset-password/<uidb64>/<token>/', PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('auth/reset-password-complete/', PasswordResetCompleteView.as_view(), name='password_reset_complete'),

    # Platform Administration
    path('admin/registrations/', AdminRegistrationListView.as_view(), name='api_admin_registrations'),
    path('admin/registrations/<int:pk>/approve/', AdminRegistrationApproveView.as_view(), name='api_admin_approve'),
    path('admin/registrations/<int:pk>/reject/', AdminRegistrationRejectView.as_view(), name='api_admin_reject'),
    path('admin/users/', AdminUserListView.as_view(), name='api_admin_users'),
    path('admin/organizations/', AdminOrganizationListView.as_view(), name='api_admin_organizations'),
]
