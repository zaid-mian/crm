from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from payments.permissions.payment import is_finance_or_admin, is_manager_or_admin
from payments.utils.responses import api_success


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def current_user(request):
    user = request.user
    groups = list(user.groups.values_list('name', flat=True))
    data = {
        'username': user.username,
        'groups': groups,
        'is_admin': user.is_superuser or user.is_staff,
        'is_finance_or_admin': is_finance_or_admin(user),
        'is_manager_or_admin': is_manager_or_admin(user),
        'can_modify_payments': is_finance_or_admin(user),
        'can_view_all': is_manager_or_admin(user),
    }
    return api_success(data=data, message='Current user retrieved.')
