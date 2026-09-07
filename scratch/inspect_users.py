import os
import sys
import django

# Add current directory to sys.path
sys.path.append(os.getcwd())

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from accounts.models import Organization, OwnerProfile, RegistrationRequest
from leads.models import UserProfile

User = get_user_model()

print("--- ORGANIZATIONS ---")
for org in Organization.objects.all():
    print(f"ID: {org.id} | Name: {org.name} | Active: {org.is_active}")

print("\n--- USERS ---")
for user in User.objects.all():
    profile = getattr(user, 'profile', None)
    owner = getattr(user, 'ownerprofile', None)
    
    p_org = profile.organization.name if profile and profile.organization else "None"
    p_role = profile.role.name if profile and profile.role else "None"
    p_type = profile.user_type if profile else "None"
    
    o_org = owner.organization.name if owner and owner.organization else "None"
    
    print(f"ID: {user.id} | Username: {user.username} | Email: {user.email} | Active: {user.is_active} | Staff: {user.is_staff} | Superuser: {user.is_superuser}")
    print(f"  -> CRM Profile: Type={p_type}, Role={p_role}, Org={p_org}")
    print(f"  -> JTS OwnerProfile Org: {o_org}")
