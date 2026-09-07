import os
import sys
import django

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from leads.models import UserProfile
from roles.models import Role
from accounts.models import Organization

User = get_user_model()

def fix():
    print("=== BACKFILLING CRM QA WORKSPACE PROFILES ===")
    
    # 1. Resolve organization
    org_name = "QA Testing Corp"
    org = Organization.objects.filter(name=org_name).first()
    if not org:
        org = Organization.objects.create(name=org_name, is_active=True)
        print(f"Created missing Organization: {org_name}")
    else:
        if not org.is_active:
            org.is_active = True
            org.save()
            print(f"Activated existing Organization: {org_name}")
            
    # 2. Update zaidqa_test@example.com (CRM Admin)
    try:
        u_admin = User.objects.get(username='zaidqa_test@example.com')
        role_admin = Role.objects.get(name='Administrator')
        up_admin = u_admin.profile
        up_admin.user_type = 'ADMIN'
        up_admin.role = role_admin
        up_admin.organization = org
        up_admin.save()
        print("Updated zaidqa_test@example.com -> ADMIN / Administrator / QA Testing Corp")
    except User.DoesNotExist:
        print("Error: User zaidqa_test@example.com does not exist.")
    except Exception as e:
        print(f"Error updating zaidqa_test: {e}")

    # 3. Update mz@gmail.com (CRM Manager)
    try:
        u_mgr = User.objects.get(username='mz@gmail.com')
        role_mgr = Role.objects.get(name='Manager')
        up_mgr = u_mgr.profile
        up_mgr.user_type = 'USER'
        up_mgr.role = role_mgr
        up_mgr.organization = org
        up_mgr.save()
        print("Updated mz@gmail.com -> USER / Manager / QA Testing Corp")
    except User.DoesNotExist:
        print("Error: User mz@gmail.com does not exist.")
    except Exception as e:
        print(f"Error updating mz: {e}")

    # 4. Update salesperson1 (CRM Salesperson)
    try:
        u_sp = User.objects.get(username='salesperson1')
        role_sp = Role.objects.get(name='Salesperson')
        up_sp = u_sp.profile
        up_sp.user_type = 'USER'
        up_sp.role = role_sp
        up_sp.organization = org
        up_sp.save()
        print("Updated salesperson1 -> USER / Salesperson / QA Testing Corp")
    except User.DoesNotExist:
        print("Error: User salesperson1 does not exist.")
    except Exception as e:
        print(f"Error updating salesperson1: {e}")

if __name__ == '__main__':
    fix()
