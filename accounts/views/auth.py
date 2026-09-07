import json
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import (
    PasswordResetConfirmView as DjangoPasswordResetConfirmView,
    PasswordResetCompleteView as DjangoPasswordResetCompleteView
)
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.urls import reverse, reverse_lazy
from django.apps import apps
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status
from core.api.responses import api_success, api_error
from django.contrib.auth import get_user_model
from ..models import OwnerProfile, RegistrationRequest
from ..serializers import PlatformSignupSerializer

User = get_user_model()

class PlatformRegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PlatformSignupSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return api_success(
                message="Registration submitted successfully! Await admin approval.",
                status_code=status.HTTP_201_CREATED
            )
        return api_error(message="Registration validation failed.", errors=serializer.errors)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username') or request.data.get('email')
        password = request.data.get('password')

        if not username or not password:
            return api_error("Both username and password are required.", status_code=status.HTTP_400_BAD_REQUEST)

        # Normalize email/username
        username = username.strip().lower()

        # Resolve username if email is passed
        if '@' in username:
            try:
                user_obj = User.objects.filter(email=username).first()
                if user_obj:
                    username = user_obj.username
            except Exception:
                pass

        # Try to authenticate
        user = authenticate(username=username, password=password)
        if user is not None:
            login(request, user)

            return api_success(data={
                "id": user.id,
                "username": user.username,
                "email": user.email
            }, message="Login successful")

        # Check if the user is inactive and explain why (pending or rejected requests)
        try:
            user_obj = User.objects.get(username=username)
        except User.DoesNotExist:
            try:
                user_obj = User.objects.get(email=username)
            except User.DoesNotExist:
                user_obj = None

        if user_obj is not None and user_obj.check_password(password):
            if not user_obj.is_active:
                profile = getattr(user_obj, 'ownerprofile', None)
                if profile:
                    reg = RegistrationRequest.objects.filter(owner_profile=profile).first()
                    if reg:
                        if reg.status == 'pending':
                            return api_error(
                                message="Your registration is pending admin approval. Please try again later.",
                                status_code=status.HTTP_403_FORBIDDEN
                            )
                        elif reg.status == 'rejected':
                            reason = reg.rejection_reason or 'Not specified'
                            return api_error(
                                message=f"Your registration was rejected. Reason: {reason}",
                                status_code=status.HTTP_403_FORBIDDEN
                            )
                return api_error(
                    message="This account is inactive. Please contact support.",
                    status_code=status.HTTP_403_FORBIDDEN
                )

        return api_error("Invalid credentials.", status_code=status.HTTP_401_UNAUTHORIZED)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        from leads.utils.tenant import get_user_organization
        org = get_user_organization(user)
        org_data = None
        if org:
            org_data = {
                "id": org.id,
                "name": org.name,
                "logo": request.build_absolute_uri(org.logo.url) if org.logo else None,
                "is_active": org.is_active
            }

        # Resolve owner profile data with full fallback support
        profile_data = None
        owner_profile = getattr(user, 'ownerprofile', None)
        if owner_profile:
            profile_data = {
                "cnic": owner_profile.cnic,
                "phone_number": owner_profile.phone_number,
                "country": owner_profile.country,
                "address": owner_profile.address,
                "organization": org_data
            }
        else:
            profile_data = {
                "cnic": "",
                "phone_number": "",
                "country": "",
                "address": "",
                "organization": org_data
            }

        # Resolve CRM UserType & Role details from leads.UserProfile
        crm_user_type = 'USER'
        crm_role_name = None

        if user.is_superuser or user.is_staff:
            crm_user_type = 'ADMIN'
            crm_role_name = 'Administrator'

        crm_profile = getattr(user, 'profile', None)
        if crm_profile:
            crm_user_type = crm_profile.user_type
            if crm_profile.role:
                crm_role_name = crm_profile.role.name

        # Compute capabilities
        from roles.services import PermissionService
        raw_perms = PermissionService.compute_user_permissions(user)
        capabilities = {}

        if user.is_superuser or user.is_staff:
            resources = ['leads', 'companies', 'contacts', 'opportunities', 'payments', 'pipeline']
            for res in resources:
                capabilities[res] = {
                    "view": True,
                    "create": True,
                    "edit": True,
                    "delete": True,
                    "export": True,
                    "approve": True,
                    "assign": True
                }
        else:
            for resource, actions in raw_perms.items():
                res_code = resource.lower()
                capabilities[res_code] = {}
                for act, scope in actions.items():
                    act_code = act.lower()
                    capabilities[res_code][act_code] = (scope in ('ALL', 'OWN'))

        subscriptions = []
        if org and org.plan:
            has_crm = org.plan.modules.filter(code='sales-crm').exists()
            subscriptions.append({
                "id": f"sub-{org.plan.id}",
                "product": org.plan.product.name if org.plan.product else "Sales CRM",
                "hasCrm": has_crm,
                "pricingPlan": org.plan.name,
                "status": "Active",
                "startDate": org.created_at.strftime("%b %d, %Y") if org.created_at else "Jan 15, 2026",
                "renewalDate": "Jan 15, 2027"
            })

        return api_success(data={
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
            "user_type": crm_user_type,
            "role": crm_role_name,
            "permissions": capabilities,
            "profile": profile_data,
            "subscriptions": subscriptions,
            "direct_crm": user.email in ('zaidqa_test@example.com',)
        }, message="User details retrieved successfully")

    def patch(self, request):
        user = request.user
        data = request.data

        # Update core user fields
        if 'first_name' in data:
            user.first_name = (data['first_name'] or '').strip()[:150]
        if 'last_name' in data:
            user.last_name = (data['last_name'] or '').strip()[:150]
        user.save()

        # Update owner profile fields if profile exists
        try:
            profile = user.ownerprofile
            if 'phone_number' in data:
                profile.phone_number = (data['phone_number'] or '').strip()[:20]
            if 'country' in data:
                profile.country = (data['country'] or '').strip()[:100]
            if 'address' in data:
                profile.address = (data['address'] or '').strip()[:255]
            profile.save()
        except Exception:
            pass

        return self.get(request)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return api_success(message="Logout successful")


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        current_password = request.data.get("current_password")
        new_password = request.data.get("new_password")
        confirm_new_password = request.data.get("confirm_new_password")

        if not current_password or not new_password or not confirm_new_password:
            return api_error("All fields are required.", status_code=status.HTTP_400_BAD_REQUEST)

        if not user.check_password(current_password):
            return api_error("Incorrect current password.", status_code=status.HTTP_400_BAD_REQUEST)

        if new_password != confirm_new_password:
            return api_error("New passwords do not match.", status_code=status.HTTP_400_BAD_REQUEST)

        try:
            validate_password(new_password, user=user)
        except ValidationError as e:
            return api_error(message="Weak password.", errors={"new_password": e.messages})

        user.set_password(new_password)
        user.save()
        update_session_auth_hash(request, user)

        return api_success(message="Password changed successfully")


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email")
        if not email:
            return api_error("Email is required.", status_code=status.HTTP_400_BAD_REQUEST)

        # Always return success response to prevent email enumeration
        success_response = api_success(
            message="If an account exists with this email, a password reset link has been sent."
        )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return success_response

        if not user.is_active:
            return success_response

        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        # Build absolute reset path pointing to the React frontend
        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')
        reset_link = f"{frontend_url.rstrip('/')}/?view=reset-password&uid={uidb64}&token={token}"

        subject = "BMS Platform - Password Reset Request"
        message = (
            f"Hello,\n\n"
            f"You requested a password reset for your BMS account.\n"
            f"Please click the link below to set a new password:\n\n"
            f"{reset_link}\n\n"
            f"If you did not make this request, you can safely ignore this email.\n\n"
            f"Best regards,\n"
            f"BMS Platform Security Team"
        )

        send_mail(
            subject,
            message,
            None,
            [user.email],
            fail_silently=False
        )

        return success_response


class PasswordResetConfirmView(DjangoPasswordResetConfirmView):
    template_name = 'accounts/password_reset_confirm.html'
    success_url = reverse_lazy('accounts:password_reset_complete')


class PasswordResetCompleteView(DjangoPasswordResetCompleteView):
    template_name = 'accounts/password_reset_complete.html'


class PasswordResetConfirmAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        from django.utils.http import urlsafe_base64_decode
        from django.utils.encoding import force_str
        
        uidb64 = request.data.get("uidb64")
        token = request.data.get("token")
        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")

        if not uidb64 or not token or not new_password or not confirm_password:
            return api_error("All fields (uidb64, token, new_password, confirm_password) are required.", status_code=status.HTTP_400_BAD_REQUEST)

        if new_password != confirm_password:
            return api_error("Passwords do not match.", status_code=status.HTTP_400_BAD_REQUEST)

        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return api_error("Invalid reset link parameters.", status_code=status.HTTP_400_BAD_REQUEST)

        if not default_token_generator.check_token(user, token):
            return api_error("The password reset token is invalid or has expired.", status_code=status.HTTP_400_BAD_REQUEST)

        try:
            validate_password(new_password, user=user)
        except ValidationError as e:
            return api_error(message="Weak password.", errors={"new_password": e.messages})

        user.set_password(new_password)
        user.save()

        return api_success(message="Password reset successful. You can now log in with your new password.")
