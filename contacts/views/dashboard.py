from django.shortcuts import render
from django.contrib.auth import get_user_model
from contacts.models import Contact
from contacts.permissions import is_manager_or_admin

User = get_user_model()

def dashboard_view(request):
    """
    Renders the Contact Board with interactive Admin vs User role toggle option.
    Allows easy switching between Admin View (with Delete option) and User View (without Delete option).
    """
    role = request.GET.get('role', request.session.get('active_role', 'admin')).lower()
    request.session['active_role'] = role

    contacts_qs = Contact.objects.filter(is_deleted=False)
    total_contacts = contacts_qs.count()
    active_contacts = contacts_qs.filter(status='Active').count()
    inactive_contacts = contacts_qs.filter(status='Inactive').count()
    
    my_contacts = 0
    if request.user.is_authenticated:
        my_contacts = contacts_qs.filter(assigned_salesperson=request.user).count()

    is_admin = (role == 'admin')

    users = User.objects.exclude(username='admin').exclude(is_superuser=True)

    context = {
        'total_contacts': total_contacts,
        'active_contacts': active_contacts,
        'inactive_contacts': inactive_contacts,
        'my_contacts': my_contacts,
        'users': users,
        'is_admin': is_admin,
        'active_role': role,
    }
    return render(request, 'dashboard.html', context)
