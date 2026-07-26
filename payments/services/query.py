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

        if not user or not user.is_authenticated:
            return queryset

        if is_manager_or_admin(user):
            return queryset

        return queryset.filter(assigned_salesperson=user)
