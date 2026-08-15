from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from roles.models import Role, CRMResource, RolePermission
from roles.serializers import (
    RoleSerializer,
    CRMResourceSerializer,
    RolePermissionSerializer,
    RolePermissionUpdateSerializer
)

class IsAdminRole(permissions.BasePermission):
    """
    Permission class allowing access only to authenticated superusers
    or users assigned to the 'Administrator' role.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
            
        if request.user.is_superuser:
            return True
            
        try:
            profile = getattr(request.user, 'profile', None)
            if profile and profile.role:
                return profile.role.name == 'Administrator'
        except ObjectDoesNotExist:
            pass
            
        return False


class RoleViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Role management, providing CRUD endpoints, resource discovery listings,
    and granular permission matrix updates. Protected for Admins only.
    """
    queryset = Role.objects.all().order_by('name')
    serializer_class = RoleSerializer
    permission_classes = [IsAdminRole]

    def list(self, request, *args, **kwargs):
        from core.api.responses import api_success
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return api_success(data=serializer.data, message="Roles retrieved successfully")

    def retrieve(self, request, *args, **kwargs):
        from core.api.responses import api_success
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return api_success(data=serializer.data, message="Role retrieved successfully")

    def create(self, request, *args, **kwargs):
        from core.api.responses import api_success
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return api_success(data=serializer.data, message="Role created successfully", status_code=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        from core.api.responses import api_success
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        
        # Prevent renaming of system roles
        if instance.is_system:
            if request.data.get('name') and request.data.get('name') != instance.name:
                return Response(
                    {"detail": "System role names cannot be modified."},
                    status=status.HTTP_403_FORBIDDEN
                )
                
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return api_success(data=serializer.data, message="Role updated successfully")

    def destroy(self, request, *args, **kwargs):
        from core.api.responses import api_success
        instance = self.get_object()
        
        # Prevent deletion of system roles
        if instance.is_system:
            return Response(
                {"detail": "System roles cannot be deleted."},
                status=status.HTTP_403_FORBIDDEN
            )
            
        # Prevent deletion of roles assigned to active UserProfiles
        if instance.profiles.exists():
            return Response(
                {"detail": "Cannot delete a role that is still assigned to users."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        self.perform_destroy(instance)
        return api_success(message="Role deleted successfully")

    @action(detail=False, methods=['get'], url_path='resources')
    def resources(self, request):
        """Returns the list of all dynamically auto-discovered CRM resources."""
        from core.api.responses import api_success
        resources = CRMResource.objects.all().order_by('name')
        serializer = CRMResourceSerializer(resources, many=True)
        return api_success(data=serializer.data, message="Resources retrieved successfully")

    @action(detail=True, methods=['get', 'put'], url_path='permissions')
    def permissions(self, request, pk=None):
        """
        Retrieves or overwrites the permission scope configuration matrix for a role.
        Updates are processed within an atomic transaction.
        """
        from core.api.responses import api_success
        role = self.get_object()
        
        if request.method == 'GET':
            permissions_qs = RolePermission.objects.filter(role=role).select_related('resource')
            serializer = RolePermissionSerializer(permissions_qs, many=True)
            return api_success(data=serializer.data, message="Permissions retrieved successfully")
            
        elif request.method == 'PUT':
            # Support list-based payload mapping for bulk updates
            serializer = RolePermissionUpdateSerializer(data=request.data, many=True)
            serializer.is_valid(raise_exception=True)
            
            with transaction.atomic():
                # Remove existing permission associations for this role
                RolePermission.objects.filter(role=role).delete()
                
                # Perform bulk creation
                new_permissions = []
                for item in serializer.validated_data:
                    resource = CRMResource.objects.get(codename=item['resource_codename'])
                    new_permissions.append(
                        RolePermission(
                            role=role,
                            resource=resource,
                            action=item['action'],
                            scope=item['scope']
                        )
                    )
                RolePermission.objects.bulk_create(new_permissions)
                
            # Explicitly invalidate cache for all users assigned to this role (bypasses signal in bulk operations)
            from leads.models import UserProfile
            from roles.services import PermissionService
            user_ids = UserProfile.objects.filter(role=role).values_list('user_id', flat=True)
            for uid in user_ids:
                PermissionService.clear_user_permission_cache(uid)
                
            # Query updated list and return
            updated_qs = RolePermission.objects.filter(role=role).select_related('resource')
            return api_success(data=RolePermissionSerializer(updated_qs, many=True).data, message="Permissions updated successfully")
