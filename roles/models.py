from django.db import models

class Role(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class CRMResource(models.Model):
    codename = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=150)

    def __str__(self):
        return f"{self.name} ({self.codename})"

class RolePermission(models.Model):
    ACTION_CHOICES = [
        ('VIEW', 'View'),
        ('CREATE', 'Create'),
        ('EDIT', 'Edit'),
        ('DELETE', 'Delete'),
        ('EXPORT', 'Export'),
        ('APPROVE', 'Approve'),
        ('ASSIGN', 'Assign'),
    ]
    SCOPE_CHOICES = [
        ('ALL', 'All'),
        ('OWN', 'Own'),
        ('NONE', 'None'),
    ]
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='permissions')
    resource = models.ForeignKey(CRMResource, on_delete=models.CASCADE, related_name='permissions')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    scope = models.CharField(max_length=10, choices=SCOPE_CHOICES, default='NONE')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["role", "resource", "action"],
                name="unique_role_permission"
            )
        ]

    def __str__(self):
        return f"{self.role.name} - {self.resource.codename} - {self.action}: {self.scope}"

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

@receiver(post_save, sender=Role)
@receiver(post_delete, sender=Role)
def invalidate_role_cache(sender, instance, **kwargs):
    """Invalidates permission cache for all users assigned to the affected role."""
    from leads.models import UserProfile
    from roles.services import PermissionService
    try:
        user_ids = UserProfile.objects.filter(role=instance).values_list('user_id', flat=True)
        for uid in user_ids:
            PermissionService.clear_user_permission_cache(uid)
    except Exception:
        pass

@receiver(post_save, sender=RolePermission)
@receiver(post_delete, sender=RolePermission)
def invalidate_permission_cache(sender, instance, **kwargs):
    """Invalidates permission cache for all users assigned to the permission's role."""
    from leads.models import UserProfile
    from roles.services import PermissionService
    try:
        user_ids = UserProfile.objects.filter(role=instance.role).values_list('user_id', flat=True)
        for uid in user_ids:
            PermissionService.clear_user_permission_cache(uid)
    except Exception:
        pass

@receiver(post_save, sender='leads.UserProfile')
@receiver(post_delete, sender='leads.UserProfile')
def invalidate_user_profile_cache(sender, instance, **kwargs):
    """Invalidates permission cache for the modified user profile's user."""
    from roles.services import PermissionService
    try:
        if instance.user_id:
            PermissionService.clear_user_permission_cache(instance.user_id)
    except Exception:
        pass

