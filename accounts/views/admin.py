from rest_framework.views import APIView
from rest_framework.permissions import IsAdminUser
from rest_framework import status
from django.utils import timezone
from django.core.mail import send_mail
from django.db.models import Q
from django.db import transaction
from core.api.responses import api_success, api_error
from django.contrib.auth import get_user_model
from ..models import RegistrationRequest, Organization
from ..serializers import RegistrationRequestSerializer, OrganizationSerializer
from ..signals import registration_approved

User = get_user_model()

class AdminRegistrationListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        requests_qs = RegistrationRequest.objects.filter(status='pending').select_related(
            'owner_profile__user',
            'owner_profile__organization'
        ).order_by('-submitted_at')
        
        serializer = RegistrationRequestSerializer(requests_qs, many=True)
        return api_success(data=serializer.data, message="Pending registrations retrieved successfully")


class AdminRegistrationApproveView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        try:
            reg = RegistrationRequest.objects.select_related(
                'owner_profile__user',
                'owner_profile__organization'
            ).get(pk=pk)
        except RegistrationRequest.DoesNotExist:
            return api_error("Registration request not found.", status_code=status.HTTP_404_NOT_FOUND)

        if reg.status != 'pending':
            return api_error(f"Cannot approve registration in status: {reg.status}.", status_code=status.HTTP_400_BAD_REQUEST)

        # 1. Update status
        reg.status = 'approved'
        reg.reviewed_at = timezone.now()
        reg.save()

        # 2. Activate user and organization
        user = reg.owner_profile.user
        org = reg.owner_profile.organization

        user.is_active = True
        user.save()

        org.is_active = True
        org.save()

        # 3. Fire custom decoupled signal to provision workspace metrics/RBAC only after commit
        transaction.on_commit(lambda: registration_approved.send(sender=RegistrationRequest, user=user, organization=org))

        return api_success(message="Registration request approved successfully.")


class AdminRegistrationRejectView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        try:
            reg = RegistrationRequest.objects.select_related(
                'owner_profile__user',
                'owner_profile__organization'
            ).get(pk=pk)
        except RegistrationRequest.DoesNotExist:
            return api_error("Registration request not found.", status_code=status.HTTP_404_NOT_FOUND)

        if reg.status != 'pending':
            return api_error(f"Cannot reject registration in status: {reg.status}.", status_code=status.HTTP_400_BAD_REQUEST)

        reason = request.data.get('reason', '')
        if not reason:
            return api_error("Rejection reason is required.", status_code=status.HTTP_400_BAD_REQUEST)

        # 1. Update status
        reg.status = 'rejected'
        reg.rejection_reason = reason
        reg.reviewed_at = timezone.now()
        reg.save()

        # 2. Send email notification
        send_mail(
            subject="Your BMS Platform Registration was Rejected",
            message=(
                f"Hello {reg.owner_profile.user.first_name},\n\n"
                f"Your registration request for '{reg.owner_profile.organization.name}' was rejected.\n\n"
                f"Reason: {reason}\n\n"
                f"Regards,\n"
                f"BMS Platform Administration Team"
            ),
            from_email=None,
            recipient_list=[reg.owner_profile.user.email],
            fail_silently=True
        )

        return api_success(message="Registration request rejected successfully.")


class AdminUserListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        users = User.objects.all()

        search_query = request.GET.get('search')
        if search_query:
            users = users.filter(
                Q(email__icontains=search_query) |
                Q(first_name__icontains=search_query) |
                Q(last_name__icontains=search_query) |
                Q(username__icontains=search_query)
            )

        ordering = request.GET.get('ordering')
        if ordering:
            valid_fields = ['email', '-email', 'date_joined', '-date_joined', 'first_name', '-first_name', 'id', '-id']
            if ordering in valid_fields:
                users = users.order_by(ordering)
            else:
                users = users.order_by('-date_joined')
        else:
            users = users.order_by('-date_joined')

        data = []
        for user in users:
            org_name = ""
            profile = getattr(user, 'ownerprofile', None)
            if profile:
                org_name = profile.organization.name

            # Determine platform role
            if user.is_superuser:
                role = "Superuser"
            elif user.is_staff:
                role = "Staff"
            elif profile:
                role = "Owner"
            else:
                role = "User"

            # Determine registration status
            if user.is_active:
                user_status = "Active"
            else:
                if profile:
                    reg = RegistrationRequest.objects.filter(owner_profile=profile).first()
                    if reg:
                        user_status = reg.status.capitalize()
                    else:
                        user_status = "Inactive"
                else:
                    user_status = "Inactive"

            data.append({
                "id": user.id,
                "full_name": user.get_full_name() or user.username,
                "email": user.email,
                "organization": org_name,
                "role": role,
                "status": user_status,
                "created_at": user.date_joined.isoformat()
            })

        return api_success(data=data, message="Platform users retrieved successfully")


class AdminOrganizationListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        orgs = Organization.objects.all().order_by('-created_at')
        serializer = OrganizationSerializer(orgs, many=True)
        return api_success(data=serializer.data, message="Organizations retrieved successfully")
