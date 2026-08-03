from django.test import TestCase
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from roles.models import Role, CRMResource, RolePermission
from roles.services import PermissionService
from roles.permissions import get_scoped_queryset
from leads.models import UserProfile

User = get_user_model()

class RoleModelTests(TestCase):
    
    def test_default_roles_created_by_migration(self):
        """Verify standard system roles were created and marked as system roles."""
        admin_role = Role.objects.filter(name="Administrator").first()
        salesperson_role = Role.objects.filter(name="Salesperson").first()
        manager_role = Role.objects.filter(name="Manager").first()
        
        self.assertIsNotNone(admin_role)
        self.assertIsNotNone(salesperson_role)
        self.assertIsNotNone(manager_role)
        self.assertTrue(admin_role.is_system)
        self.assertTrue(salesperson_role.is_system)
        self.assertTrue(manager_role.is_system)

    def test_user_creation_auto_assigns_role(self):
        """Verify creating a new User automatically creates UserProfile with correct Role."""
        # Standard user
        std_user = User.objects.create_user(username="test_sales", password="password123")
        self.assertTrue(hasattr(std_user, 'profile'))
        self.assertEqual(std_user.profile.user_type, 'USER')
        self.assertEqual(std_user.profile.role.name, 'Salesperson')

        # Superuser
        admin_user = User.objects.create_superuser(username="test_admin", password="password123")
        self.assertTrue(hasattr(admin_user, 'profile'))
        self.assertEqual(admin_user.profile.user_type, 'ADMIN')
        self.assertEqual(admin_user.profile.role.name, 'Administrator')

    def test_custom_role_crud(self):
        """Verify we can create custom non-system roles."""
        custom_role = Role.objects.create(
            name="Junior Sales",
            description="Limited sales agent access",
            is_system=False
        )
        self.assertEqual(custom_role.name, "Junior Sales")
        self.assertFalse(custom_role.is_system)

    def test_role_permission_relation(self):
        """Verify we can map CRMResources and RolePermissions to Roles."""
        role = Role.objects.create(name="Support Agent")
        resource = CRMResource.objects.create(codename="leads", name="Leads")
        
        permission = RolePermission.objects.create(
            role=role,
            resource=resource,
            action="VIEW",
            scope="OWN"
        )
        
        self.assertEqual(permission.role, role)
        self.assertEqual(permission.resource, resource)
        self.assertEqual(permission.action, "VIEW")
        self.assertEqual(permission.scope, "OWN")
        
        # Test unique together constraint
        with self.assertRaises(IntegrityError):
            RolePermission.objects.create(
                role=role,
                resource=resource,
                action="VIEW",
                scope="ALL"
            )

    def test_discovery_of_new_custom_crm_app(self):
        """Verify that a newly added custom CRM app config is auto-discovered."""
        from django.apps import apps
        from django.apps.config import AppConfig
        from roles.registry import CRMRegistry

        class DummyCRMConfig(AppConfig):
            name = 'dummy_crm'
            label = 'dummy_crm'
            verbose_name = 'Dummy CRM App'

        # Safely inject dummy config into Django apps map
        original_configs = apps.app_configs.copy()
        try:
            apps.app_configs['dummy_crm'] = DummyCRMConfig('dummy_crm', __import__('roles'))
            # Execute discovery
            CRMRegistry.discover_resources()
            
            # Assert dummy crm registered correctly
            resource = CRMResource.objects.filter(codename='dummy_crm').first()
            self.assertIsNotNone(resource)
            self.assertEqual(resource.name, 'Dummy CRM App')
        finally:
            apps.app_configs = original_configs

    def test_exclusion_of_system_apps(self):
        """Verify that Django system apps and middleware libraries are excluded."""
        from roles.registry import CRMRegistry
        CRMRegistry.discover_resources()
        
        system_codenames = ['admin', 'auth', 'contenttypes', 'sessions', 'messages', 'staticfiles', 'corsheaders', 'rest_framework', 'roles']
        for codename in system_codenames:
            exists = CRMResource.objects.filter(codename=codename).exists()
            self.assertFalse(exists, f"System app codename '{codename}' should not be registered as a CRMResource.")

    def test_idempotency_prevents_duplicates(self):
        """Verify that running discovery multiple times does not insert duplicate CRMResource entries."""
        from roles.registry import CRMRegistry
        
        # Initial run
        CRMRegistry.discover_resources()
        count_1 = CRMResource.objects.count()
        
        # Subsequent runs
        CRMRegistry.discover_resources()
        CRMRegistry.discover_resources()
        count_2 = CRMResource.objects.count()
        
        self.assertEqual(count_1, count_2)


class PermissionEngineTests(TestCase):

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        
        # Setup system roles
        self.admin_role = Role.objects.create(name="Admin Role", is_system=False)
        self.sales_role = Role.objects.create(name="Sales Role", is_system=False)
        
        # Setup resources
        self.leads_res = CRMResource.objects.create(codename="leads", name="Leads")
        
        # Setup permissions: admin has ALL view, sales has OWN view
        RolePermission.objects.create(role=self.admin_role, resource=self.leads_res, action="VIEW", scope="ALL")
        RolePermission.objects.create(role=self.sales_role, resource=self.leads_res, action="VIEW", scope="OWN")
        
        # Setup users
        self.admin_user = User.objects.create_user(username="admin_u", password="password")
        self.sales_user = User.objects.create_user(username="sales_u", password="password")
        
        # Map roles
        self.admin_user.profile.role = self.admin_role
        self.admin_user.profile.save()
        self.sales_user.profile.role = self.sales_role
        self.sales_user.profile.save()

    def test_permission_scope_resolution(self):
        """Verify PermissionService resolves scope based on role assignments."""
        scope_admin = PermissionService.get_permission_scope(self.admin_user, "leads", "VIEW")
        scope_sales = PermissionService.get_permission_scope(self.sales_user, "leads", "VIEW")
        scope_none = PermissionService.get_permission_scope(self.sales_user, "leads", "CREATE")
        
        self.assertEqual(scope_admin, "ALL")
        self.assertEqual(scope_sales, "OWN")
        self.assertEqual(scope_none, "NONE")

    def test_permission_caching(self):
        """Verify that resolved permissions are cached correctly (cache hits)."""
        from django.core.cache import cache
        cache_key = PermissionService.get_permission_cache_key(self.sales_user.id)
        self.assertIsNone(cache.get(cache_key))
        
        # Trigger resolution to populate cache
        scope = PermissionService.get_permission_scope(self.sales_user, "leads", "VIEW")
        self.assertEqual(scope, "OWN")
        
        # Check cache is now populated
        cached_data = cache.get(cache_key)
        self.assertIsNotNone(cached_data)
        self.assertEqual(cached_data["leads"]["VIEW"], "OWN")

    def test_cache_invalidation_on_profile_change(self):
        """Verify that modifying user profile invalidates permissions cache."""
        from django.core.cache import cache
        # Populate cache
        PermissionService.get_permission_scope(self.sales_user, "leads", "VIEW")
        cache_key = PermissionService.get_permission_cache_key(self.sales_user.id)
        self.assertIsNotNone(cache.get(cache_key))
        
        # Modify UserProfile (change role to admin_role)
        self.sales_user.profile.role = self.admin_role
        self.sales_user.profile.save()
        
        # Cache should be invalidated (None)
        self.assertIsNone(cache.get(cache_key))

    def test_cache_invalidation_on_permission_change(self):
        """Verify that altering RolePermission invalidates cache for all users assigned."""
        from django.core.cache import cache
        # Populate cache
        PermissionService.get_permission_scope(self.sales_user, "leads", "VIEW")
        cache_key = PermissionService.get_permission_cache_key(self.sales_user.id)
        self.assertIsNotNone(cache.get(cache_key))
        
        # Modify permission (change sales scope to ALL)
        perm = RolePermission.objects.get(role=self.sales_role, resource=self.leads_res, action="VIEW")
        perm.scope = "ALL"
        perm.save()
        
        # Cache should be invalidated
        self.assertIsNone(cache.get(cache_key))
        
        # Resolve again and verify updated scope
        new_scope = PermissionService.get_permission_scope(self.sales_user, "leads", "VIEW")
        self.assertEqual(new_scope, "ALL")

    def test_permission_cache_hits_and_misses(self):
        """Verify cache miss triggers queries, cache hit does not, and invalidation triggers query again."""
        # 1. First lookup: Cache miss, should execute queries
        with self.assertNumQueries(1):
            scope = PermissionService.get_permission_scope(self.sales_user, "leads", "VIEW")
            self.assertEqual(scope, "OWN")

        # 2. Second lookup: Cache hit, should execute zero queries
        with self.assertNumQueries(0):
            scope = PermissionService.get_permission_scope(self.sales_user, "leads", "VIEW")
            self.assertEqual(scope, "OWN")

        # 3. Invalidate cache by updating role permission
        perm = RolePermission.objects.get(role=self.sales_role, resource=self.leads_res, action="VIEW")
        perm.scope = "ALL"
        perm.save()

        # 4. Third lookup: Cache miss after invalidation, should execute queries again
        with self.assertNumQueries(1):
            scope = PermissionService.get_permission_scope(self.sales_user, "leads", "VIEW")
            self.assertEqual(scope, "ALL")

    def test_queryset_scoping_filters_properly(self):
        """Verify get_scoped_queryset filters records according to the user's scope."""
        from leads.models import Lead
        
        # Create some leads assigned to different people
        lead_sales = Lead.objects.create(
            full_name="Sales Lead",
            assigned_salesperson=self.sales_user,
            status="NEW"
        )
        Lead.objects.create(
            full_name="Other Lead",
            assigned_salesperson=self.admin_user,
            status="NEW"
        )
        
        # Admin user (ALL scope) should see both
        admin_qs = get_scoped_queryset(Lead.objects.all(), self.admin_user, "leads", owner_field="assigned_salesperson")
        self.assertEqual(admin_qs.count(), 2)
        
        # Sales user (OWN scope) should only see their lead
        sales_qs = get_scoped_queryset(Lead.objects.all(), self.sales_user, "leads", owner_field="assigned_salesperson")
        self.assertEqual(sales_qs.count(), 1)
        self.assertEqual(sales_qs.first(), lead_sales)


from rest_framework.test import APITestCase
from django.urls import reverse
from rest_framework import status

class RoleAPITests(APITestCase):

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        
        # Populate CRMResource domain
        self.leads_res, _ = CRMResource.objects.get_or_create(codename="leads", defaults={"name": "Leads"})
        
        # Resolve or create standard system roles
        self.admin_role, _ = Role.objects.get_or_create(
            name="Administrator",
            defaults={"is_system": True, "description": "System Administrator with full capabilities"}
        )
        self.sales_role, _ = Role.objects.get_or_create(
            name="Salesperson",
            defaults={"is_system": True, "description": "Sales agent scoped to assigned pipeline data"}
        )
        self.custom_role, _ = Role.objects.get_or_create(
            name="Custom Agent",
            defaults={"is_system": False, "description": "Custom agent role"}
        )
        
        # Create users
        self.admin_user = User.objects.create_user(username="admin_api", password="password")
        self.sales_user = User.objects.create_user(username="sales_api", password="password")
        
        # Assign roles
        self.admin_user.profile.role = self.admin_role
        self.admin_user.profile.save()
        self.sales_user.profile.role = self.sales_role
        self.sales_user.profile.save()

    def test_list_roles_requires_admin(self):
        """Verify list endpoint is restricted to administrators."""
        url = reverse('role-list')
        
        # Unauthenticated
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Salesperson (Non-admin)
        self.client.force_authenticate(user=self.sales_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Administrator
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 4)

    def test_create_role(self):
        """Verify administrator can create a new custom role."""
        url = reverse('role-list')
        data = {"name": "Support Agent", "description": "Support role"}
        
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Support Agent")
        self.assertFalse(response.data["is_system"])

    def test_create_role_duplicate_name_fails(self):
        """Verify name validation prevents duplicate role creation."""
        url = reverse('role-list')
        data = {"name": "Custom Agent", "description": "Duplicate agent"}
        
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data["errors"])

    def test_update_system_role_rename_fails(self):
        """Verify system roles cannot be renamed."""
        url = reverse('role-detail', kwargs={'pk': self.admin_role.pk})
        data = {"name": "Super Administrator"}
        
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.put(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_system_role_fails(self):
        """Verify system roles cannot be deleted."""
        url = reverse('role-detail', kwargs={'pk': self.admin_role.pk})
        
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_assigned_role_fails(self):
        """Verify that a role assigned to users cannot be deleted."""
        # Create user profile assigned to the custom role
        some_user = User.objects.create_user(username="temp_user", password="password")
        some_user.profile.role = self.custom_role
        some_user.profile.save()

        url = reverse('role-detail', kwargs={'pk': self.custom_role.pk})
        
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)

    def test_delete_unassigned_custom_role_succeeds(self):
        """Verify custom role without user assignments can be deleted."""
        url = reverse('role-detail', kwargs={'pk': self.custom_role.pk})
        
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_resources_list(self):
        """Verify list of auto-discovered resource codenames is returned."""
        url = reverse('role-resources')
        
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["codename"], "leads")

    def test_get_and_update_permissions_matrix(self):
        """Verify matrix retrieves and atomic overwrites work."""
        url = reverse('role-permissions', kwargs={'pk': self.custom_role.pk})
        
        self.client.force_authenticate(user=self.admin_user)
        
        # 1. GET returns empty initial matrix
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)
        
        # 2. PUT updates matrix
        payload = [
            {"resource_codename": "leads", "action": "VIEW", "scope": "OWN"},
            {"resource_codename": "leads", "action": "CREATE", "scope": "ALL"}
        ]
        response = self.client.put(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        
        # 3. PUT with invalid resource code returns 400
        payload_invalid = [
            {"resource_codename": "nonexistent_app", "action": "VIEW", "scope": "OWN"}
        ]
        response = self.client.put(url, payload_invalid, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_permission_update_invalidates_cache(self):
        """Verify permission updates invalidate user cache."""
        from django.core.cache import cache
        
        # Populate cache
        self.client.force_authenticate(user=self.sales_user)
        PermissionService.get_permission_scope(self.sales_user, "leads", "VIEW")
        cache_key = PermissionService.get_permission_cache_key(self.sales_user.id)
        self.assertIsNotNone(cache.get(cache_key))
        
        # Administrator updates sales role permissions matrix via API
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('role-permissions', kwargs={'pk': self.sales_role.pk})
        payload = [{"resource_codename": "leads", "action": "VIEW", "scope": "ALL"}]
        
        response = self.client.put(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # User cache must be cleared
        self.assertIsNone(cache.get(cache_key))




