from decimal import Decimal
from rest_framework import serializers
from billing.models import (
    BillingCustomer,
    Subscription,
    SubscriptionItem,
    AddOn,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
    CreditNote,
    CreditNoteAllocation,
    DebitNote,
    DunningLog,
    SubscriptionAuditLog,
    SubscriptionChangeLog,
)
from catalog.models.plan import PricingPlan


class BillingCustomerSerializer(serializers.ModelSerializer):
    customer_number = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True
    )
    created_by = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = BillingCustomer
        fields = [
            'id',
            'customer_number',
            'name',
            'email',
            'phone',
            'billing_address_line1',
            'billing_address_line2',
            'billing_city',
            'billing_state',
            'billing_postal_code',
            'billing_country',
            'currency',
            'tax_id',
            'tax_exempt',
            'default_payment_method_id',
            'external_reference_id',
            'organization',
            'metadata',
            'is_active',
            'created_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'created_at', 'updated_at']

    def get_created_by(self, obj):
        if obj.metadata and isinstance(obj.metadata, dict):
            return obj.metadata.get('created_by_id')
        return None

    def validate_name(self, value):
        cleaned = (value or '').strip()
        if not cleaned:
            raise serializers.ValidationError("Name is required.")
        return cleaned

    def validate_email(self, value):
        if not value:
            return ''
        cleaned = value.strip().lower()
        return cleaned

    def validate_tax_id(self, value):
        if not value:
            return ''
        return value.strip()

    def validate_billing_address_line1(self, value):
        return (value or '').strip()

    def validate_billing_address_line2(self, value):
        return (value or '').strip()

    def validate_billing_city(self, value):
        return (value or '').strip()

    def validate_billing_state(self, value):
        return (value or '').strip()

    def validate_billing_postal_code(self, value):
        return (value or '').strip()

    def validate_billing_country(self, value):
        return (value or '').strip()

    def validate_phone(self, value):
        return (value or '').strip()

    def validate_default_payment_method_id(self, value):
        if not value:
            return ''
        cleaned = value.strip()
        digits = cleaned.replace(' ', '').replace('-', '')
        if digits.isdigit() and len(digits) in (15, 16):
            raise serializers.ValidationError("Raw credit card numbers are prohibited. Supply a safe gateway payment method token.")
        return cleaned

    def validate_customer_number(self, value):
        if self.instance and self.instance.pk:
            # PUT / PATCH update mode: customer_number is immutable
            if value and value != self.instance.customer_number:
                raise serializers.ValidationError("customer_number is immutable and cannot be changed.")
            return self.instance.customer_number

        # POST creation mode
        if value:
            cleaned = value.strip()
            if not cleaned:
                return ''
            if len(cleaned) > 50:
                raise serializers.ValidationError("customer_number cannot exceed 50 characters.")
            if BillingCustomer.objects.filter(customer_number=cleaned).exists():
                raise serializers.ValidationError("Customer number already exists.")
            return cleaned
        return ''


class SubscriptionItemSerializer(serializers.ModelSerializer):
    plan_name = serializers.ReadOnlyField(source='plan.name', default=None)
    addon_name = serializers.ReadOnlyField(source='addon.name', default=None)
    item_name = serializers.SerializerMethodField()
    billing_cycle = serializers.SerializerMethodField()
    plan = serializers.PrimaryKeyRelatedField(
        queryset=PricingPlan.objects.filter(is_active=True),
        required=False,
        allow_null=True
    )
    addon = serializers.PrimaryKeyRelatedField(
        queryset=AddOn.objects.filter(is_active=True),
        required=False,
        allow_null=True
    )
    unit_price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True
    )

    class Meta:
        model = SubscriptionItem
        fields = [
            'id',
            'subscription',
            'item_type',
            'plan',
            'addon',
            'plan_name',
            'addon_name',
            'item_name',
            'billing_cycle',
            'quantity',
            'unit_price',
            'discount_amount',
            'start_date',
            'end_date',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'subscription', 'created_at', 'updated_at']

    def get_item_name(self, obj):
        if obj.item_type == 'PLAN' and obj.plan:
            return obj.plan.name
        elif obj.item_type == 'ADDON' and obj.addon:
            return obj.addon.name
        return "Unknown Item"

    def get_billing_cycle(self, obj):
        if obj.item_type == 'PLAN' and obj.plan:
            return obj.plan.billing_cycle
        elif obj.item_type == 'ADDON' and obj.addon:
            return obj.addon.billing_cycle
        return "monthly"

    def validate(self, attrs):
        item_type = attrs.get('item_type')
        plan = attrs.get('plan')
        addon = attrs.get('addon')
        quantity = attrs.get('quantity', 1)

        if quantity is None or quantity < 1:
            raise serializers.ValidationError({"quantity": "Quantity must be a positive integer."})

        if item_type == 'PLAN':
            if not plan or addon:
                raise serializers.ValidationError({"plan": "Subscription item of type 'PLAN' must have a valid plan and no addon."})
        elif item_type == 'ADDON':
            if not addon or plan:
                raise serializers.ValidationError({"addon": "Subscription item of type 'ADDON' must have a valid addon and no plan."})
            if addon.max_quantity and quantity > addon.max_quantity:
                raise serializers.ValidationError({"quantity": f"Quantity exceeds maximum allowed for add-on '{addon.name}' (max {addon.max_quantity})."})
        else:
            raise serializers.ValidationError({"item_type": "Invalid item_type. Must be 'PLAN' or 'ADDON'."})

        return attrs


class AvailablePlanSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name', default=None)
    service_name = serializers.ReadOnlyField(source='service.name', default=None)

    class Meta:
        model = PricingPlan
        fields = [
            'id',
            'name',
            'price',
            'currency',
            'billing_cycle',
            'product_name',
            'service_name',
            'is_active',
        ]


class AvailableAddonSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name', default=None)

    class Meta:
        model = AddOn
        fields = [
            'id',
            'name',
            'code',
            'price',
            'currency',
            'billing_cycle',
            'unit_label',
            'max_quantity',
            'product_name',
            'is_active',
        ]


class SubscriptionSerializer(serializers.ModelSerializer):
    subscription_number = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True
    )
    customer_name = serializers.ReadOnlyField(source='customer.name')
    customer_number = serializers.ReadOnlyField(source='customer.customer_number')
    billing_cycle = serializers.CharField(write_only=True, required=False, default='MONTHLY')
    created_by = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Subscription
        fields = [
            'id',
            'subscription_number',
            'customer',
            'customer_name',
            'customer_number',
            'status',
            'currency',
            'collection_method',
            'payment_terms_days',
            'current_term_start',
            'current_term_end',
            'trial_start',
            'trial_end',
            'next_billing_date',
            'pause_date',
            'resume_date',
            'cancelled_at',
            'cancel_at_period_end',
            'cached_mrr',
            'cached_arr',
            'metadata',
            'created_by',
            'billing_cycle',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'cached_mrr', 'cached_arr', 'created_at', 'updated_at']

    def get_created_by(self, obj):
        if obj.metadata and isinstance(obj.metadata, dict):
            return obj.metadata.get('created_by_id')
        return None

    def validate_payment_terms_days(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("payment_terms_days must be a non-negative integer.")
        return value

    def validate_customer(self, value):
        if self.instance and self.instance.pk:
            if value != self.instance.customer:
                raise serializers.ValidationError("Linked customer is immutable and cannot be changed.")
        return value

    def validate_subscription_number(self, value):
        if self.instance and self.instance.pk:
            if value and value != self.instance.subscription_number:
                raise serializers.ValidationError("subscription_number is immutable and cannot be changed.")
            return self.instance.subscription_number

        if value:
            cleaned = value.strip()
            if not cleaned:
                return ''
            if len(cleaned) > 50:
                raise serializers.ValidationError("subscription_number cannot exceed 50 characters.")
            if Subscription.objects.filter(subscription_number=cleaned).exists():
                raise serializers.ValidationError("Subscription number already exists.")
            return cleaned
        return ''

    def validate_status(self, value):
        if self.instance and self.instance.pk:
            if value != self.instance.status:
                raise serializers.ValidationError(
                    "Arbitrary status changes via update endpoints are prohibited in Phase 3. Status transitions are governed by the state machine service in Phase 5."
                )
        return value


class SubscriptionDetailSerializer(SubscriptionSerializer):
    customer_details = BillingCustomerSerializer(source='customer', read_only=True)
    items = SubscriptionItemSerializer(many=True, read_only=True)

    class Meta(SubscriptionSerializer.Meta):
        fields = SubscriptionSerializer.Meta.fields + ['customer_details', 'items']


class SubscriptionTransitionSerializer(serializers.Serializer):
    to_status = serializers.CharField(max_length=50)
    reason = serializers.CharField(required=False, allow_blank=True, default='')
    metadata = serializers.JSONField(required=False, default=dict)

    def validate_to_status(self, value):
        cleaned = (value or '').strip().upper()
        if not cleaned:
            raise serializers.ValidationError("to_status is required.")
        valid_choices = [c[0] for c in Subscription.STATUS_CHOICES]
        if cleaned not in valid_choices:
            raise serializers.ValidationError(f"Invalid status '{value}'. Valid choices are: {', '.join(valid_choices)}.")
        return cleaned


class SubscriptionCancelSerializer(serializers.Serializer):
    CANCEL_TYPE_CHOICES = ['IMMEDIATE', 'PERIOD_END']
    cancel_type = serializers.ChoiceField(choices=CANCEL_TYPE_CHOICES, default='IMMEDIATE')
    reason = serializers.CharField(required=True, allow_blank=False)

    def validate_reason(self, value):
        cleaned = (value or '').strip()
        if not cleaned:
            raise serializers.ValidationError("A cancellation reason is required.")
        return cleaned


class SubscriptionPauseSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, allow_blank=False)

    def validate_reason(self, value):
        cleaned = (value or '').strip()
        if not cleaned:
            raise serializers.ValidationError("A reason is required when pausing a subscription.")
        return cleaned


class SubscriptionResumeSerializer(serializers.Serializer):
    pass


class AddOnAmendmentItemSerializer(serializers.Serializer):
    ACTION_CHOICES = ['ADD', 'CHANGE', 'REMOVE']
    addon_id = serializers.IntegerField(required=True)
    action = serializers.ChoiceField(choices=ACTION_CHOICES, default='ADD')
    quantity = serializers.IntegerField(required=False, min_value=1)

    def validate(self, attrs):
        action = (attrs.get('action') or 'ADD').upper()
        qty = attrs.get('quantity')
        if action in ('ADD', 'CHANGE') and (qty is None or qty < 1):
            raise serializers.ValidationError({"quantity": f"Quantity is required and must be >= 1 for action '{action}'."})
        return attrs


class SubscriptionProrationPreviewSerializer(serializers.Serializer):
    new_plan_id = serializers.IntegerField(required=False, allow_null=True)
    add_ons = AddOnAmendmentItemSerializer(many=True, required=False)
    effective_date = serializers.DateField(required=False, allow_null=True)


class SubscriptionAmendSerializer(serializers.Serializer):
    new_plan_id = serializers.IntegerField(required=False, allow_null=True)
    add_ons = AddOnAmendmentItemSerializer(many=True, required=False)
    effective_date = serializers.DateField(required=False, allow_null=True)
    reason = serializers.CharField(required=True, allow_blank=False)

    def validate_reason(self, value):
        cleaned = (value or '').strip()
        if not cleaned:
            raise serializers.ValidationError("An amendment reason is required.")
        return cleaned


class InvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = [
            'id',
            'invoice',
            'subscription_item',
            'description',
            'quantity',
            'unit_price',
            'subtotal',
            'discount_amount',
            'tax_amount',
            'total_amount',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'invoice', 'created_at', 'updated_at']


class InvoiceSerializer(serializers.ModelSerializer):
    customer_name = serializers.ReadOnlyField(source='customer.name')
    customer_number = serializers.ReadOnlyField(source='customer.customer_number')
    subscription_number = serializers.ReadOnlyField(source='subscription.subscription_number', default=None)

    class Meta:
        model = Invoice
        fields = [
            'id',
            'invoice_number',
            'subscription',
            'subscription_number',
            'customer',
            'customer_name',
            'customer_number',
            'billing_period_start',
            'billing_period_end',
            'issue_date',
            'due_date',
            'paid_at',
            'subtotal',
            'discount_total',
            'tax_total',
            'total_amount',
            'paid_amount',
            'balance',
            'status',
            'idempotency_key',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id', 'invoice_number', 'idempotency_key', 'created_at', 'updated_at',
            'subtotal', 'discount_total', 'tax_total', 'total_amount', 'paid_amount', 'balance'
        ]

    def validate(self, attrs):
        if self.instance and self.instance.pk:
            if self.instance.status in ['POSTED', 'PAID', 'PARTIALLY_PAID', 'VOID', 'UNCOLLECTIBLE']:
                protected_fields = ['subtotal', 'discount_total', 'tax_total', 'total_amount', 'billing_period_start', 'billing_period_end', 'customer']
                for f in protected_fields:
                    if f in self.initial_data:
                        raw_val = str(self.initial_data[f]).strip()
                        current_val = str(getattr(self.instance, f) or '').strip()
                        if raw_val != current_val:
                            raise serializers.ValidationError({f: f"Invoice in status '{self.instance.status}' is posted/immutable and cannot be modified."})
        return attrs


class InvoiceDetailSerializer(InvoiceSerializer):
    customer_details = BillingCustomerSerializer(source='customer', read_only=True)
    subscription_details = SubscriptionSerializer(source='subscription', read_only=True)
    lines = InvoiceLineSerializer(many=True, read_only=True)

    class Meta(InvoiceSerializer.Meta):
        fields = InvoiceSerializer.Meta.fields + ['customer_details', 'subscription_details', 'lines']


class InvoiceGenerateSerializer(serializers.Serializer):
    subscription = serializers.PrimaryKeyRelatedField(queryset=Subscription.objects.all())
    billing_period_start = serializers.DateField(required=False, allow_null=True)
    billing_period_end = serializers.DateField(required=False, allow_null=True)
    issue_date = serializers.DateField(required=False, allow_null=True)
    due_date = serializers.DateField(required=False, allow_null=True)


class PaymentAllocationSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)

    class Meta:
        model = PaymentAllocation
        fields = [
            'id',
            'payment',
            'invoice',
            'invoice_number',
            'amount',
            'allocated_at',
            'notes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'payment', 'allocated_at', 'created_at', 'updated_at']


class PaymentSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    allocated_amount = serializers.SerializerMethodField(read_only=True)
    allocations = PaymentAllocationSerializer(many=True, read_only=True)

    class Meta:
        model = Payment
        fields = [
            'id',
            'payment_number',
            'customer',
            'customer_name',
            'amount',
            'currency',
            'payment_method',
            'payment_method_id',
            'gateway_transaction_id',
            'status',
            'payment_date',
            'unallocated_amount',
            'allocated_amount',
            'notes',
            'allocations',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'payment_number',
            'status',
            'unallocated_amount',
            'allocated_amount',
            'created_at',
            'updated_at',
        ]

    def get_allocated_amount(self, obj):
        amt = obj.amount or 0
        unalloc = obj.unallocated_amount or 0
        return str(Decimal(str(amt - unalloc)).quantize(Decimal('0.01')))

    def validate(self, attrs):
        if self.instance:
            for f in ['amount', 'customer', 'currency', 'payment_number']:
                if f in self.initial_data:
                    raw_val = str(self.initial_data[f]).strip()
                    current_val = str(getattr(self.instance, f) or '').strip()
                    if raw_val != current_val:
                        raise serializers.ValidationError({f: "Payment financial identity fields are immutable once recorded."})
        return attrs


class PaymentCreateSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=BillingCustomer.objects.all())
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency = serializers.CharField(max_length=10, required=False, default='USD')
    payment_method = serializers.CharField(max_length=30, required=False, default='CREDIT_CARD')
    payment_method_id = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    gateway_transaction_id = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    payment_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class AllocationItemSerializer(serializers.Serializer):
    invoice_id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class PaymentAllocateSerializer(serializers.Serializer):
    allocations = AllocationItemSerializer(many=True)


class PaymentMethodAttachSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=BillingCustomer.objects.all(), required=False)
    customer_id = serializers.IntegerField(required=False)
    payment_method_id = serializers.CharField(max_length=255)
    set_as_default = serializers.BooleanField(required=False, default=True)

    def validate_payment_method_id(self, value):
        val_str = str(value).strip()
        if not val_str.startswith('pm_'):
            raise serializers.ValidationError("Invalid payment method token. Safe Stripe payment method token must start with 'pm_'. Raw card data is forbidden.")

        return val_str

    def validate(self, attrs):
        cust = attrs.get('customer')
        cust_id = attrs.get('customer_id')
        if not cust and cust_id:
            try:
                attrs['customer'] = BillingCustomer.objects.get(pk=cust_id)
            except BillingCustomer.DoesNotExist:
                raise serializers.ValidationError({"customer_id": "Invalid BillingCustomer ID."})
        if not attrs.get('customer'):
            raise serializers.ValidationError({"customer": "customer or customer_id is required."})
        return attrs


class DunningLogSerializer(serializers.ModelSerializer):
    subscription_number = serializers.ReadOnlyField(source='subscription.subscription_number')
    invoice_number = serializers.ReadOnlyField(source='invoice.invoice_number')

    class Meta:
        model = DunningLog
        fields = [
            'id',
            'subscription',
            'subscription_number',
            'invoice',
            'invoice_number',
            'attempt_number',
            'status',
            'gateway_transaction_id',
            'idempotency_key',
            'error_code',
            'error_message',
            'next_retry_at',
            'timestamp',
        ]


class CreditNoteAllocationSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)
    credit_note_number = serializers.CharField(source='credit_note.credit_note_number', read_only=True)

    class Meta:
        model = CreditNoteAllocation
        fields = [
            'id',
            'credit_note',
            'credit_note_number',
            'invoice',
            'invoice_number',
            'amount',
            'allocated_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'credit_note', 'allocated_at', 'created_at', 'updated_at']


class CreditNoteSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_number = serializers.CharField(source='customer.customer_number', read_only=True)
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)
    allocated_amount = serializers.SerializerMethodField(read_only=True)
    allocations = CreditNoteAllocationSerializer(many=True, read_only=True)

    class Meta:
        model = CreditNote
        fields = [
            'id',
            'credit_note_number',
            'customer',
            'customer_name',
            'customer_number',
            'invoice',
            'invoice_number',
            'reason',
            'subtotal',
            'tax_total',
            'total_amount',
            'unallocated_amount',
            'allocated_amount',
            'status',
            'issued_date',
            'allocations',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'credit_note_number',
            'subtotal',
            'tax_total',
            'total_amount',
            'unallocated_amount',
            'allocated_amount',
            'status',
            'created_at',
            'updated_at',
        ]

    def get_allocated_amount(self, obj):
        amt = obj.total_amount or Decimal('0.00')
        unalloc = obj.unallocated_amount or Decimal('0.00')
        return str(Decimal(str(amt - unalloc)).quantize(Decimal('0.01')))

    def validate(self, attrs):
        if self.instance:
            for f in ['total_amount', 'subtotal', 'tax_total', 'customer', 'invoice', 'credit_note_number']:
                if f in self.initial_data:
                    raw_val = str(self.initial_data[f]).strip()
                    current_val = str(getattr(self.instance, f) or '').strip()
                    if raw_val != current_val:
                        raise serializers.ValidationError({f: "Credit Note financial identity fields are immutable once issued."})
        return attrs


class CreditNoteIssueSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=BillingCustomer.objects.all(), required=False)
    customer_id = serializers.IntegerField(required=False)
    invoice = serializers.PrimaryKeyRelatedField(queryset=Invoice.objects.all(), required=False, allow_null=True)
    invoice_id = serializers.IntegerField(required=False, allow_null=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    reason = serializers.ChoiceField(choices=CreditNote.REASON_CHOICES, required=False, default='CORRECTION')
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    tax_total = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    issued_date = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        cust = attrs.get('customer')
        cust_id = attrs.get('customer_id')
        if not cust and cust_id:
            try:
                attrs['customer'] = BillingCustomer.objects.get(pk=cust_id)
            except BillingCustomer.DoesNotExist:
                raise serializers.ValidationError({"customer_id": "Invalid BillingCustomer ID."})

        inv = attrs.get('invoice')
        inv_id = attrs.get('invoice_id')
        if not inv and inv_id:
            try:
                inv = Invoice.objects.get(pk=inv_id)
                attrs['invoice'] = inv
            except Invoice.DoesNotExist:
                raise serializers.ValidationError({"invoice_id": "Invalid Invoice ID."})

        if not attrs.get('customer'):
            if attrs.get('invoice'):
                attrs['customer'] = attrs['invoice'].customer
            else:
                raise serializers.ValidationError({"customer": "customer or customer_id is required."})

        return attrs


class CreditNoteAllocateSerializer(serializers.Serializer):
    allocations = AllocationItemSerializer(many=True, required=False)
    invoice_id = serializers.IntegerField(required=False)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)

    def validate(self, attrs):
        allocations = attrs.get('allocations')
        if not allocations:
            inv_id = attrs.get('invoice_id')
            amt = attrs.get('amount')
            if inv_id and amt:
                attrs['allocations'] = [{'invoice_id': inv_id, 'amount': amt}]
            else:
                raise serializers.ValidationError({"allocations": "allocations list or (invoice_id and amount) is required."})
        return attrs


class DebitNoteSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)
    customer_id = serializers.IntegerField(source='invoice.customer.id', read_only=True)
    customer_name = serializers.CharField(source='invoice.customer.name', read_only=True)

    class Meta:
        model = DebitNote
        fields = [
            'id',
            'debit_note_number',
            'invoice',
            'invoice_number',
            'customer_id',
            'customer_name',
            'amount',
            'reason',
            'issued_date',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'debit_note_number', 'created_at', 'updated_at']

    def validate(self, attrs):
        if self.instance:
            for f in ['amount', 'invoice', 'debit_note_number']:
                if f in self.initial_data:
                    raw_val = str(self.initial_data[f]).strip()
                    current_val = str(getattr(self.instance, f) or '').strip()
                    if raw_val != current_val:
                        raise serializers.ValidationError({f: "Debit Note financial identity fields are immutable once issued."})
        return attrs


class DebitNoteIssueSerializer(serializers.Serializer):
    invoice = serializers.PrimaryKeyRelatedField(queryset=Invoice.objects.all(), required=False)
    invoice_id = serializers.IntegerField(required=False)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    reason = serializers.CharField(required=False, allow_blank=True, default='')
    issued_date = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        inv = attrs.get('invoice')
        inv_id = attrs.get('invoice_id')
        if not inv and inv_id:
            try:
                attrs['invoice'] = Invoice.objects.get(pk=inv_id)
            except Invoice.DoesNotExist:
                raise serializers.ValidationError({"invoice_id": "Invalid Invoice ID."})
        if not attrs.get('invoice'):
            raise serializers.ValidationError({"invoice": "invoice or invoice_id is required."})
        return attrs


class SubscriptionAuditLogSerializer(serializers.ModelSerializer):
    subscription_number = serializers.CharField(source='subscription.subscription_number', read_only=True)
    customer_id = serializers.IntegerField(source='subscription.customer.id', read_only=True)
    customer_name = serializers.CharField(source='subscription.customer.name', read_only=True)

    class Meta:
        model = SubscriptionAuditLog
        fields = [
            'id',
            'subscription',
            'subscription_number',
            'customer_id',
            'customer_name',
            'actor_id',
            'actor_type',
            'action',
            'old_state',
            'new_state',
            'reason',
            'metadata',
            'timestamp',
        ]
        read_only_fields = fields


class SubscriptionChangeLogSerializer(serializers.ModelSerializer):
    subscription_number = serializers.CharField(source='subscription.subscription_number', read_only=True)

    class Meta:
        model = SubscriptionChangeLog
        fields = [
            'id',
            'subscription',
            'subscription_number',
            'change_type',
            'details',
            'proration_amount',
            'effective_date',
            'timestamp',
        ]
        read_only_fields = fields


class UnifiedAuditActivitySerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True)
    subscription = serializers.IntegerField(read_only=True, required=False)
    subscription_number = serializers.CharField(read_only=True, required=False)
    category = serializers.CharField(read_only=True)
    action = serializers.CharField(read_only=True)
    title = serializers.CharField(read_only=True)
    actor_type = serializers.CharField(read_only=True)
    actor_id = serializers.CharField(read_only=True, allow_null=True)
    actor_name = serializers.CharField(read_only=True, allow_null=True)
    timestamp = serializers.DateTimeField(read_only=True)
    reason = serializers.CharField(read_only=True, allow_blank=True)
    state_delta = serializers.DictField(read_only=True)
    details = serializers.DictField(read_only=True)
    proration_amount = serializers.CharField(read_only=True)


class EntitlementCheckQuerySerializer(serializers.Serializer):
    feature = serializers.CharField(required=False, allow_blank=True, default='')
    limit = serializers.CharField(required=False, allow_blank=True, default='')


class WonOpportunityAddOnItemSerializer(serializers.Serializer):
    addon_id = serializers.IntegerField(required=True)
    quantity = serializers.IntegerField(required=False, default=1, min_value=1)

    def validate_addon_id(self, value):
        if not AddOn.objects.filter(id=value, is_active=True).exists():
            raise serializers.ValidationError(f"AddOn {value} does not exist or is inactive.")
        return value


class WonOpportunityProvisionSerializer(serializers.Serializer):
    opportunity_id = serializers.IntegerField(required=True)
    company_id = serializers.IntegerField(required=False, allow_null=True)
    company_name = serializers.CharField(required=False, allow_blank=True, default='')
    contact_email = serializers.EmailField(required=False, allow_blank=True, default='')
    plan_id = serializers.IntegerField(required=True)
    plan_quantity = serializers.IntegerField(required=False, default=1, min_value=1)
    billing_cycle = serializers.CharField(required=False, allow_blank=True, default='')
    start_date = serializers.DateField(required=False, allow_null=True)
    collection_method = serializers.ChoiceField(
        choices=['CHARGE_AUTOMATIC', 'SEND_INVOICE'],
        required=False,
        default='CHARGE_AUTOMATIC'
    )
    payment_terms_days = serializers.IntegerField(required=False, default=0, min_value=0)
    add_ons = WonOpportunityAddOnItemSerializer(many=True, required=False, default=list)

    def validate_plan_id(self, value):
        if not PricingPlan.objects.filter(id=value, is_active=True).exists():
            raise serializers.ValidationError(f"PricingPlan {value} does not exist or is inactive.")
        return value


class SubscriberBreakdownSerializer(serializers.Serializer):
    by_status = serializers.DictField(child=serializers.IntegerField(), read_only=True)
    by_plan = serializers.DictField(child=serializers.IntegerField(), read_only=True)
    by_billing_cycle = serializers.DictField(child=serializers.IntegerField(), read_only=True)


class AnalyticsOverviewSerializer(serializers.Serializer):
    live_mrr = serializers.CharField(read_only=True)
    live_arr = serializers.CharField(read_only=True)
    active_subscribers = serializers.IntegerField(read_only=True)
    arpu = serializers.CharField(read_only=True)
    ltv = serializers.CharField(read_only=True)
    churn_rate_pct = serializers.CharField(read_only=True)
    subscriber_breakdown = SubscriberBreakdownSerializer(read_only=True)
    total_collected_revenue = serializers.CharField(read_only=True)


class MrrMovementItemSerializer(serializers.Serializer):
    period = serializers.CharField(read_only=True)
    new_mrr = serializers.CharField(read_only=True)
    expansion_mrr = serializers.CharField(read_only=True)
    contraction_mrr = serializers.CharField(read_only=True)
    churned_mrr = serializers.CharField(read_only=True)
    reactivation_mrr = serializers.CharField(read_only=True)
    net_mrr_growth = serializers.CharField(read_only=True)
    ending_mrr = serializers.CharField(read_only=True)


class MrrMovementResponseSerializer(serializers.Serializer):
    results = MrrMovementItemSerializer(many=True, read_only=True)

