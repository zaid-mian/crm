import os
import sys
import django
from django.test import RequestFactory

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from accounts.views.admin import AdminUserListView

User = get_user_model()
factory = RequestFactory()

def run_test_queries():
    print("=== RUNNING API USER SCOPING VERIFICATION ===")
    
    # 1. Test Direct CRM Admin (zaidqa_test@example.com)
    try:
        u_crm_admin = User.objects.get(username='zaidqa_test@example.com')
        request = factory.get('/api/admin/users/')
        request.user = u_crm_admin
        
        view = AdminUserListView.as_view()
        response = view(request)
        
        print("\n[TEST 1] Logging in directly as zaidqa_test@example.com (CRM Admin):")
        print(f"  -> Response Status: {response.status_code}")
        data = response.data
        if data.get('success'):
            users = data['data']
            print(f"  -> Number of users returned: {len(users)}")
            for usr in users:
                print(f"     * User: {usr['email']} | Org: {usr['organization']} | Role: {usr['role']} | Status: {usr['status']}")
        else:
            print(f"  -> Error: {data.get('message')}")
    except Exception as e:
        print(f"  -> Exception: {e}")

    # 2. Test JTS Admin (admin@bms.com) without organization parameter
    try:
        u_jts_admin = User.objects.get(username='admin@bms.com')
        request = factory.get('/api/admin/users/')
        request.user = u_jts_admin
        
        view = AdminUserListView.as_view()
        response = view(request)
        
        print("\n[TEST 2] Logging in as admin@bms.com (JTS Admin, no org context):")
        print(f"  -> Response Status: {response.status_code}")
        data = response.data
        if data.get('success'):
            users = data['data']
            print(f"  -> Number of users returned (Should be 0): {len(users)}")
            for usr in users:
                print(f"     * User: {usr['email']} | Org: {usr['organization']}")
        else:
            print(f"  -> Error: {data.get('message')}")
    except Exception as e:
        print(f"  -> Exception: {e}")

    # 3. Test JTS Admin (admin@bms.com) with organization parameter pointing to QA Testing Corp
    try:
        from accounts.models import Organization
        org = Organization.objects.filter(name='QA Testing Corp').first()
        org_id = org.id if org else 13
        
        u_jts_admin = User.objects.get(username='admin@bms.com')
        request = factory.get(f'/api/admin/users/?organization_id={org_id}')
        request.user = u_jts_admin
        
        view = AdminUserListView.as_view()
        response = view(request)
        
        print(f"\n[TEST 3] Logging in as admin@bms.com with organization_id={org_id} (QA Testing Corp):")
        print(f"  -> Response Status: {response.status_code}")
        data = response.data
        if data.get('success'):
            users = data['data']
            print(f"  -> Number of users returned: {len(users)}")
            for usr in users:
                print(f"     * User: {usr['email']} | Org: {usr['organization']} | Role: {usr['role']}")
        else:
            print(f"  -> Error: {data.get('message')}")
    except Exception as e:
        print(f"  -> Exception: {e}")

if __name__ == '__main__':
    run_test_queries()
