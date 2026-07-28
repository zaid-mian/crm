from rest_framework import serializers

from opportunities.models import Opportunity
from payments.models import InvoiceStatus, Payment, PaymentMethod, PaymentTransaction
from payments.services.invoice import PaymentInvoiceService
from payments.services.payment_workflow import PaymentWorkflowService


class PaymentTransactionSerializer(serializers.ModelSerializer):
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    recorded_by_name = serializers.CharField(source='recorded_by.username', read_only=True, default='')

    class Meta:
        model = PaymentTransaction
        fields = [
            'id',
            'amount',
            'payment_method',
            'payment_method_display',
            'transaction_reference',
            'payment_date',
            'notes',
            'recorded_by_name',
            'created_at',
        ]


class PaymentActivitySerializer(serializers.Serializer):
    action = serializers.CharField()
    description = serializers.CharField()
    created_at = serializers.DateTimeField()
    user_name = serializers.CharField()


class PaymentListSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.name', read_only=True)
    opportunity_name = serializers.CharField(source='opportunity.name', read_only=True)
    assigned_salesperson_name = serializers.CharField(
        source='assigned_salesperson.username',
        read_only=True,
        default='',
    )
    balance = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payment_method = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            'id',
            'invoice_number',
            'company',
            'company_name',
            'opportunity',
            'opportunity_name',
            'total_amount',
            'paid_amount',
            'balance',
            'status',
            'status_display',
            'payment_method',
            'payment_date',
            'assigned_salesperson_name',
            'currency',
            'created_at',
        ]

    def get_payment_method(self, obj):
        latest = obj.transactions.order_by('-payment_date', '-created_at').first()
        return latest.payment_method if latest else None


class PaymentDetailSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.name', read_only=True)
    opportunity_name = serializers.CharField(source='opportunity.name', read_only=True)
    customer_name = serializers.SerializerMethodField()
    assigned_salesperson_name = serializers.CharField(
        source='assigned_salesperson.username',
        read_only=True,
        default='',
    )
    balance = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    transactions = PaymentTransactionSerializer(many=True, read_only=True)
    payment_history = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            'id',
            'invoice_number',
            'company',
            'company_name',
            'opportunity',
            'opportunity_name',
            'customer_name',
            'total_amount',
            'paid_amount',
            'balance',
            'credit_balance',
            'currency',
            'status',
            'status_display',
            'payment_date',
            'notes',
            'assigned_salesperson',
            'assigned_salesperson_name',
            'transactions',
            'payment_history',
            'can_edit',
            'created_at',
            'updated_at',
        ]

    def get_customer_name(self, obj):
        contact = obj.opportunity.primary_contact if obj.opportunity_id else None
        return contact.full_name if contact else ''

    def get_payment_history(self, obj):
        logs = obj.activity_logs.select_related('user').order_by('created_at')
        return [
            {
                'action': log.action,
                'description': log.description,
                'created_at': log.created_at,
                'user_name': log.user.username if log.user else '',
            }
            for log in logs
        ]

    def get_can_edit(self, obj):
        request = self.context.get('request')
        if not request:
            return False
        from payments.permissions.payment import is_finance_or_admin
        return is_finance_or_admin(request.user)


class PaymentRecordSerializer(serializers.Serializer):
    payment_id = serializers.IntegerField(required=False)
    company = serializers.IntegerField(required=False)
    opportunity = serializers.IntegerField(required=False)
    total_amount = serializers.DecimalField(max_digits=15, decimal_places=2, required=False)
    amount_received = serializers.DecimalField(max_digits=15, decimal_places=2)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices)
    transaction_reference = serializers.CharField(required=False, allow_blank=True, default='')
    payment_date = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        payment_id = attrs.get('payment_id')
        if payment_id:
            try:
                attrs['payment_instance'] = Payment.objects.select_related('opportunity').get(pk=payment_id)
            except Payment.DoesNotExist as exc:
                raise serializers.ValidationError({'payment_id': 'Payment not found.'}) from exc
            if attrs['payment_instance'].status == InvoiceStatus.PAID:
                raise serializers.ValidationError(
                    {'payment_id': 'This invoice is already fully paid. Update its total first if another balance is due.'}
                )
            return attrs

        if not attrs.get('company') or not attrs.get('opportunity') or attrs.get('total_amount') is None:
            raise serializers.ValidationError(
                'company, opportunity, and total_amount are required when creating a new payment record.'
            )
        try:
            opportunity = Opportunity.objects.select_related('company').get(pk=attrs['opportunity'])
        except Opportunity.DoesNotExist as exc:
            raise serializers.ValidationError({'opportunity': 'Opportunity not found.'}) from exc

        PaymentWorkflowService.validate_opportunity_for_payment(opportunity)
        if opportunity.company_id != attrs['company']:
            raise serializers.ValidationError({'company': 'Company does not match the selected opportunity.'})
        attrs['opportunity_instance'] = opportunity
        return attrs

    def create(self, validated_data):
        user = self.context['request'].user
        amount = validated_data['amount_received']
        txn_payload = {
            'amount': amount,
            'payment_method': validated_data['payment_method'],
            'transaction_reference': validated_data.get('transaction_reference', ''),
            'payment_date': validated_data['payment_date'],
            'notes': validated_data.get('notes', ''),
        }

        if validated_data.get('payment_instance'):
            payment = validated_data['payment_instance']
        else:
            opportunity = validated_data['opportunity_instance']
            existing = Payment.objects.filter(opportunity=opportunity).first()
            if existing:
                payment = existing
                if validated_data['total_amount'] != payment.total_amount:
                    payment.total_amount = validated_data['total_amount']
                    payment.save(update_fields=['total_amount', 'updated_at'])
            else:
                payment = PaymentInvoiceService.generate_from_opportunity(
                    opportunity,
                    user=user,
                    total_amount=validated_data['total_amount'],
                )

        PaymentWorkflowService.add_transaction(payment, txn_payload, user)
        return payment


class PaymentUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ['total_amount', 'notes', 'currency']

    def validate_total_amount(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError('Total amount must be greater than zero.')
        return value

    def update(self, instance, validated_data):
        user = self.context['request'].user
        payment = super().update(instance, validated_data)
        payment.recalculate_totals()
        from payments.services.activity import PaymentActivityService
        PaymentActivityService.log(
            payment,
            action='PAYMENT_UPDATED',
            description='Payment record updated.',
            user=user,
        )
        return payment


class GenerateInvoiceSerializer(serializers.Serializer):
    opportunity_id = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=15, decimal_places=2, required=False)

    def validate_opportunity_id(self, value):
        try:
            self.context['opportunity'] = Opportunity.objects.select_related('company').get(pk=value)
        except Opportunity.DoesNotExist as exc:
            raise serializers.ValidationError('Opportunity not found.') from exc
        return value

    def create(self, validated_data):
        user = self.context['request'].user
        opportunity = self.context['opportunity']
        total_amount = validated_data.get('total_amount')
        return PaymentInvoiceService.generate_from_opportunity(
            opportunity,
            user=user,
            total_amount=total_amount,
        )
