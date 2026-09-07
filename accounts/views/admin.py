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


from rest_framework.permissions import IsAuthenticated

class AdminUserListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from leads.utils.tenant import get_user_organization
        is_global_admin = request.user.is_superuser or request.user.is_staff
        crm_profile = getattr(request.user, 'profile', None)
        is_crm_admin = crm_profile and crm_profile.user_type == 'ADMIN'

        # Resolve target organization
        org = None
        if is_global_admin:
            org_id = request.GET.get('organization_id')
            if org_id:
                org = Organization.objects.filter(id=org_id).first()
            else:
                org = get_user_organization(request.user)
        else:
            org = get_user_organization(request.user)

        if org:
            # CRM scope: only users within the resolved organization
            users = User.objects.filter(
                Q(profile__organization=org) |
                Q(ownerprofile__organization=org)
            ).distinct()
        else:
            users = User.objects.none()

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
            else:
                crm_profile = getattr(user, 'profile', None)
                if crm_profile and crm_profile.organization:
                    org_name = crm_profile.organization.name

            # Determine role name and role ID
            role = "User"
            role_id = None
            crm_profile = getattr(user, 'profile', None)
            if crm_profile and crm_profile.role:
                role = crm_profile.role.name
                role_id = crm_profile.role.id
            elif user.is_superuser:
                role = "Superuser"
            elif user.is_staff:
                role = "Staff"
            elif profile:
                role = "Owner"

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
                "role_id": role_id,
                "status": user_status,
                "created_at": user.date_joined.isoformat()
            })

        return api_success(data=data, message="Platform users retrieved successfully")

    def patch(self, request):
        user = request.user
        
        # Verify permissions
        is_global_admin = user.is_superuser or user.is_staff
        crm_profile = getattr(user, 'profile', None)
        is_crm_admin = crm_profile and crm_profile.user_type == 'ADMIN'
        
        if not (is_global_admin or is_crm_admin):
            return api_error("You do not have permission to manage users.", status_code=status.HTTP_403_FORBIDDEN)
            
        target_user_id = request.data.get('user_id')
        target_role_id = request.data.get('role_id')
        
        if not target_user_id:
            return api_error("User ID is required.", status_code=status.HTTP_400_BAD_REQUEST)
            
        try:
            target_user = User.objects.get(pk=target_user_id)
        except User.DoesNotExist:
            return api_error("User not found.", status_code=status.HTTP_404_NOT_FOUND)
            
        # Verify organization boundaries
        from leads.utils.tenant import get_user_organization
        if not is_global_admin:
            org = get_user_organization(user)
            target_org = get_user_organization(target_user)
            if not org or org != target_org:
                return api_error("Target user does not belong to your organization.", status_code=status.HTTP_403_FORBIDDEN)
                
        # Resolve new role
        from roles.models import Role
        if target_role_id:
            try:
                new_role = Role.objects.get(pk=target_role_id)
            except Role.DoesNotExist:
                return api_error("Role not found.", status_code=status.HTTP_404_NOT_FOUND)
        else:
            new_role = None
            
        # Update role
        from leads.models import UserProfile
        target_profile, created = UserProfile.objects.get_or_create(user=target_user)
        target_profile.role = new_role
        
        # If the new role name is 'Administrator', update user_type to 'ADMIN', else update to 'USER'
        if new_role and new_role.name == 'Administrator':
            target_profile.user_type = 'ADMIN'
        else:
            target_profile.user_type = 'USER'
            
        target_profile.save()
        
        # Clear target user's permission cache
        from roles.services import PermissionService
        PermissionService.clear_user_permission_cache(target_user.id)
        
        return api_success(message="User role updated successfully.")

    def post(self, request):
        user = request.user
        
        # Verify permissions
        is_global_admin = user.is_superuser or user.is_staff
        crm_profile = getattr(user, 'profile', None)
        is_crm_admin = crm_profile and crm_profile.user_type == 'ADMIN'
        
        if not (is_global_admin or is_crm_admin):
            return api_error("You do not have permission to manage users.", status_code=status.HTTP_403_FORBIDDEN)
            
        email = request.data.get('email')
        password = request.data.get('password')
        first_name = request.data.get('first_name', '')
        last_name = request.data.get('last_name', '')
        target_role_id = request.data.get('role_id')
        
        if not email or not password:
            return api_error("Email and password are required.", status_code=status.HTTP_400_BAD_REQUEST)
            
        email = email.strip().lower()
        
        # Check if user already exists
        if User.objects.filter(Q(username__iexact=email) | Q(email__iexact=email)).exists():
            return api_error("A user with this email address already exists.", status_code=status.HTTP_400_BAD_REQUEST)
            
        # Resolve organization from administrator profile (strictly backend-derived)
        from leads.utils.tenant import get_user_organization
        org = get_user_organization(user)
        if not org and not is_global_admin:
            return api_error("Organization could not be resolved.", status_code=status.HTTP_400_BAD_REQUEST)
            
        # Resolve and validate role
        from roles.models import Role
        new_role = None
        if target_role_id:
            try:
                new_role = Role.objects.get(pk=target_role_id)
            except Role.DoesNotExist:
                return api_error("Role not found.", status_code=status.HTTP_404_NOT_FOUND)
            
            # Future-proof organization check if roles get organization fields
            if hasattr(new_role, 'organization') and new_role.organization and new_role.organization != org:
                return api_error("Selected role is not allowed for this organization.", status_code=status.HTTP_400_BAD_REQUEST)
                
        # Create user
        with transaction.atomic():
            new_user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                is_active=True
            )
            
            # Update the UserProfile that is automatically created by post_save user signal
            from leads.models import UserProfile
            profile, created = UserProfile.objects.get_or_create(user=new_user)
            profile.organization = org
            profile.role = new_role
            profile.user_type = 'ADMIN' if (new_role and new_role.name == 'Administrator') else 'USER'
            profile.save()
            
        # Clear permissions cache
        from roles.services import PermissionService
        PermissionService.clear_user_permission_cache(new_user.id)
        
        return api_success(message="Employee created successfully.")


class AdminOrganizationListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        orgs = Organization.objects.all().order_by('-created_at')
        serializer = OrganizationSerializer(orgs, many=True)
        return api_success(data=serializer.data, message="Organizations retrieved successfully")
