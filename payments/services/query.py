from django.db.models import QuerySet

from payments.models import Payment
from payments.permissions.payment import is_manager_or_admin


class PaymentQueryService:
    @staticmethod
    def get_visible_payments(user, queryset=None) -> QuerySet:
        if queryset is None:
            queryset = Payment.objects.all()

        queryset = queryset.select_related(
            'company',
            'opportunity',
            'assigned_salesperson',
        )

        from roles.permissions import get_scoped_queryset
        return get_scoped_queryset(queryset, user, resource_codename='payments', owner_field='assigned_salesperson')
