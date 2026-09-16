import calendar
import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.db.models import Sum, Q
from rest_framework.exceptions import ValidationError, PermissionDenied
from billing.models import (
    BillingCustomer,
    Subscription,
    SubscriptionItem,
    AddOn,
    SubscriptionAuditLog,
    SubscriptionChangeLog,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
    CreditNote,
    CreditNoteAllocation,
    DebitNote,
    WebhookInbox,
    DunningLog,
)
from billing.utils.tenant import get_billing_tenant_organization
from catalog.models.plan import PricingPlan, PlanModule
from catalog.models.module import Module

CUST_NUMBER_REGEX = re.compile(r'^CUST-(\d{5})$')
MAX_CUSTOMER_NUMBER_INT = 99999

SUB_NUMBER_REGEX = re.compile(r'^SUB-(\d{5})$')
MAX_SUBSCRIPTION_NUMBER_INT = 99999


class BillingAuditService:
    """
    Centralized, authoritative service for creating immutable audit records
    across subscription lifecycles, commercial changes, and financial events.
    """
    SENSITIVE_KEYS = {
        'password', 'secret', 'token', 'cvv', 'card_number', 'credit_card',
        'api_key', 'stripe_signature', 'raw_payload', 'client_secret', 'authorization'
    }

    @classmethod
    def _sanitize_metadata(cls, data):
        """Recursively sanitizes dictionary metadata to scrub sensitive secrets and payment data."""
        if not isinstance(data, dict):
            return data
        sanitized = {}
        for k, v in data.items():
            if any(sens in str(k).lower() for sens in cls.SENSITIVE_KEYS):
                sanitized[k] = '[REDACTED]'
            elif isinstance(v, dict):
                sanitized[k] = cls._sanitize_metadata(v)
            elif isinstance(v, (list, tuple)):
                sanitized[k] = [cls._sanitize_metadata(item) if isinstance(item, dict) else (str(item) if isinstance(item, Decimal) else item) for item in v]
            elif isinstance(v, Decimal):
                sanitized[k] = str(v)
            else:
                sanitized[k] = v
        return sanitized

    @classmethod
    def log_subscription_lifecycle(cls, subscription, action, actor=None, old_state='', new_state='', reason='', metadata=None):
        """
        Creates an immutable SubscriptionAuditLog record for state transitions and lifecycle actions.
        """
        if actor and getattr(actor, 'id', None):
            actor_id = str(actor.id)
            actor_type = 'USER'
        elif isinstance(actor, str) and actor.strip():
            actor_id = actor.strip()
            actor_type = 'SYSTEM' if actor.upper() in ('SYSTEM', 'ENGINE', 'RENEWAL_ENGINE', 'DUNNING_ENGINE') else 'USER'
        else:
            actor_id = 'SYSTEM'
            actor_type = 'SYSTEM'

        return SubscriptionAuditLog.objects.create(
            subscription=subscription,
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            old_state=old_state or '',
            new_state=new_state or '',
            reason=reason or '',
            metadata=cls._sanitize_metadata(metadata or {})
        )

    @classmethod
    def log_subscription_change(cls, subscription, change_type, details=None, proration_amount=Decimal('0.00'), effective_date=None, actor=None):
        """
        Creates an immutable SubscriptionChangeLog record for catalog deltas, items, and proration math.
        Stores actor metadata inside details JSONField.
        """
        if effective_date is None:
            effective_date = timezone.now().date()

        change_details = details.copy() if isinstance(details, dict) else {}
        if actor and getattr(actor, 'id', None):
            change_details['actor_id'] = str(actor.id)
            change_details['actor_username'] = getattr(actor, 'username', '')

        return SubscriptionChangeLog.objects.create(
            subscription=subscription,
            change_type=change_type,
            details=cls._sanitize_metadata(change_details),
            proration_amount=Decimal(str(proration_amount)).quantize(Decimal('0.01')),
            effective_date=effective_date
        )

    @classmethod
    def log_financial_event(cls, subscription, action, actor=None, reason='', metadata=None):
        """
        Creates an immutable SubscriptionAuditLog record for invoices, payments, allocations, and credit/debit notes.
        """
        return cls.log_subscription_lifecycle(
            subscription=subscription,
            action=action,
            actor=actor,
            old_state='',
            new_state='',
            reason=reason,
            metadata=metadata
        )

    @classmethod
    def log_dunning_event(cls, subscription, attempt_number, status, invoice=None, gateway_transaction_id='', idempotency_key=None, error_code='', error_message='', next_retry_at=None):
        """
        Creates an immutable DunningLog record for dunning retry attempts and automated recoveries.
        """
        return DunningLog.objects.create(
            subscription=subscription,
            invoice=invoice,
            attempt_number=attempt_number,
            status=status,
            gateway_transaction_id=gateway_transaction_id or '',
            idempotency_key=idempotency_key,
            error_code=error_code or '',
            error_message=error_message or '',
            next_retry_at=next_retry_at
        )


class CustomerService:
    @staticmethod
    def generate_next_customer_number():
        """
        Calculates the next available candidate CUST-XXXXX across the entire database.
        Zero count()+1. Excludes malformed numbers from numeric sequence calculation.
        """
        existing_numbers = BillingCustomer.objects.values_list('customer_number', flat=True)
        max_seq = 0
        for num in existing_numbers:
            match = CUST_NUMBER_REGEX.match(num or '')
            if match:
                seq_val = int(match.group(1))
                if seq_val > max_seq:
                    max_seq = seq_val

        next_seq = max_seq + 1
        if next_seq > MAX_CUSTOMER_NUMBER_INT:
            raise ValidationError({
                "customer_number": "Customer number sequence limit reached (CUST-99999). Contact system administrator."
            })
        return f"CUST-{next_seq:05d}"

    @classmethod
    def create_customer(cls, organization, user, validated_data, max_retries=5):
        """
        Creates a new BillingCustomer with authoritative normalization, ownership assignment,
        and targeted uniqueness collision retry on customer_number.
        """
        data = validated_data.copy()

        # 1. Authoritative field normalizations
        if 'email' in data:
            data['email'] = (data['email'] or '').strip().lower()

        for addr_field in [
            'billing_address_line1', 'billing_address_line2',
            'billing_city', 'billing_state', 'billing_postal_code',
            'billing_country'
        ]:
            if addr_field in data:
                data[addr_field] = (data[addr_field] or '').strip()

        if 'tax_id' in data:
            data['tax_id'] = (data['tax_id'] or '').strip()

        if 'name' in data:
            data['name'] = (data['name'] or '').strip()

        if 'phone' in data:
            data['phone'] = (data['phone'] or '').strip()

        if 'default_payment_method_id' in data:
            val = (data['default_payment_method_id'] or '').strip()
            # Basic validation rejecting obvious raw card numbers
            digits = val.replace(' ', '').replace('-', '')
            if digits.isdigit() and len(digits) in (15, 16):
                raise ValidationError({
                    "default_payment_method_id": "Raw credit card numbers are prohibited. Supply a safe gateway payment method token."
                })
            data['default_payment_method_id'] = val

        # 2. Ownership metadata tracking
        metadata = data.get('metadata') or {}
        if not isinstance(metadata, dict):
            metadata = {}
        if user and user.is_authenticated:
            metadata['created_by_id'] = user.id
            metadata['created_by_username'] = user.username
        data['metadata'] = metadata

        # 3. Customer number determination
        explicit_number = data.get('customer_number')
        auto_generated = False
        if explicit_number:
            data['customer_number'] = explicit_number.strip()
            if not data['customer_number']:
                auto_generated = True
        else:
            auto_generated = True

        # 4. Atomic savepoint retry loop
        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    if auto_generated and not data.get('customer_number'):
                        data['customer_number'] = cls.generate_next_customer_number()

                    customer = BillingCustomer.objects.create(
                        organization=organization,
                        **data
                    )
                    return customer
            except IntegrityError as e:
                candidate = data.get('customer_number')
                err_str = str(e).lower()
                is_cust_num_collision = (
                    'customer_number' in err_str or
                    (candidate and BillingCustomer.objects.filter(customer_number=candidate).exists())
                )

                if auto_generated and is_cust_num_collision:
                    data.pop('customer_number', None)
                    if attempt == max_retries - 1:
                        raise ValidationError({
                            "customer_number": "Could not generate a unique customer number due to concurrent writes. Please try again."
                        })
                    continue

                # Unrelated integrity errors propagate immediately
                raise


class SubscriptionService:
    @staticmethod
    def generate_next_subscription_number():
        """
        Calculates the next available candidate SUB-XXXXX across the entire database.
        Zero count()+1. Excludes malformed numbers from numeric sequence calculation.
        """
        existing_numbers = Subscription.objects.values_list('subscription_number', flat=True)
        max_seq = 0
        for num in existing_numbers:
            match = SUB_NUMBER_REGEX.match(num or '')
            if match:
                seq_val = int(match.group(1))
                if seq_val > max_seq:
                    max_seq = seq_val

        next_seq = max_seq + 1
        if next_seq > MAX_SUBSCRIPTION_NUMBER_INT:
            raise ValidationError({
                "subscription_number": "Subscription number sequence limit reached (SUB-99999). Contact system administrator."
            })
        return f"SUB-{next_seq:05d}"

    @staticmethod
    def calculate_term_dates(start_date, billing_cycle='MONTHLY', term_months=1):
        """
        Calculates deterministic term_start, term_end, and next_billing_date for subscription.
        Handles month-end boundary clamping (e.g. Jan 31 -> Feb 28/29) and leap year cases.
        """
        if isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)

        billing_cycle = (billing_cycle or 'MONTHLY').upper()

        if billing_cycle == 'YEARLY':
            target_year = start_date.year + 1
            target_month = start_date.month
            target_day = start_date.day
            if target_month == 2 and target_day == 29 and not calendar.isleap(target_year):
                target_day = 28
            target_date = date(target_year, target_month, target_day)
        else:
            # MONTHLY
            target_year = start_date.year + (start_date.month + term_months - 1) // 12
            target_month = (start_date.month + term_months - 1) % 12 + 1
            max_days = calendar.monthrange(target_year, target_month)[1]
            target_day = min(start_date.day, max_days)
            target_date = date(target_year, target_month, target_day)

        current_term_start = start_date
        current_term_end = target_date - timedelta(days=1)
        next_billing_date = target_date

        return current_term_start, current_term_end, next_billing_date

    @classmethod
    def create_subscription(cls, organization, user, validated_data, max_retries=5):
        """
        Creates a new Subscription header with ownership tracking, automatic SUB-XXXXX numbering,
        and term date derivation.
        """
        data = validated_data.copy()

        # 1. Ownership metadata tracking
        metadata = data.get('metadata') or {}
        if not isinstance(metadata, dict):
            metadata = {}
        if user and user.is_authenticated:
            metadata['created_by_id'] = user.id
            metadata['created_by_username'] = user.username
        data['metadata'] = metadata

        # 2. Extract billing_cycle parameter if provided for term calculation
        billing_cycle = data.pop('billing_cycle', 'MONTHLY')

        # 3. Currency fallback
        customer = data.get('customer')
        if not data.get('currency') and customer:
            data['currency'] = customer.currency or 'USD'

        # 4. Payment terms validation
        payment_terms_days = data.get('payment_terms_days', 0)
        if payment_terms_days is not None and int(payment_terms_days) < 0:
            raise ValidationError({
                "payment_terms_days": "payment_terms_days must be a non-negative integer."
            })

        # 5. Term dates calculation if current_term_start is provided but end/next_billing not set
        term_start = data.get('current_term_start')
        if term_start:
            calc_start, calc_end, calc_next = cls.calculate_term_dates(term_start, billing_cycle)
            if not data.get('current_term_end'):
                data['current_term_end'] = calc_end
            if not data.get('next_billing_date'):
                data['next_billing_date'] = calc_next

        # 6. Subscription number determination
        explicit_number = data.get('subscription_number')
        auto_generated = False
        if explicit_number:
            data['subscription_number'] = explicit_number.strip()
            if not data['subscription_number']:
                auto_generated = True
        else:
            auto_generated = True

        # 7. Atomic savepoint retry loop
        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    if auto_generated and not data.get('subscription_number'):
                        data['subscription_number'] = cls.generate_next_subscription_number()

                    subscription = Subscription.objects.create(**data)
                    BillingAuditService.log_subscription_lifecycle(
                        subscription=subscription,
                        action='SUBSCRIPTION_CREATED',
                        actor=user,
                        old_state='',
                        new_state=subscription.status,
                        reason='Initial subscription creation',
                        metadata={
                            'subscription_number': subscription.subscription_number,
                            'customer_id': subscription.customer_id,
                            'collection_method': subscription.collection_method,
                            'current_term_start': str(subscription.current_term_start) if subscription.current_term_start else None,
                            'current_term_end': str(subscription.current_term_end) if subscription.current_term_end else None,
                        }
                    )
                    return subscription
            except IntegrityError as e:
                candidate = data.get('subscription_number')
                err_str = str(e).lower()
                is_sub_num_collision = (
                    'subscription_number' in err_str or
                    (candidate and Subscription.objects.filter(subscription_number=candidate).exists())
                )

                if auto_generated and is_sub_num_collision:
                    data.pop('subscription_number', None)
                    if attempt == max_retries - 1:
                        raise ValidationError({
                            "subscription_number": "Could not generate a unique subscription number due to concurrent writes. Please try again."
                        })
                    continue

                raise


class SubscriptionItemService:
    @classmethod
    def recalculate_subscription_mrr_arr(cls, subscription, as_of_date=None):
        """
        Recalculates cached_mrr and cached_arr on Subscription header based on active line items.
        Option 2A: Item contributes to MRR only when start_date <= eval_date <= end_date (or null dates).
        Period conversion:
        - Monthly items: (unit_price * quantity - discount_amount)
        - Yearly items: (unit_price * quantity - discount_amount) / 12
        - One-time items: 0 MRR contribution
        """
        if as_of_date:
            eval_date = date.fromisoformat(as_of_date) if isinstance(as_of_date, str) else as_of_date
        elif subscription.current_term_start and subscription.current_term_end:
            today = date.today()
            if subscription.current_term_start <= today <= subscription.current_term_end:
                eval_date = today
            else:
                eval_date = subscription.current_term_start
        else:
            eval_date = date.today()

        total_mrr = Decimal('0.00')

        items = SubscriptionItem.objects.filter(subscription=subscription).select_related('plan', 'addon')
        for item in items:
            # Active date check:
            if item.start_date and item.start_date > eval_date:
                continue
            if item.end_date and item.end_date < eval_date:
                continue

            unit_price = item.unit_price or Decimal('0.00')
            qty = item.quantity or 1
            discount = item.discount_amount or Decimal('0.00')
            item_total = max(Decimal('0.00'), (unit_price * Decimal(qty)) - discount)

            cycle = 'monthly'
            if item.item_type == 'PLAN' and item.plan:
                cycle = (item.plan.billing_cycle or 'monthly').lower()
            elif item.item_type == 'ADDON' and item.addon:
                cycle = (item.addon.billing_cycle or 'monthly').lower()

            if cycle == 'yearly':
                mrr_contribution = (item_total / Decimal('12.00')).quantize(Decimal('0.01'))
            elif cycle == 'one_time':
                mrr_contribution = Decimal('0.00')
            else:
                mrr_contribution = item_total.quantize(Decimal('0.01'))

            total_mrr += mrr_contribution

        subscription.cached_mrr = total_mrr.quantize(Decimal('0.01'))
        subscription.cached_arr = (total_mrr * Decimal('12.00')).quantize(Decimal('0.01'))
        subscription.save(update_fields=['cached_mrr', 'cached_arr', 'updated_at'])
        return subscription.cached_mrr, subscription.cached_arr

    @classmethod
    def add_item_to_subscription(cls, subscription, user, validated_data):
        """
        Attaches a SubscriptionItem to a Subscription header.
        - Option 1A: Maximum 1 PLAN item per subscription. Attaching a new PLAN replaces any existing PLAN item transactionally.
        - Historical snapshot: Copies plan.price or addon.price to unit_price if not explicitly specified.
        - Quantity validation: Positive integer, checks addon.max_quantity.
        - Co-terminated start/end dates from subscription if not provided.
        - Recalculates MRR/ARR transactionally.
        """
        data = validated_data.copy()
        item_type = data.get('item_type')
        plan = data.get('plan')
        addon = data.get('addon')
        quantity = data.get('quantity', 1)

        if quantity is None or quantity < 1:
            raise ValidationError({"quantity": "Quantity must be a positive integer."})

        # Validate item type consistency
        if item_type == 'PLAN':
            if not plan or addon:
                raise ValidationError({"plan": "Subscription item of type 'PLAN' must have a valid plan and no addon."})
            # Snapshot pricing if unit_price not explicitly set
            if 'unit_price' not in data or data['unit_price'] is None:
                data['unit_price'] = plan.price
        elif item_type == 'ADDON':
            if not addon or plan:
                raise ValidationError({"addon": "Subscription item of type 'ADDON' must have a valid addon and no plan."})
            # Quantity cap check
            if addon.max_quantity and quantity > addon.max_quantity:
                raise ValidationError({"quantity": f"Quantity exceeds maximum allowed for add-on '{addon.name}' (max {addon.max_quantity})."})
            # Snapshot pricing if unit_price not explicitly set
            if 'unit_price' not in data or data['unit_price'] is None:
                data['unit_price'] = addon.price
        else:
            raise ValidationError({"item_type": "Invalid item_type. Must be 'PLAN' or 'ADDON'."})

        # Set default start/end dates from subscription if omitted
        if 'start_date' not in data or not data['start_date']:
            data['start_date'] = subscription.current_term_start
        if 'end_date' not in data or not data['end_date']:
            data['end_date'] = subscription.current_term_end

        with transaction.atomic():
            # Option 1A: Transactional replacement if item_type == 'PLAN'
            if item_type == 'PLAN':
                subscription.items.filter(item_type='PLAN').delete()

            item = SubscriptionItem.objects.create(
                subscription=subscription,
                **data
            )
            cls.recalculate_subscription_mrr_arr(subscription)
            return item

    @classmethod
    def remove_item_from_subscription(cls, subscription, item_id):
        """
        Removes a SubscriptionItem from a Subscription header and recalculates MRR/ARR transactionally.
        """
        with transaction.atomic():
            try:
                item = SubscriptionItem.objects.get(subscription=subscription, id=int(item_id))
            except (SubscriptionItem.DoesNotExist, ValueError, TypeError):
                raise ValidationError({"detail": "Subscription item not found."})

            item.delete()
            cls.recalculate_subscription_mrr_arr(subscription)


class SubscriptionStateMachineService:
    ALLOWED_TRANSITIONS = {
        'DRAFT': ['TRIAL', 'FUTURE', 'LIVE', 'CANCELLED'],
        'FUTURE': ['LIVE', 'CANCELLED'],
        'TRIAL': ['LIVE', 'CANCELLED'],
        'LIVE': ['PAUSED', 'NON_RENEWING', 'PAST_DUE', 'CANCELLED'],
        'PAUSED': ['LIVE', 'CANCELLED'],
        'NON_RENEWING': ['LIVE', 'CANCELLED'],
        'PAST_DUE': ['LIVE', 'UNPAID', 'CANCELLED'],
        'UNPAID': ['LIVE', 'CANCELLED'],
        'CANCELLED': [],  # Terminal state
    }

    @classmethod
    def transition(cls, subscription, to_status, user=None, reason="", metadata=None):
        """
        Authoritative service method executing subscription lifecycle state transitions.
        Enforces approved transition matrix, terminal state invariants, reason validation,
        metadata updates, and atomic SubscriptionAuditLog creation.
        """
        to_status = (to_status or '').upper().strip()
        old_status = subscription.status

        # 1. Reject same-status transitions (No-op rejection with HTTP 400 equivalent ValidationError)
        if old_status == to_status:
            raise ValidationError({"to_status": f"Subscription is already in status '{to_status}'."})

        # 2. Check transition matrix allowed paths
        valid_targets = cls.ALLOWED_TRANSITIONS.get(old_status, [])
        if to_status not in valid_targets:
            if old_status == 'CANCELLED':
                raise ValidationError({"to_status": "Subscription is CANCELLED (terminal state) and cannot transition to any other status."})
            raise ValidationError({"to_status": f"Transition from '{old_status}' to '{to_status}' is prohibited."})

        # 3. Validate transition-specific required fields
        reason_clean = (reason or '').strip()
        if to_status == 'CANCELLED' and not reason_clean:
            raise ValidationError({"reason": "A reason is required when cancelling a subscription."})
        if to_status == 'PAUSED' and not reason_clean:
            raise ValidationError({"reason": "A reason is required when pausing a subscription."})

        # 4. Atomic status update and audit log creation
        with transaction.atomic():
            subscription.status = to_status

            if to_status == 'CANCELLED':
                subscription.cancelled_at = timezone.now()
            elif to_status == 'PAUSED':
                subscription.pause_date = date.today()
            elif to_status == 'LIVE' and old_status == 'PAUSED':
                subscription.resume_date = date.today()
            elif to_status == 'NON_RENEWING':
                subscription.cancel_at_period_end = True
            elif to_status == 'LIVE' and old_status == 'NON_RENEWING':
                subscription.cancel_at_period_end = False

            subscription.save()

            audit_metadata = metadata.copy() if isinstance(metadata, dict) else {}
            if user and user.is_authenticated:
                audit_metadata['actor_username'] = user.username

            BillingAuditService.log_subscription_lifecycle(
                subscription=subscription,
                action='STATE_TRANSITION',
                actor=user,
                old_state=old_status,
                new_state=to_status,
                reason=reason_clean,
                metadata=audit_metadata
            )

            return subscription


class SubscriptionLifecycleService:
    @classmethod
    def cancel_subscription(cls, subscription, cancel_type='IMMEDIATE', reason='', user=None):
        """
        Cancels a subscription either IMMEDIATELY (LIVE -> CANCELLED)
        or at PERIOD_END (LIVE -> NON_RENEWING with cancel_at_period_end=True).
        Enforces mandatory reason and routes through SubscriptionStateMachineService.
        """
        cancel_type = (cancel_type or 'IMMEDIATE').upper().strip()
        reason_clean = (reason or '').strip()
        if not reason_clean:
            raise ValidationError({"reason": "A cancellation reason is required."})

        if cancel_type == 'IMMEDIATE':
            return SubscriptionStateMachineService.transition(
                subscription=subscription,
                to_status='CANCELLED',
                user=user,
                reason=reason_clean,
                metadata={"cancel_type": "IMMEDIATE"}
            )
        elif cancel_type == 'PERIOD_END':
            return SubscriptionStateMachineService.transition(
                subscription=subscription,
                to_status='NON_RENEWING',
                user=user,
                reason=reason_clean,
                metadata={"cancel_type": "PERIOD_END"}
            )
        else:
            raise ValidationError({"cancel_type": f"Invalid cancel_type '{cancel_type}'. Must be 'IMMEDIATE' or 'PERIOD_END'."})

    @classmethod
    def re_enable_auto_renewal(cls, subscription, user=None, reason=''):
        """
        Restores a NON_RENEWING subscription to LIVE and clears cancel_at_period_end.
        """
        reason_clean = (reason or 'Re-enabled auto-renewal').strip()
        return SubscriptionStateMachineService.transition(
            subscription=subscription,
            to_status='LIVE',
            user=user,
            reason=reason_clean,
            metadata={"action": "RE_ENABLE_AUTO_RENEWAL"}
        )

    @classmethod
    def pause_subscription(cls, subscription, reason='', user=None):
        """
        Pauses a LIVE subscription (LIVE -> PAUSED).
        Enforces mandatory reason and records pause_date = today.
        PAST_DUE and UNPAID subscriptions cannot be paused.
        """
        reason_clean = (reason or '').strip()
        if not reason_clean:
            raise ValidationError({"reason": "A reason is required when pausing a subscription."})

        if subscription.status in ('PAST_DUE', 'UNPAID'):
            raise ValidationError({"to_status": f"Subscriptions in '{subscription.status}' status cannot be paused. Please settle outstanding invoices first."})

        return SubscriptionStateMachineService.transition(
            subscription=subscription,
            to_status='PAUSED',
            user=user,
            reason=reason_clean,
            metadata={"pause_date": date.today().isoformat()}
        )

    @classmethod
    def resume_subscription(cls, subscription, user=None, resume_date=None):
        """
        Resumes a PAUSED subscription (PAUSED -> LIVE).
        Applies approved OPTION A — TERM EXTENSION policy:
        - Calculates paused duration: N = (resume_date - pause_date).days (minimum 0 days).
        - Extends current_term_end forward by N days.
        - Extends next_billing_date forward by N days.
        - Preserves current_term_start and remaining subscription time.
        """
        if subscription.status != 'PAUSED':
            raise ValidationError({"to_status": f"Only PAUSED subscriptions can be resumed. Current status is '{subscription.status}'."})

        today = resume_date or date.today()
        if isinstance(today, str):
            today = date.fromisoformat(today)

        pause_d = subscription.pause_date or today
        paused_duration_days = max(0, (today - pause_d).days)

        with transaction.atomic():
            sub = SubscriptionStateMachineService.transition(
                subscription=subscription,
                to_status='LIVE',
                user=user,
                reason=f"Subscription resumed after {paused_duration_days} days paused.",
                metadata={
                    "resume_date": today.isoformat(),
                    "paused_duration_days": paused_duration_days
                }
            )

            # Apply term extension if duration > 0
            update_fields = []
            if sub.resume_date != today:
                sub.resume_date = today
                update_fields.append('resume_date')

            if paused_duration_days > 0:
                if sub.current_term_end:
                    sub.current_term_end = sub.current_term_end + timedelta(days=paused_duration_days)
                    update_fields.append('current_term_end')
                if sub.next_billing_date:
                    sub.next_billing_date = sub.next_billing_date + timedelta(days=paused_duration_days)
                    update_fields.append('next_billing_date')

            if update_fields:
                sub.save(update_fields=update_fields)

            return sub


INV_NUMBER_REGEX = re.compile(r'^INV-(\d{4})-(\d{5})$')
MAX_INVOICE_NUMBER_INT = 99999


class InvoicingEngineService:
    @staticmethod
    def generate_next_invoice_number():
        """
        Calculates the next available candidate INV-YYYY-XXXXX across the entire database.
        Zero count()+1. Excludes malformed numbers from numeric sequence calculation.
        """
        current_year = date.today().year
        pattern = f"^INV-{current_year}-(\\d{{5}})$"
        year_regex = re.compile(pattern)

        existing_numbers = Invoice.objects.values_list('invoice_number', flat=True)
        max_seq = 0
        for num in existing_numbers:
            match = year_regex.match(num or '')
            if match:
                seq_val = int(match.group(1))
                if seq_val > max_seq:
                    max_seq = seq_val

        next_seq = max_seq + 1
        if next_seq > MAX_INVOICE_NUMBER_INT:
            raise ValidationError({
                "invoice_number": f"Invoice number sequence limit reached (INV-{current_year}-99999). Contact system administrator."
            })
        return f"INV-{current_year}-{next_seq:05d}"

    @classmethod
    def generate_invoice(cls, subscription, billing_period_start=None, billing_period_end=None, issue_date=None, due_date=None, user=None, max_retries=5):
        """
        Authoritative service method generating an Invoice from a Subscription and its active SubscriptionItems.
        - Deterministic idempotency key: inv_sub_<subscription_id>_period_<billing_period_start>
        - Guarantees zero duplicate invoices for the same subscription and period.
        - If an invoice with the matching idempotency key already exists, returns the existing invoice without creating duplicates.
        - Race-safe atomic execution using transaction.atomic() + IntegrityError fallback.
        - Server calculates line subtotals, line discounts, line taxes, subtotal, discount_total, tax_total, total_amount, paid_amount=0.00, balance=total_amount.
        - Newly generated status: POSTED.
        - Default due date: issue_date + payment_terms_days.
        """
        # 1. Billing Period & Date Determinism
        if not billing_period_start:
            billing_period_start = subscription.current_term_start or date.today()
        if isinstance(billing_period_start, str):
            billing_period_start = date.fromisoformat(billing_period_start)

        if not billing_period_end:
            billing_period_end = subscription.current_term_end or billing_period_start
        if isinstance(billing_period_end, str):
            billing_period_end = date.fromisoformat(billing_period_end)

        if not issue_date:
            issue_date = date.today()
        if isinstance(issue_date, str):
            issue_date = date.fromisoformat(issue_date)

        if not due_date:
            terms_days = subscription.payment_terms_days or 0
            due_date = issue_date + timedelta(days=terms_days)
        elif isinstance(due_date, str):
            due_date = date.fromisoformat(due_date)

        # 2. Deterministic Idempotency Key
        idempotency_key = f"inv_sub_{subscription.id}_period_{billing_period_start.isoformat()}"

        # 3. Check if invoice with this idempotency key already exists
        existing_inv = Invoice.objects.filter(idempotency_key=idempotency_key).first()
        if existing_inv:
            return existing_inv

        # 4. Fetch active SubscriptionItems
        items = subscription.items.select_related('plan', 'addon').all()
        if not items.exists():
            raise ValidationError({"subscription": "Cannot generate invoice for a subscription with no line items."})

        # 5. Atomic retry loop for candidate invoice_number uniqueness collisions
        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    # Double-check idempotency inside savepoint/transaction
                    existing_inv_tx = Invoice.objects.filter(idempotency_key=idempotency_key).first()
                    if existing_inv_tx:
                        return existing_inv_tx

                    invoice_num = cls.generate_next_invoice_number()

                    # Initial Invoice Header creation
                    invoice = Invoice.objects.create(
                        invoice_number=invoice_num,
                        subscription=subscription,
                        customer=subscription.customer,
                        billing_period_start=billing_period_start,
                        billing_period_end=billing_period_end,
                        issue_date=issue_date,
                        due_date=due_date,
                        status='POSTED',
                        idempotency_key=idempotency_key,
                        subtotal=Decimal('0.00'),
                        discount_total=Decimal('0.00'),
                        tax_total=Decimal('0.00'),
                        total_amount=Decimal('0.00'),
                        paid_amount=Decimal('0.00'),
                        balance=Decimal('0.00')
                    )

                    running_subtotal = Decimal('0.00')
                    running_discount = Decimal('0.00')
                    running_tax = Decimal('0.00')

                    # Derive InvoiceLine records from SubscriptionItems
                    for item in items:
                        # Active period check
                        if item.start_date and item.start_date > billing_period_end:
                            continue
                        if item.end_date and item.end_date < billing_period_start:
                            continue

                        if item.item_type == 'PLAN' and item.plan:
                            desc = f"PLAN: {item.plan.name}"
                        elif item.item_type == 'ADDON' and item.addon:
                            desc = f"ADDON: {item.addon.name}"
                        else:
                            desc = "Subscription Line Item"

                        qty = item.quantity or 1
                        unit_price = (item.unit_price or Decimal('0.00')).quantize(Decimal('0.01'))
                        line_subtotal = (unit_price * Decimal(qty)).quantize(Decimal('0.01'))
                        line_discount = (item.discount_amount or Decimal('0.00')).quantize(Decimal('0.01'))
                        line_tax = Decimal('0.00')
                        line_total = max(Decimal('0.00'), line_subtotal - line_discount + line_tax).quantize(Decimal('0.01'))

                        InvoiceLine.objects.create(
                            invoice=invoice,
                            subscription_item=item,
                            description=desc,
                            quantity=qty,
                            unit_price=unit_price,
                            subtotal=line_subtotal,
                            discount_amount=line_discount,
                            tax_amount=line_tax,
                            total_amount=line_total
                        )

                        running_subtotal += line_subtotal
                        running_discount += line_discount
                        running_tax += line_tax

                    final_total = max(Decimal('0.00'), running_subtotal - running_discount + running_tax).quantize(Decimal('0.01'))

                    invoice.subtotal = running_subtotal.quantize(Decimal('0.01'))
                    invoice.discount_total = running_discount.quantize(Decimal('0.01'))
                    invoice.tax_total = running_tax.quantize(Decimal('0.01'))
                    invoice.total_amount = final_total
                    invoice.paid_amount = Decimal('0.00')
                    invoice.balance = final_total
                    invoice.save()

                    return invoice

            except IntegrityError as e:
                err_str = str(e).lower()

                # If collision was on idempotency_key due to concurrent request, fetch existing invoice
                if 'idempotency_key' in err_str or Invoice.objects.filter(idempotency_key=idempotency_key).exists():
                    existing = Invoice.objects.filter(idempotency_key=idempotency_key).first()
                    if existing:
                        return existing

                # Otherwise invoice_number collision retry
                if attempt == max_retries - 1:
                    raise ValidationError({
                        "invoice_number": "Could not generate a unique invoice number due to concurrent writes. Please try again."
                    })
                continue

    @classmethod
    def generate_amendment_proration_invoice(cls, subscription, proration_result, effective_date, user=None, max_retries=5):
        """
        Generates a positive proration invoice for subscription upgrade amendments.
        - Deterministic idempotency key: inv_sub_<sub_id>_amend_<effective_date>_<fingerprint>
        - Canonical fingerprint incorporates plan changes and all sorted add-on modifications.
        - Guarantees zero duplicate invoices for repeated submissions of the exact same amendment.
        - Guarantees distinct invoices for different same-day amendments even with identical net amounts.
        - Invoice line items reflect prorated charges and unconsumed credit discounts.
        - Total invoice amount equals net proration (> 0).
        - Enforces Rule 9: No negative invoice lines.
        - Status: POSTED.
        """
        net_amount = proration_result['net_amount_decimal']
        if net_amount <= Decimal('0.00'):
            return None

        new_plan_id = proration_result['new_plan']['plan_id'] if proration_result.get('new_plan') else None

        addon_changes = []
        for a in proration_result.get('add_on_changes', []):
            aid = a.get('addon_id')
            act = (a.get('action') or '').upper().strip()
            qty = a.get('added_quantity') if act == 'ADD' else a.get('final_quantity', 0)
            addon_changes.append((aid, act, qty))
        addon_changes.sort(key=lambda x: (x[0] if x[0] is not None else 0, x[1], x[2]))

        eff_date_str = effective_date.isoformat() if hasattr(effective_date, 'isoformat') else str(effective_date)
        net_cents = int(net_amount * 100)

        payload_dict = {
            "sub_id": subscription.id,
            "effective_date": eff_date_str,
            "new_plan_id": new_plan_id,
            "add_ons": addon_changes,
            "net_cents": net_cents
        }
        payload_bytes = json.dumps(payload_dict, sort_keys=True).encode('utf-8')
        fingerprint = hashlib.sha256(payload_bytes).hexdigest()[:16]

        idempotency_key = f"inv_sub_{subscription.id}_amend_{eff_date_str}_{fingerprint}"

        existing = Invoice.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

        issue_date = date.today()
        terms_days = subscription.payment_terms_days or 0
        due_date = issue_date + timedelta(days=terms_days)

        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    existing_tx = Invoice.objects.filter(idempotency_key=idempotency_key).first()
                    if existing_tx:
                        return existing_tx

                    invoice_num = cls.generate_next_invoice_number()
                    invoice = Invoice.objects.create(
                        invoice_number=invoice_num,
                        subscription=subscription,
                        customer=subscription.customer,
                        billing_period_start=effective_date,
                        billing_period_end=subscription.current_term_end,
                        issue_date=issue_date,
                        due_date=due_date,
                        status='POSTED',
                        idempotency_key=idempotency_key,
                        subtotal=Decimal('0.00'),
                        discount_total=Decimal('0.00'),
                        tax_total=Decimal('0.00'),
                        total_amount=Decimal('0.00'),
                        paid_amount=Decimal('0.00'),
                        balance=Decimal('0.00')
                    )

                    total_credit = Decimal(proration_result['total_credit'])
                    credit_remaining = total_credit
                    running_subtotal = Decimal('0.00')
                    running_discount = Decimal('0.00')

                    for c_item in proration_result['charges']:
                        c_amt = Decimal(str(c_item['amount']))
                        line_discount = min(credit_remaining, c_amt)
                        credit_remaining -= line_discount

                        line_subtotal = c_amt
                        line_total = max(Decimal('0.00'), line_subtotal - line_discount).quantize(Decimal('0.01'))

                        InvoiceLine.objects.create(
                            invoice=invoice,
                            subscription_item=None,
                            description=c_item['description'],
                            quantity=c_item.get('quantity', 1),
                            unit_price=c_amt,
                            subtotal=line_subtotal,
                            discount_amount=line_discount,
                            tax_amount=Decimal('0.00'),
                            total_amount=line_total
                        )
                        running_subtotal += line_subtotal
                        running_discount += line_discount

                    final_total = max(Decimal('0.00'), running_subtotal - running_discount).quantize(Decimal('0.01'))

                    invoice.subtotal = running_subtotal.quantize(Decimal('0.01'))
                    invoice.discount_total = running_discount.quantize(Decimal('0.01'))
                    invoice.tax_total = Decimal('0.00')
                    invoice.total_amount = final_total
                    invoice.paid_amount = Decimal('0.00')
                    invoice.balance = final_total
                    invoice.save()

                    return invoice
            except IntegrityError as e:
                err_str = str(e).lower()
                if 'idempotency_key' in err_str or Invoice.objects.filter(idempotency_key=idempotency_key).exists():
                    existing = Invoice.objects.filter(idempotency_key=idempotency_key).first()
                    if existing:
                        return existing
                if attempt == max_retries - 1:
                    raise ValidationError({
                        "invoice_number": "Could not generate a unique invoice number due to concurrent writes. Please try again."
                    })
                continue


class ProrationService:
    @classmethod
    def calculate_proration(cls, subscription, new_plan_id=None, add_ons=None, effective_date=None):
        """
        Authoritative server-side proration calculation engine.
        Strictly read-only: performs zero DB writes, creates no records.

        Day-count convention:
        D_total = (current_term_end - current_term_start).days + 1
        D_consumed = (effective_date - current_term_start).days
        D_remaining = (current_term_end - effective_date).days + 1
        Invariant: D_consumed + D_remaining == D_total
        """
        if subscription.status != 'LIVE':
            raise ValidationError({"subscription": f"Only LIVE subscriptions can be amended. Current status is '{subscription.status}'."})

        if not subscription.current_term_start or not subscription.current_term_end:
            raise ValidationError({"subscription": "Subscription must have active current_term_start and current_term_end."})

        term_start = subscription.current_term_start
        term_end = subscription.current_term_end

        if effective_date is None:
            effective_date = date.today()
        elif isinstance(effective_date, str):
            try:
                effective_date = date.fromisoformat(effective_date)
            except ValueError:
                raise ValidationError({"effective_date": "Invalid effective_date format. Must be YYYY-MM-DD."})

        if effective_date < term_start or effective_date > term_end:
            raise ValidationError({"effective_date": f"Effective date ({effective_date}) must be within the current term ({term_start} to {term_end})."})

        d_total = (term_end - term_start).days + 1
        d_consumed = (effective_date - term_start).days
        d_remaining = (term_end - effective_date).days + 1

        if d_total <= 0 or d_remaining <= 0:
            raise ValidationError({"effective_date": "Invalid term boundary for proration calculation."})

        d_total_dec = Decimal(str(d_total))
        d_remaining_dec = Decimal(str(d_remaining))

        # 1. Inspect existing active items
        active_items = subscription.items.select_related('plan', 'addon').all()
        existing_plan_item = None
        existing_addons_map = {}  # addon_id -> item

        for item in active_items:
            if item.item_type == 'PLAN' and item.plan:
                existing_plan_item = item
            elif item.item_type == 'ADDON' and item.addon:
                existing_addons_map[item.addon.id] = item

        credits = []
        charges = []
        has_plan_change = False
        has_addon_changes = False

        # 2. Plan Amendment Proration
        old_plan_data = None
        new_plan_data = None
        target_plan = None

        if new_plan_id is not None:
            try:
                target_plan = PricingPlan.objects.get(id=int(new_plan_id))
            except (PricingPlan.DoesNotExist, ValueError, TypeError):
                raise ValidationError({"new_plan_id": "Selected plan does not exist."})

            if not target_plan.is_active:
                raise ValidationError({"new_plan_id": f"Plan '{target_plan.name}' is inactive."})

            current_plan_id = existing_plan_item.plan_id if existing_plan_item else None
            if target_plan.id != current_plan_id:
                has_plan_change = True

        if has_plan_change:
            # Unconsumed credit for old plan using historical snapshot price
            if existing_plan_item:
                old_unit_price = existing_plan_item.unit_price or Decimal('0.00')
                old_qty = Decimal(str(existing_plan_item.quantity or 1))
                old_discount = existing_plan_item.discount_amount or Decimal('0.00')
                old_term_cost = (old_unit_price * old_qty) - old_discount
                old_daily_rate = (old_term_cost / d_total_dec).quantize(Decimal('0.000001'))
                old_plan_credit = ((old_term_cost / d_total_dec) * d_remaining_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

                old_plan_data = {
                    "item_id": existing_plan_item.id,
                    "plan_id": existing_plan_item.plan.id,
                    "name": existing_plan_item.plan.name,
                    "unit_price": str(old_unit_price),
                    "quantity": existing_plan_item.quantity,
                    "discount_amount": str(old_discount),
                    "term_cost": str(old_term_cost),
                    "daily_rate": str(old_daily_rate),
                    "unconsumed_credit": str(old_plan_credit)
                }
                credits.append({
                    "type": "PLAN",
                    "description": f"Credit: Unused {existing_plan_item.plan.name}",
                    "amount": old_plan_credit,
                    "item_id": existing_plan_item.id
                })

            # Charge for new plan for remaining period at current catalog price
            new_unit_price = (target_plan.price or Decimal('0.00')).quantize(Decimal('0.01'))
            new_term_cost = new_unit_price * Decimal('1')
            new_daily_rate = (new_term_cost / d_total_dec).quantize(Decimal('0.000001'))
            new_plan_charge = ((new_term_cost / d_total_dec) * d_remaining_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            new_plan_data = {
                "plan_id": target_plan.id,
                "name": target_plan.name,
                "unit_price": str(new_unit_price),
                "quantity": 1,
                "term_cost": str(new_term_cost),
                "daily_rate": str(new_daily_rate),
                "prorated_charge": str(new_plan_charge)
            }
            charges.append({
                "type": "PLAN",
                "description": f"Charge: {target_plan.name} ({d_remaining} days)",
                "amount": new_plan_charge,
                "plan_id": target_plan.id
            })
        else:
            if existing_plan_item:
                old_plan_data = {
                    "item_id": existing_plan_item.id,
                    "plan_id": existing_plan_item.plan.id,
                    "name": existing_plan_item.plan.name,
                    "unit_price": str(existing_plan_item.unit_price),
                    "quantity": existing_plan_item.quantity,
                    "unconsumed_credit": "0.00"
                }

        # 3. Add-on Amendments
        add_on_results = []
        if add_ons and isinstance(add_ons, list):
            for idx, ad_req in enumerate(add_ons):
                addon_id = ad_req.get('addon_id')
                action = (ad_req.get('action') or '').upper().strip()
                req_qty = ad_req.get('quantity')

                if not addon_id:
                    raise ValidationError({"add_ons": f"Add-on at index {idx} missing required field 'addon_id'."})

                try:
                    addon_obj = AddOn.objects.get(id=int(addon_id))
                except (AddOn.DoesNotExist, ValueError, TypeError):
                    raise ValidationError({"add_ons": f"Add-on with id {addon_id} does not exist."})

                existing_item = existing_addons_map.get(addon_obj.id)
                current_qty = existing_item.quantity if existing_item else 0
                current_unit_price = existing_item.unit_price if existing_item else addon_obj.price

                if action == 'ADD':
                    if req_qty is None or int(req_qty) < 1:
                        raise ValidationError({"add_ons": f"Quantity to ADD for '{addon_obj.name}' must be at least 1."})
                    add_qty = int(req_qty)
                    final_qty = current_qty + add_qty

                    if addon_obj.max_quantity and final_qty > addon_obj.max_quantity:
                        raise ValidationError({"add_ons": f"Resulting quantity ({final_qty}) exceeds max_quantity ({addon_obj.max_quantity}) for add-on '{addon_obj.name}'."})

                    # Charge only newly added quantity for remaining days
                    add_unit_price = (addon_obj.price or Decimal('0.00')).quantize(Decimal('0.01'))
                    addon_term_cost = add_unit_price * Decimal(str(add_qty))
                    addon_charge = ((addon_term_cost / d_total_dec) * d_remaining_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

                    charges.append({
                        "type": "ADDON",
                        "description": f"Add-on: {addon_obj.name} (+{add_qty}) ({d_remaining} days)",
                        "amount": addon_charge,
                        "addon_id": addon_obj.id,
                        "quantity": add_qty
                    })
                    add_on_results.append({
                        "addon_id": addon_obj.id,
                        "name": addon_obj.name,
                        "action": "ADD",
                        "current_quantity": current_qty,
                        "added_quantity": add_qty,
                        "final_quantity": final_qty,
                        "unit_price": str(add_unit_price),
                        "prorated_charge": str(addon_charge),
                        "unconsumed_credit": "0.00"
                    })
                    has_addon_changes = True

                elif action == 'CHANGE':
                    if req_qty is None or int(req_qty) < 1:
                        raise ValidationError({"add_ons": f"Desired quantity for '{addon_obj.name}' must be at least 1."})
                    new_target_qty = int(req_qty)

                    if addon_obj.max_quantity and new_target_qty > addon_obj.max_quantity:
                        raise ValidationError({"add_ons": f"Desired quantity ({new_target_qty}) exceeds max_quantity ({addon_obj.max_quantity}) for add-on '{addon_obj.name}'."})

                    if new_target_qty == current_qty:
                        continue  # No change for this add-on

                    # Credit old quantity at historical snapshot price
                    addon_credit = Decimal('0.00')
                    if existing_item and current_qty > 0:
                        old_addon_term_cost = (existing_item.unit_price or Decimal('0.00')) * Decimal(str(current_qty))
                        addon_credit = ((old_addon_term_cost / d_total_dec) * d_remaining_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                        credits.append({
                            "type": "ADDON",
                            "description": f"Credit: Unused {addon_obj.name} (x{current_qty})",
                            "amount": addon_credit,
                            "addon_id": addon_obj.id,
                            "item_id": existing_item.id
                        })

                    # Charge new quantity at current catalog price
                    new_unit_price = (addon_obj.price or Decimal('0.00')).quantize(Decimal('0.01'))
                    new_addon_term_cost = new_unit_price * Decimal(str(new_target_qty))
                    addon_charge = ((new_addon_term_cost / d_total_dec) * d_remaining_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    charges.append({
                        "type": "ADDON",
                        "description": f"Add-on: {addon_obj.name} (x{new_target_qty}) ({d_remaining} days)",
                        "amount": addon_charge,
                        "addon_id": addon_obj.id,
                        "quantity": new_target_qty
                    })

                    add_on_results.append({
                        "addon_id": addon_obj.id,
                        "name": addon_obj.name,
                        "action": "CHANGE",
                        "current_quantity": current_qty,
                        "final_quantity": new_target_qty,
                        "unit_price": str(new_unit_price),
                        "prorated_charge": str(addon_charge),
                        "unconsumed_credit": str(addon_credit)
                    })
                    has_addon_changes = True

                elif action == 'REMOVE':
                    if not existing_item or current_qty == 0:
                        raise ValidationError({"add_ons": f"Cannot REMOVE add-on '{addon_obj.name}' as it is not currently active on this subscription."})

                    old_addon_term_cost = (existing_item.unit_price or Decimal('0.00')) * Decimal(str(current_qty))
                    addon_credit = ((old_addon_term_cost / d_total_dec) * d_remaining_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    credits.append({
                        "type": "ADDON",
                        "description": f"Credit: Removed {addon_obj.name} (x{current_qty})",
                        "amount": addon_credit,
                        "addon_id": addon_obj.id,
                        "item_id": existing_item.id
                    })
                    add_on_results.append({
                        "addon_id": addon_obj.id,
                        "name": addon_obj.name,
                        "action": "REMOVE",
                        "current_quantity": current_qty,
                        "final_quantity": 0,
                        "unit_price": str(existing_item.unit_price),
                        "prorated_charge": "0.00",
                        "unconsumed_credit": str(addon_credit)
                    })
                    has_addon_changes = True
                else:
                    raise ValidationError({"add_ons": f"Invalid action '{action}'. Must be 'ADD', 'CHANGE', or 'REMOVE'."})

        # 4. Total and Net Proration
        total_credit = sum((c['amount'] for c in credits), Decimal('0.00')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_charge = sum((c['amount'] for c in charges), Decimal('0.00')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        net_proration = (total_charge - total_credit).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # 5. Check No-op
        if not has_plan_change and not has_addon_changes and net_proration == Decimal('0.00'):
            raise ValidationError({"detail": "The requested amendment produces no change to the subscription."})

        # 6. Projected MRR/ARR Calculation
        active_plan = target_plan if has_plan_change else (existing_plan_item.plan if existing_plan_item else None)
        plan_mrr = Decimal('0.00')
        if active_plan:
            plan_cycle = (active_plan.billing_cycle or 'monthly').lower()
            plan_p = (active_plan.price or Decimal('0.00')).quantize(Decimal('0.01'))
            if plan_cycle == 'yearly':
                plan_mrr = (plan_p / Decimal('12.00')).quantize(Decimal('0.01'))
            elif plan_cycle == 'one_time':
                plan_mrr = Decimal('0.00')
            else:
                plan_mrr = plan_p

        # Add-on MRR
        addon_mrr = Decimal('0.00')
        final_addons_dict = {
            ad_id: (item.addon, item.quantity, item.unit_price)
            for ad_id, item in existing_addons_map.items()
        }
        for res in add_on_results:
            aid = res['addon_id']
            fq = res['final_quantity']
            if fq > 0:
                a_obj = AddOn.objects.get(id=aid)
                up = Decimal(res['unit_price'])
                final_addons_dict[aid] = (a_obj, fq, up)
            else:
                final_addons_dict.pop(aid, None)

        for a_obj, qty, up in final_addons_dict.values():
            a_cycle = (a_obj.billing_cycle or 'monthly').lower()
            tot = (up * Decimal(str(qty))).quantize(Decimal('0.01'))
            if a_cycle == 'yearly':
                addon_mrr += (tot / Decimal('12.00')).quantize(Decimal('0.01'))
            elif a_cycle == 'one_time':
                pass
            else:
                addon_mrr += tot

        projected_mrr = (plan_mrr + addon_mrr).quantize(Decimal('0.01'))
        projected_arr = (projected_mrr * Decimal('12.00')).quantize(Decimal('0.01'))

        return {
            "subscription_id": subscription.id,
            "subscription_number": subscription.subscription_number,
            "currency": subscription.currency,
            "effective_date": effective_date.isoformat(),
            "current_term_start": term_start.isoformat(),
            "current_term_end": term_end.isoformat(),
            "term_days_total": d_total,
            "term_days_consumed": d_consumed,
            "term_days_remaining": d_remaining,
            "has_plan_change": has_plan_change,
            "has_addon_changes": has_addon_changes,
            "old_plan": old_plan_data,
            "new_plan": new_plan_data,
            "add_on_changes": add_on_results,
            "credits": [{**c, "amount": str(c['amount'])} for c in credits],
            "charges": [{**c, "amount": str(c['amount'])} for c in charges],
            "total_credit": str(total_credit),
            "total_charge": str(total_charge),
            "net_amount": str(net_proration),
            "net_amount_decimal": net_proration,
            "is_upgrade": net_proration > Decimal('0.00'),
            "is_downgrade": net_proration < Decimal('0.00'),
            "current_mrr": str(subscription.cached_mrr),
            "projected_new_mrr": str(projected_mrr),
            "projected_new_arr": str(projected_arr),
            "target_plan_id": target_plan.id if target_plan else None,
            "final_addons": [
                {"addon_id": aid, "quantity": qty, "unit_price": str(up)}
                for aid, (_, qty, up) in final_addons_dict.items()
            ]
        }


class SubscriptionAmendmentService:
    @classmethod
    def apply_amendment(cls, subscription, new_plan_id=None, add_ons=None, reason="", user=None, effective_date=None):
        """
        Executes a transactional subscription amendment.
        - Locks subscription row using select_for_update()
        - Re-validates state (LIVE only)
        - Re-calculates proration with current authoritative catalog prices
        - Applies line item changes:
            * Closes/replaces existing PLAN with exactly 1 active PLAN
            * Updates/creates co-terminated ADDON items
        - Recalculates cached_mrr and cached_arr
        - Creates SubscriptionChangeLog
        - Creates SubscriptionAuditLog
        - If net_proration > 0: generates positive proration invoice via InvoicingEngineService
        """
        reason_clean = (reason or '').strip()
        if not reason_clean:
            raise ValidationError({"reason": "An amendment reason is required."})

        sub_id = subscription.id

        with transaction.atomic():
            sub = Subscription.objects.select_for_update().select_related('customer').get(id=sub_id)

            if sub.status != 'LIVE':
                raise ValidationError({"subscription": f"Only LIVE subscriptions can be amended. Current status is '{sub.status}'."})

            proration = ProrationService.calculate_proration(
                subscription=sub,
                new_plan_id=new_plan_id,
                add_ons=add_ons,
                effective_date=effective_date
            )

            eff_date = date.fromisoformat(proration['effective_date'])
            net_amount = proration['net_amount_decimal']
            has_plan_change = proration['has_plan_change']
            has_addon_changes = proration['has_addon_changes']
            target_plan_id = proration.get('target_plan_id')
            final_addons = proration.get('final_addons', [])

            # 1. Apply Plan Amendment (Maintain Max 1 Active Plan)
            if has_plan_change and target_plan_id:
                target_plan = PricingPlan.objects.get(id=target_plan_id)
                sub.items.filter(item_type='PLAN').delete()

                SubscriptionItem.objects.create(
                    subscription=sub,
                    item_type='PLAN',
                    plan=target_plan,
                    quantity=1,
                    unit_price=target_plan.price,  # Snapshot current catalog price
                    discount_amount=Decimal('0.00'),
                    start_date=eff_date,
                    end_date=sub.current_term_end
                )

            # 2. Apply Add-on Amendments
            if has_addon_changes:
                sub.items.filter(item_type='ADDON').delete()

                for ad_data in final_addons:
                    addon_obj = AddOn.objects.get(id=ad_data['addon_id'])
                    SubscriptionItem.objects.create(
                        subscription=sub,
                        item_type='ADDON',
                        addon=addon_obj,
                        quantity=ad_data['quantity'],
                        unit_price=Decimal(ad_data['unit_price']),
                        discount_amount=Decimal('0.00'),
                        start_date=eff_date,
                        end_date=sub.current_term_end
                    )

            # 3. Recalculate cached MRR and ARR as of the amendment effective date
            SubscriptionItemService.recalculate_subscription_mrr_arr(sub, as_of_date=eff_date)
            sub.refresh_from_db()

            # 4. Determine Change Type
            if has_plan_change and not has_addon_changes:
                change_type = 'PLAN_UPGRADE' if net_amount > 0 else 'PLAN_DOWNGRADE'
            elif has_addon_changes and not has_plan_change:
                change_type = 'ADDON_AMENDMENT'
            else:
                change_type = 'PLAN_UPGRADE' if net_amount >= 0 else 'PLAN_DOWNGRADE'

            # 5. Create SubscriptionChangeLog
            change_details = {
                "reason": reason_clean,
                "effective_date": proration['effective_date'],
                "term_days_total": proration['term_days_total'],
                "term_days_remaining": proration['term_days_remaining'],
                "old_plan": proration['old_plan'],
                "new_plan": proration['new_plan'],
                "add_on_changes": proration['add_on_changes'],
                "total_credit": proration['total_credit'],
                "total_charge": proration['total_charge'],
                "net_amount": proration['net_amount'],
                "cached_mrr_after": str(sub.cached_mrr),
                "cached_arr_after": str(sub.cached_arr)
            }

            BillingAuditService.log_subscription_change(
                subscription=sub,
                change_type=change_type,
                proration_amount=net_amount,
                effective_date=eff_date,
                details=change_details,
                actor=user
            )

            # 6. Generate Proration Invoice if net_amount > 0 (Upgrade)
            proration_invoice = None
            if net_amount > Decimal('0.00'):
                proration_invoice = InvoicingEngineService.generate_amendment_proration_invoice(
                    subscription=sub,
                    proration_result=proration,
                    effective_date=eff_date,
                    user=user
                )

            # 7. Create SubscriptionAuditLog
            audit_metadata = {
                "change_type": change_type,
                "net_proration": str(net_amount),
                "effective_date": proration['effective_date'],
                "invoice_id": proration_invoice.id if proration_invoice else None,
                "invoice_number": proration_invoice.invoice_number if proration_invoice else None,
                "old_plan_id": proration['old_plan']['plan_id'] if proration['old_plan'] else None,
                "new_plan_id": proration['new_plan']['plan_id'] if proration['new_plan'] else None
            }

            BillingAuditService.log_subscription_lifecycle(
                subscription=sub,
                action='SUBSCRIPTION_AMENDED',
                actor=user,
                old_state='LIVE',
                new_state='LIVE',
                reason=reason_clean,
                metadata=audit_metadata
            )

            return {
                "subscription": sub,
                "proration": proration,
                "invoice": proration_invoice,
                "change_type": change_type
            }


PAY_NUMBER_REGEX = re.compile(r'^PAY-(\d{4})-(\d{5})$')
MAX_PAYMENT_NUMBER_INT = 99999


class PaymentService:
    @staticmethod
    def generate_next_payment_number():
        """
        Calculates the next available candidate PAY-YYYY-XXXXX across the entire database.
        Zero count()+1. Excludes malformed numbers from numeric sequence calculation.
        """
        current_year = date.today().year
        pattern = f"^PAY-{current_year}-(\\d{{5}})$"
        year_regex = re.compile(pattern)

        existing_numbers = Payment.objects.values_list('payment_number', flat=True)
        max_seq = 0
        for num in existing_numbers:
            match = year_regex.match(num or '')
            if match:
                seq_val = int(match.group(1))
                if seq_val > max_seq:
                    max_seq = seq_val

        next_seq = max_seq + 1
        if next_seq > MAX_PAYMENT_NUMBER_INT:
            raise ValidationError({
                "payment_number": f"Payment number sequence limit reached (PAY-{current_year}-99999). Contact system administrator."
            })
        return f"PAY-{current_year}-{next_seq:05d}"

    @classmethod
    def record_payment(cls, customer, amount, currency='USD', payment_method='CREDIT_CARD', payment_method_id='', gateway_transaction_id='', payment_date=None, notes='', max_retries=5):
        """
        Authoritative service method for recording payment receipts.
        - Validates amount > 0 (Decimal '0.01').
        - Validates customer tenant organization.
        - Generates atomic sequential payment_number (PAY-YYYY-XXXXX).
        - Initializes unallocated_amount = amount.
        - Default status = 'SUCCEEDED' for manually recorded receipts.
        - Checks gateway_transaction_id for reference duplicates if provided.
        """
        if amount is None:
            raise ValidationError({"amount": "Payment amount is required."})

        try:
            amount_decimal = Decimal(str(amount)).quantize(Decimal('0.01'))
        except Exception:
            raise ValidationError({"amount": "Invalid monetary amount format."})

        if amount_decimal <= Decimal('0.00'):
            raise ValidationError({"amount": "Payment amount must be greater than zero."})

        currency_clean = (currency or 'USD').strip().upper()

        if not payment_date:
            payment_date = date.today()
        elif isinstance(payment_date, str):
            payment_date = date.fromisoformat(payment_date)

        gateway_tx_clean = (gateway_transaction_id or '').strip()
        if gateway_tx_clean:
            if Payment.objects.filter(customer=customer, gateway_transaction_id=gateway_tx_clean).exists():
                raise ValidationError({"gateway_transaction_id": f"Payment with reference '{gateway_tx_clean}' has already been recorded for this customer."})

        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    pay_num = cls.generate_next_payment_number()
                    payment = Payment.objects.create(
                        payment_number=pay_num,
                        customer=customer,
                        amount=amount_decimal,
                        currency=currency_clean,
                        payment_method=payment_method or 'CREDIT_CARD',
                        payment_method_id=payment_method_id or '',
                        gateway_transaction_id=gateway_tx_clean,
                        status='SUCCEEDED',
                        payment_date=payment_date,
                        unallocated_amount=amount_decimal,
                        notes=notes or ''
                    )
                    return payment
            except IntegrityError:
                if attempt == max_retries - 1:
                    raise ValidationError({"payment_number": "Could not generate a unique payment number due to concurrent writes. Please try again."})
                continue


class PaymentAllocationService:
    @classmethod
    def allocate_payment(cls, payment_id, allocations_data, user=None):
        """
        Authoritative multi-invoice allocation service with atomic ledger settlement.
        - Wraps execution in single transaction.atomic()
        - Acquires select_for_update() row locks on Payment and target Invoices
        - Enforces allocation validation rules and updates balances/statuses atomically.
        """
        if not allocations_data or not isinstance(allocations_data, list):
            raise ValidationError({"allocations": "Allocations must be a non-empty list of allocation objects."})

        validated_items = []
        total_requested = Decimal('0.00')

        for idx, item in enumerate(allocations_data):
            inv_id = item.get('invoice_id')
            amt_raw = item.get('amount')
            if not inv_id:
                raise ValidationError({"allocations": f"Allocation item at index {idx} missing required 'invoice_id'."})
            try:
                amt_dec = Decimal(str(amt_raw)).quantize(Decimal('0.01'))
            except Exception:
                raise ValidationError({"allocations": f"Invalid amount format at allocation index {idx}."})

            if amt_dec <= Decimal('0.00'):
                raise ValidationError({"allocations": f"Allocation amount at index {idx} must be greater than zero."})

            validated_items.append((inv_id, amt_dec, item.get('notes', '')))
            total_requested += amt_dec

        with transaction.atomic():
            # 1. Lock Payment
            try:
                payment = Payment.objects.select_for_update().get(id=payment_id)
            except Payment.DoesNotExist:
                raise ValidationError({"payment": "Payment record not found."})

            if payment.unallocated_amount < total_requested:
                raise ValidationError({
                    "allocations": f"Total requested allocations (${total_requested}) exceed payment unallocated credit (${payment.unallocated_amount})."
                })

            # 2. Lock target Invoices
            invoice_ids = [v[0] for v in validated_items]
            invoices_qs = Invoice.objects.select_for_update().filter(id__in=invoice_ids)
            invoices_map = {inv.id: inv for inv in invoices_qs}

            missing_invoices = set(invoice_ids) - set(invoices_map.keys())
            if missing_invoices:
                raise ValidationError({"allocations": f"Invoice(s) {list(missing_invoices)} not found."})

            created_allocations = []

            # 3. Process each allocation against target invoice
            for inv_id, amt_dec, notes_str in validated_items:
                invoice = invoices_map[inv_id]

                # Check customer ownership match
                if invoice.customer_id != payment.customer_id:
                    raise ValidationError({
                        "allocations": f"Invoice {invoice.invoice_number} belongs to customer '{invoice.customer.name}', which does not match payment customer '{payment.customer.name}'."
                    })

                # Check currency match
                if payment.currency != 'USD':  # Assuming system standard currency check
                    pass

                # Check eligible invoice status
                if invoice.status not in ['POSTED', 'PARTIALLY_PAID']:
                    raise ValidationError({
                        "allocations": f"Cannot allocate to invoice {invoice.invoice_number} because it is in status '{invoice.status}'. Only POSTED or PARTIALLY_PAID invoices can accept payments."
                    })

                if invoice.balance <= Decimal('0.00'):
                    raise ValidationError({
                        "allocations": f"Invoice {invoice.invoice_number} has zero remaining balance and cannot accept additional allocations."
                    })

                if amt_dec > invoice.balance:
                    raise ValidationError({
                        "allocations": f"Allocation amount (${amt_dec}) exceeds invoice {invoice.invoice_number} remaining balance (${invoice.balance})."
                    })

                # Create PaymentAllocation record
                alloc = PaymentAllocation.objects.create(
                    payment=payment,
                    invoice=invoice,
                    amount=amt_dec,
                    notes=notes_str or ''
                )
                created_allocations.append(alloc)

                # Update Payment unallocated credit
                payment.unallocated_amount -= amt_dec

                # Update Invoice settlement fields
                invoice.paid_amount = (invoice.paid_amount + amt_dec).quantize(Decimal('0.01'))
                invoice.balance = (invoice.balance - amt_dec).quantize(Decimal('0.01'))

                if invoice.balance == Decimal('0.00'):
                    invoice.status = 'PAID'
                    invoice.paid_at = timezone.now()
                else:
                    invoice.status = 'PARTIALLY_PAID'

                invoice.save()

                if invoice.subscription:
                    BillingAuditService.log_financial_event(
                        subscription=invoice.subscription,
                        action='PAYMENT_ALLOCATED',
                        actor=user,
                        reason=f"Payment allocation from {payment.payment_number}",
                        metadata={
                            'payment_id': payment.id,
                            'payment_number': payment.payment_number,
                            'invoice_id': invoice.id,
                            'invoice_number': invoice.invoice_number,
                            'allocated_amount': str(amt_dec),
                            'invoice_balance_after': str(invoice.balance),
                        }
                    )

            payment.save()

            return {
                "payment": payment,
                "allocations": created_allocations,
                "invoices": [invoices_map[iid] for iid in invoice_ids]
            }


class WebhookInboxProcessor:
    @classmethod
    def process_inbox_item(cls, inbox_item):
        """
        Durable processor for WebhookInbox records.
        Executes within transaction.atomic() to guarantee zero partial financial state.
        """
        if inbox_item.status == 'PROCESSED':
            return inbox_item

        payload = inbox_item.payload or {}
        event_type = inbox_item.event_type or payload.get('type', '')

        # Filter supported event types
        if event_type not in ['payment_intent.succeeded', 'payment_intent.payment_failed']:
            inbox_item.status = 'PROCESSED'
            inbox_item.processed_at = timezone.now()
            inbox_item.error_message = f"Acknowledged unhandled event type '{event_type}'."
            inbox_item.save(update_fields=['status', 'processed_at', 'error_message'])
            return inbox_item

        obj = payload.get('data', {}).get('object', {})
        pi_id = obj.get('id', '')
        if not pi_id:
            inbox_item.status = 'FAILED'
            inbox_item.error_message = "Missing PaymentIntent object ID."
            inbox_item.save(update_fields=['status', 'error_message'])
            return inbox_item

        with transaction.atomic():
            # Check deduplication Layer 2 (Payment.gateway_transaction_id)
            existing_payment = Payment.objects.filter(gateway_transaction_id=pi_id).first()
            if existing_payment:
                inbox_item.status = 'PROCESSED'
                inbox_item.processed_at = timezone.now()
                inbox_item.error_message = f"Payment for transaction {pi_id} already exists (Payment {existing_payment.payment_number})."
                inbox_item.save(update_fields=['status', 'processed_at', 'error_message'])
                return inbox_item

            # Resolve BillingCustomer
            metadata = obj.get('metadata') or {}
            cust_id = metadata.get('billing_customer_id')
            stripe_cust_id = obj.get('customer')

            customer = None
            if cust_id:
                customer = BillingCustomer.objects.filter(id=cust_id).first()
            if not customer and stripe_cust_id:
                customer = BillingCustomer.objects.filter(metadata__stripe_customer_id=stripe_cust_id).first()

            if not customer:
                inbox_item.status = 'FAILED'
                inbox_item.error_message = f"Could not resolve BillingCustomer from metadata {metadata} or Stripe customer {stripe_cust_id}."
                inbox_item.save(update_fields=['status', 'error_message'])
                return inbox_item

            # Parse amount (cents -> dollars)
            amount_cents = obj.get('amount', 0)
            amount_dollars = (Decimal(str(amount_cents)) / Decimal('100.00')).quantize(Decimal('0.01'))
            currency = str(obj.get('currency', 'usd')).upper()
            pm_id = str(obj.get('payment_method', ''))

            if event_type == 'payment_intent.succeeded':
                # Create Payment receipt via PaymentService
                payment = PaymentService.record_payment(
                    customer=customer,
                    amount=amount_dollars,
                    currency=currency,
                    payment_method='CREDIT_CARD',
                    payment_method_id=pm_id,
                    gateway_transaction_id=pi_id,
                    payment_date=timezone.now().date(),
                    notes=f"Stripe PaymentIntent {pi_id} via Webhook event {inbox_item.event_id}"
                )

                # Trusted Invoice Resolution & Settlement
                inv_id = metadata.get('invoice_id')
                if inv_id:
                    invoice = Invoice.objects.filter(id=inv_id).first()
                    if (
                        invoice and
                        invoice.customer_id == customer.id and
                        invoice.customer.organization_id == customer.organization_id and
                        invoice.status in ['POSTED', 'PARTIALLY_PAID'] and
                        invoice.balance > Decimal('0.00')

                    ):
                        alloc_amt = min(payment.unallocated_amount, invoice.balance)
                        if alloc_amt > Decimal('0.00'):
                            PaymentAllocationService.allocate_payment(
                                payment_id=payment.id,
                                allocations_data=[{
                                    'invoice_id': invoice.id,
                                    'amount': alloc_amt,
                                    'notes': f"Automated allocation from Webhook event {inbox_item.event_id}"
                                }]
                            )
                            if invoice.subscription and invoice.subscription.status in ['PAST_DUE', 'UNPAID']:
                                DunningService.handle_manual_payment_recovery(
                                    subscription=invoice.subscription,
                                    invoice=invoice,
                                    payment=payment
                                )

            elif event_type == 'payment_intent.payment_failed':
                # Record failed Payment record
                payment = Payment.objects.create(
                    payment_number=PaymentService.generate_next_payment_number(),
                    customer=customer,
                    amount=amount_dollars,
                    currency=currency,
                    payment_method='CREDIT_CARD',
                    payment_method_id=pm_id,
                    gateway_transaction_id=pi_id,
                    status='FAILED',
                    payment_date=timezone.now().date(),
                    unallocated_amount=Decimal('0.00'),
                    notes=f"Failed PaymentIntent {pi_id} via Webhook event {inbox_item.event_id}"
                )

                inv_id = metadata.get('invoice_id')
                if inv_id:
                    invoice = Invoice.objects.filter(id=inv_id).first()
                    if invoice and invoice.subscription and invoice.subscription.status == 'LIVE':
                        last_err = obj.get('last_payment_error', {}) or {}
                        DunningService.handle_failed_renewal(
                            subscription=invoice.subscription,
                            invoice=invoice,
                            error_code=str(last_err.get('code', 'PAYMENT_FAILED')),
                            error_message=str(last_err.get('message', 'Payment intent failed'))
                        )

            inbox_item.status = 'PROCESSED'
            inbox_item.processed_at = timezone.now()
            inbox_item.save(update_fields=['status', 'processed_at'])
            return inbox_item


class DunningService:
    RETRY_SCHEDULE_DAYS = {
        1: 3,   # Day 3 retry
        2: 7,   # Day 7 retry
        3: 14,  # Day 14 retry
    }

    @classmethod
    def handle_failed_renewal(cls, subscription, invoice=None, error_code='', error_message=''):
        """
        Authoritative service method handling initial renewal charge failure or webhook failure event.
        - If subscription is LIVE, transitions to PAST_DUE via SubscriptionStateMachineService.
        - Records an initial DunningLog record (attempt_number=0).
        - Handles missing payment method gracefully without creating fake payment records.
        """
        with transaction.atomic():
            sub = Subscription.objects.select_for_update().select_related('customer').get(id=subscription.id)
            if sub.status == 'LIVE':
                SubscriptionStateMachineService.transition(
                    subscription=sub,
                    to_status='PAST_DUE',
                    user=None,
                    reason=f"Renewal payment collection failed: {error_message or error_code or 'Payment failed'}"
                )
                sub.refresh_from_db()

            has_no_pm = not (sub.customer and sub.customer.default_payment_method_id)
            err_code = 'MISSING_PAYMENT_METHOD' if has_no_pm else (error_code or 'PAYMENT_FAILED')
            err_msg = 'Customer has no default payment method attached.' if has_no_pm else (error_message or 'Initial renewal payment failed.')

            inv_id_str = str(invoice.id) if invoice else 'none'
            idempotency_key = f"dunning_sub_{sub.id}_inv_{inv_id_str}_attempt_0"

            if not DunningLog.objects.filter(idempotency_key=idempotency_key).exists():
                DunningLog.objects.create(
                    subscription=sub,
                    invoice=invoice,
                    attempt_number=0,
                    status='FAILED',
                    idempotency_key=idempotency_key,
                    error_code=err_code,
                    error_message=err_msg,
                    next_retry_at=timezone.now() + timedelta(days=3)
                )

        return sub

    @classmethod
    def process_dunning_retries(cls, organization=None, force_next_attempt=False):
        """
        Iterates over PAST_DUE subscriptions and executes scheduled dunning retries.
        - Database row locking via Subscription.objects.select_for_update() ensures concurrent safety.
        - Retries on Day 3, Day 7, Day 14 based on initial failure timestamp.
        - Uses deterministic Stripe idempotency keys (dunning_sub_<sub_id>_inv_<inv_id>_attempt_<N>).
        - On success: settles invoice via PaymentService/PaymentAllocationService & transitions PAST_DUE -> LIVE.
        - On 3rd attempt failure: transitions PAST_DUE -> UNPAID & logs EXHAUSTED status.
        - force_next_attempt: When True (admin trigger/simulation), advances the next scheduled retry attempt immediately.
        """
        qs = Subscription.objects.filter(status='PAST_DUE').select_related('customer')
        if organization:
            qs = qs.filter(customer__organization=organization)

        processed_count = 0
        success_count = 0
        failed_count = 0
        exhausted_count = 0

        sub_ids = list(qs.values_list('id', flat=True))

        for sub_id in sub_ids:
            with transaction.atomic():
                try:
                    sub = Subscription.objects.select_for_update().select_related('customer').get(id=sub_id, status='PAST_DUE')
                except Subscription.DoesNotExist:
                    continue

                invoice = Invoice.objects.filter(
                    subscription=sub,
                    status__in=['POSTED', 'PARTIALLY_PAID'],
                    balance__gt=Decimal('0.00')
                ).order_by('-created_at').first()

                if not invoice or invoice.balance <= Decimal('0.00'):
                    cls.handle_manual_payment_recovery(sub, invoice, None)
                    continue

                initial_log = DunningLog.objects.filter(
                    subscription=sub,
                    invoice=invoice,
                    attempt_number=0
                ).order_by('timestamp').first()

                if not initial_log:
                    initial_log = DunningLog.objects.filter(subscription=sub).order_by('timestamp').first()

                initial_time = initial_log.timestamp if initial_log else sub.updated_at
                now = timezone.now()
                elapsed_days = (now - initial_time).days

                completed_logs = list(
                    DunningLog.objects.filter(
                        subscription=sub,
                        invoice=invoice,
                        status__in=['SUCCESS', 'FAILED', 'EXHAUSTED']
                    )
                )

                completed_attempts = {log.attempt_number for log in completed_logs if log.attempt_number > 0}
                next_attempt = max(completed_attempts, default=0) + 1

                if next_attempt > 3:
                    if not any(log.status == 'EXHAUSTED' for log in completed_logs):
                        SubscriptionStateMachineService.transition(
                            subscription=sub,
                            to_status='UNPAID',
                            user=None,
                            reason="Dunning retries exhausted after 3 failed attempts."
                        )
                        DunningLog.objects.create(
                            subscription=sub,
                            invoice=invoice,
                            attempt_number=3,
                            status='EXHAUSTED',
                            idempotency_key=f"dunning_sub_{sub.id}_inv_{invoice.id}_exhausted",
                            error_code='RETRIES_EXHAUSTED',
                            error_message='All 3 retry attempts failed. Subscription is now UNPAID.'
                        )
                        exhausted_count += 1
                    continue

                required_days = cls.RETRY_SCHEDULE_DAYS[next_attempt]
                if not force_next_attempt and elapsed_days < required_days:
                    continue

                idempotency_key = f"dunning_sub_{sub.id}_inv_{invoice.id}_attempt_{next_attempt}"

                if DunningLog.objects.filter(idempotency_key=idempotency_key, status__in=['SUCCESS', 'FAILED', 'EXHAUSTED']).exists():
                    continue

                processed_count += 1
                pm_id = sub.customer.default_payment_method_id if sub.customer else None

                if not pm_id:
                    next_retry = now + timedelta(days=cls.RETRY_SCHEDULE_DAYS.get(next_attempt + 1, 0)) if next_attempt < 3 else None
                    DunningLog.objects.create(
                        subscription=sub,
                        invoice=invoice,
                        attempt_number=next_attempt,
                        status='FAILED',
                        idempotency_key=idempotency_key,
                        error_code='MISSING_PAYMENT_METHOD',
                        error_message=f"Attempt #{next_attempt} failed: Customer has no default payment method attached.",
                        next_retry_at=next_retry
                    )
                    failed_count += 1

                    if next_attempt == 3:
                        SubscriptionStateMachineService.transition(
                            subscription=sub,
                            to_status='UNPAID',
                            user=None,
                            reason="Dunning retries exhausted due to missing payment method."
                        )
                        DunningLog.objects.create(
                            subscription=sub,
                            invoice=invoice,
                            attempt_number=3,
                            status='EXHAUSTED',
                            idempotency_key=f"dunning_sub_{sub.id}_inv_{invoice.id}_exhausted",
                            error_code='RETRIES_EXHAUSTED',
                            error_message='All 3 retry attempts failed. Subscription is now UNPAID.'
                        )
                        exhausted_count += 1
                    continue

                from billing.gateways.stripe import StripeGatewayService
                sub_currency = getattr(sub, 'currency', 'USD') or 'USD'

                try:
                    gateway_res = StripeGatewayService().create_payment_intent(
                        customer=sub.customer,
                        amount=invoice.balance,
                        currency=sub_currency,
                        payment_method_id=pm_id,
                        invoice_id=invoice.id,
                        description=f"Dunning retry #{next_attempt} for invoice {invoice.invoice_number}",
                        idempotency_key=idempotency_key
                    )
                    pi_id = gateway_res.get('payment_intent_id', '')
                    res_status = gateway_res.get('status')

                    if res_status == 'succeeded':
                        pay = PaymentService.record_payment(
                            customer=sub.customer,
                            amount=invoice.balance,
                            currency=sub_currency,
                            payment_method='CREDIT_CARD',
                            payment_method_id=pm_id,
                            gateway_transaction_id=pi_id,
                            payment_date=now.date(),
                            notes=f"Dunning retry #{next_attempt} payment for invoice {invoice.invoice_number}"
                        )
                        PaymentAllocationService.allocate_payment(
                            payment_id=pay.id,
                            allocations_data=[{
                                'invoice_id': invoice.id,
                                'amount': invoice.balance,
                                'notes': f"Automated allocation from dunning retry #{next_attempt}"
                            }]
                        )

                        SubscriptionStateMachineService.transition(
                            subscription=sub,
                            to_status='LIVE',
                            user=None,
                            reason=f"Dunning retry #{next_attempt} succeeded. Subscription restored to LIVE."
                        )

                        DunningLog.objects.create(
                            subscription=sub,
                            invoice=invoice,
                            attempt_number=next_attempt,
                            status='SUCCESS',
                            gateway_transaction_id=pi_id,
                            idempotency_key=idempotency_key,
                            error_code='',
                            error_message=f"Dunning retry #{next_attempt} succeeded.",
                            next_retry_at=None
                        )
                        success_count += 1
                    else:
                        err_code = gateway_res.get('error_code', 'PAYMENT_FAILED')
                        err_msg = gateway_res.get('error_message', f"Dunning retry #{next_attempt} failed.")
                        next_retry = now + timedelta(days=cls.RETRY_SCHEDULE_DAYS.get(next_attempt + 1, 0)) if next_attempt < 3 else None

                        DunningLog.objects.create(
                            subscription=sub,
                            invoice=invoice,
                            attempt_number=next_attempt,
                            status='FAILED',
                            gateway_transaction_id=pi_id,
                            idempotency_key=idempotency_key,
                            error_code=err_code,
                            error_message=err_msg,
                            next_retry_at=next_retry
                        )
                        failed_count += 1

                        if next_attempt == 3:
                            SubscriptionStateMachineService.transition(
                                subscription=sub,
                                to_status='UNPAID',
                                user=None,
                                reason="Dunning retries exhausted after 3 failed attempts."
                            )
                            DunningLog.objects.create(
                                subscription=sub,
                                invoice=invoice,
                                attempt_number=3,
                                status='EXHAUSTED',
                                idempotency_key=f"dunning_sub_{sub.id}_inv_{invoice.id}_exhausted",
                                error_code='RETRIES_EXHAUSTED',
                                error_message='All 3 retry attempts failed. Subscription is now UNPAID.'
                            )
                            exhausted_count += 1

                except Exception as e:
                    next_retry = now + timedelta(days=cls.RETRY_SCHEDULE_DAYS.get(next_attempt + 1, 0)) if next_attempt < 3 else None
                    DunningLog.objects.create(
                        subscription=sub,
                        invoice=invoice,
                        attempt_number=next_attempt,
                        status='FAILED',
                        idempotency_key=idempotency_key,
                        error_code='GATEWAY_ERROR',
                        error_message=str(e),
                        next_retry_at=next_retry
                    )
                    failed_count += 1

                    if next_attempt == 3:
                        SubscriptionStateMachineService.transition(
                            subscription=sub,
                            to_status='UNPAID',
                            user=None,
                            reason="Dunning retries exhausted after 3 failed attempts."
                        )
                        DunningLog.objects.create(
                            subscription=sub,
                            invoice=invoice,
                            attempt_number=3,
                            status='EXHAUSTED',
                            idempotency_key=f"dunning_sub_{sub.id}_inv_{invoice.id}_exhausted",
                            error_code='RETRIES_EXHAUSTED',
                            error_message='All 3 retry attempts failed. Subscription is now UNPAID.'
                        )
                        exhausted_count += 1

        return {
            "processed": processed_count,
            "succeeded": success_count,
            "failed": failed_count,
            "exhausted": exhausted_count
        }

    @classmethod
    def handle_manual_payment_recovery(cls, subscription, invoice=None, payment=None):
        """
        Called when an invoice is fully paid manually or via external payment while subscription is PAST_DUE or UNPAID.
        Restores subscription to LIVE status.
        """
        with transaction.atomic():
            sub = Subscription.objects.select_for_update().get(id=subscription.id)
            if sub.status in ['PAST_DUE', 'UNPAID']:
                SubscriptionStateMachineService.transition(
                    subscription=sub,
                    to_status='LIVE',
                    user=None,
                    reason="Manual payment recovery settled invoice. Subscription restored to LIVE."
                )
                idempotency_key = f"manual_recovery_sub_{sub.id}_inv_{invoice.id if invoice else 'none'}_{int(timezone.now().timestamp() * 1000)}"
                DunningLog.objects.create(
                    subscription=sub,
                    invoice=invoice,
                    attempt_number=0,
                    status='SUCCESS',
                    gateway_transaction_id=payment.gateway_transaction_id if payment else '',
                    idempotency_key=idempotency_key,
                    error_code='',
                    error_message='Manual payment recovery successful.',
                    next_retry_at=None
                )
                return True
        return False


class SubscriptionRenewalService:
    @classmethod
    def renew_subscription(cls, subscription, user=None):
        """
        Authoritative service method executing automated subscription renewal.
        Uses two-stage transaction architecture:
        - Stage 1 (Atomic DB Transaction):
            1. Lock subscription with select_for_update()
            2. Re-verify renewal eligibility (LIVE and next_billing_date <= today, or NON_RENEWING -> CANCELLED)
            3. Invoke InvoicingEngineService.generate_invoice(subscription, billing_period_start=next_billing_date)
            4. Advance term dates via SubscriptionService.calculate_term_dates
            5. Create SubscriptionAuditLog record (action='RENEWAL_COMPLETED')
            6. Commit DB transaction
        - Stage 2 (Auto-Collection Dispatch):
            If collection_method == 'CHARGE_AUTOMATIC' and customer has default_payment_method_id:
            Trigger StripeGatewayService.create_payment_intent off-session.
        """
        today = date.today()
        sub_id = subscription.id

        # Stage 1: Atomic Database Transaction
        with transaction.atomic():
            sub = Subscription.objects.select_for_update().select_related('customer').get(id=sub_id)

            # Check NON_RENEWING or cancel_at_period_end condition
            if sub.status == 'NON_RENEWING' or sub.cancel_at_period_end:
                if sub.next_billing_date and sub.next_billing_date <= today:
                    SubscriptionStateMachineService.transition(
                        subscription=sub,
                        to_status='CANCELLED',
                        user=user,
                        reason="Subscription reached end of billing term with cancel_at_period_end=True"
                    )
                    return {"status": "CANCELLED", "invoice": None, "subscription": sub}
                return {"status": "SKIPPED", "invoice": None, "subscription": sub}

            # Check eligibility
            if sub.status != 'LIVE' or not sub.next_billing_date or sub.next_billing_date > today:
                return {"status": "SKIPPED", "invoice": None, "subscription": sub}

            billing_period_start = sub.next_billing_date

            # Generate renewal invoice (Idempotent via inv_sub_<id>_period_<start>)
            invoice = InvoicingEngineService.generate_invoice(
                subscription=sub,
                billing_period_start=billing_period_start,
                issue_date=today,
                user=user
            )

            # Advance term dates
            cycle = 'MONTHLY'
            first_item = sub.items.filter(item_type='PLAN').select_related('plan').first()
            if first_item and first_item.plan and first_item.plan.billing_cycle:
                cycle = (first_item.plan.billing_cycle or 'MONTHLY').upper()

            calc_start, calc_end, calc_next = SubscriptionService.calculate_term_dates(billing_period_start, cycle)
            sub.current_term_start = calc_start
            sub.current_term_end = calc_end
            sub.next_billing_date = calc_next
            sub.save(update_fields=['current_term_start', 'current_term_end', 'next_billing_date', 'updated_at'])

            # Audit Log
            BillingAuditService.log_subscription_lifecycle(
                subscription=sub,
                action='RENEWAL_COMPLETED',
                actor=user,
                old_state='LIVE',
                new_state='LIVE',
                reason=f"Automated term renewal for period {billing_period_start.isoformat()}",
                metadata={
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "next_billing_date": sub.next_billing_date.isoformat(),
                    "total_amount": str(invoice.total_amount)
                }
            )

        # Stage 2: External Auto-Collection Side Effect
        if sub.collection_method == 'CHARGE_AUTOMATIC':
            if not (sub.customer and sub.customer.default_payment_method_id):
                DunningService.handle_failed_renewal(
                    subscription=sub,
                    invoice=invoice,
                    error_code='MISSING_PAYMENT_METHOD',
                    error_message='Customer has no default payment method attached.'
                )
            else:
                try:
                    from billing.gateways.stripe import StripeGatewayService
                    sub_currency = getattr(sub, 'currency', 'USD') or 'USD'
                    idempotency_key = f"renewal_sub_{sub.id}_inv_{invoice.id}"
                    gateway_res = StripeGatewayService().create_payment_intent(
                        customer=sub.customer,
                        amount=invoice.total_amount,
                        currency=sub_currency,
                        payment_method_id=sub.customer.default_payment_method_id,
                        invoice_id=invoice.id,
                        description=f"Automated renewal invoice {invoice.invoice_number} payment",
                        idempotency_key=idempotency_key
                    )
                    pi_id = gateway_res.get('payment_intent_id')
                    if pi_id and gateway_res.get('status') == 'succeeded':
                        existing_pay = Payment.objects.filter(gateway_transaction_id=pi_id).first()
                        if not existing_pay:
                            pay = PaymentService.record_payment(
                                customer=sub.customer,
                                amount=invoice.total_amount,
                                currency=sub_currency,
                                payment_method='CREDIT_CARD',
                                payment_method_id=sub.customer.default_payment_method_id,
                                gateway_transaction_id=pi_id,
                                payment_date=today,
                                notes=f"Auto-collection for renewal invoice {invoice.invoice_number}"
                            )
                            PaymentAllocationService.allocate_payment(
                                payment_id=pay.id,
                                allocations_data=[{
                                    'invoice_id': invoice.id,
                                    'amount': invoice.total_amount,
                                    'notes': f"Automated allocation for renewal invoice {invoice.invoice_number}"
                                }]
                            )
                    else:
                        err_code = gateway_res.get('error_code', 'PAYMENT_FAILED')
                        err_msg = gateway_res.get('error_message', 'Payment intent failed')
                        DunningService.handle_failed_renewal(
                            subscription=sub,
                            invoice=invoice,
                            error_code=err_code,
                            error_message=err_msg
                        )
                except Exception as e:
                    DunningService.handle_failed_renewal(
                        subscription=sub,
                        invoice=invoice,
                        error_code='GATEWAY_ERROR',
                        error_message=str(e)
                    )





        invoice.refresh_from_db()
        return {"status": "RENEWED", "invoice": invoice, "subscription": sub}


    @classmethod
    def process_due_renewals(cls, organization=None, user=None, batch_size=50):
        """
        Processes all due subscriptions for an organization up to batch_size.
        Executes each renewal in an isolated block so one failure does not break the batch.
        """
        today = date.today()
        try:
            batch_size = max(1, min(int(batch_size or 50), 500))
        except (ValueError, TypeError):
            batch_size = 50

        qs = Subscription.objects.filter(
            status__in=['LIVE', 'NON_RENEWING'],
            next_billing_date__lte=today
        ).order_by('next_billing_date', 'id')

        if organization:
            qs = qs.filter(customer__organization=organization)

        candidate_ids = list(qs.values_list('id', flat=True)[:batch_size])

        results = {
            "processed": len(candidate_ids),
            "renewed": 0,
            "cancelled": 0,
            "skipped": 0,
            "failed": 0,
            "details": []
        }

        for sub_id in candidate_ids:
            try:
                sub = Subscription.objects.get(id=sub_id)
                res = cls.renew_subscription(sub, user=user)
                status_str = res.get('status', 'SKIPPED')
                if status_str == 'RENEWED':
                    results['renewed'] += 1
                elif status_str == 'CANCELLED':
                    results['cancelled'] += 1
                else:
                    results['skipped'] += 1

                inv = res.get('invoice')
                results['details'].append({
                    "subscription_id": sub_id,
                    "subscription_number": sub.subscription_number,
                    "status": status_str,
                    "invoice_number": inv.invoice_number if inv else None
                })
            except Exception as e:
                results['failed'] += 1
                results['details'].append({
                    "subscription_id": sub_id,
                    "status": "FAILED",
                    "error": str(e)
                })

        return results


CN_NUMBER_REGEX = re.compile(r'^CN-(\d{4})-(\d{5})$')
MAX_CREDIT_NOTE_NUMBER_INT = 99999

DN_NUMBER_REGEX = re.compile(r'^DN-(\d{4})-(\d{5})$')
MAX_DEBIT_NOTE_NUMBER_INT = 99999


class CreditNoteService:
    @staticmethod
    def generate_next_credit_note_number():
        """
        Calculates the next available sequential candidate CN-YYYY-XXXXX across the entire database.
        Zero count()+1. Excludes malformed numbers from numeric sequence calculation.
        """
        current_year = date.today().year
        pattern = f"^CN-{current_year}-(\\d{{5}})$"
        year_regex = re.compile(pattern)

        existing_numbers = CreditNote.objects.values_list('credit_note_number', flat=True)
        max_seq = 0
        for num in existing_numbers:
            match = year_regex.match(num or '')
            if match:
                seq_val = int(match.group(1))
                if seq_val > max_seq:
                    max_seq = seq_val

        next_seq = max_seq + 1
        if next_seq > MAX_CREDIT_NOTE_NUMBER_INT:
            raise ValidationError({
                "credit_note_number": f"Credit note number sequence limit reached (CN-{current_year}-99999). Contact system administrator."
            })
        return f"CN-{current_year}-{next_seq:05d}"

    @classmethod
    def issue_credit_note(cls, customer, amount, reason='CORRECTION', invoice=None, subtotal=None, tax_total=None, issued_date=None, user=None, max_retries=5):
        """
        Authoritative service method for issuing Credit Notes.
        - Validates amount > 0 (Decimal '0.01').
        - Validates customer tenant organization against user if provided.
        - If invoice provided, validates invoice belongs to customer and matches tenant organization.
        - Preserves posted invoice immutability (does NOT modify invoice totals or lines).
        - Generates atomic sequential credit_note_number (CN-YYYY-XXXXX).
        - Initializes unallocated_amount = total_amount.
        - Sets status = 'ISSUED'.
        """
        if customer is None:
            raise ValidationError({"customer": "Customer is required."})

        if not customer.is_active:
            raise ValidationError({"customer": "Cannot issue credit note for an inactive customer."})

        if user:
            org = get_billing_tenant_organization(user)
            if org is not None and customer.organization_id != org.id:
                raise PermissionDenied("Cannot issue credit note for customer outside your organization.")

        if amount is None:
            raise ValidationError({"amount": "Credit amount is required."})

        try:
            amount_decimal = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception:
            raise ValidationError({"amount": "Invalid monetary amount format."})

        if amount_decimal <= Decimal('0.00'):
            raise ValidationError({"amount": "Credit amount must be greater than zero."})

        if invoice is not None:
            if invoice.customer_id != customer.id:
                raise ValidationError({"invoice": f"Invoice {invoice.invoice_number} does not belong to customer {customer.name}."})
            if user:
                org = get_billing_tenant_organization(user)
                if org is not None and invoice.customer.organization_id != org.id:
                    raise PermissionDenied("Cannot attach invoice outside your organization.")

        # Subtotal & Tax Calculation
        if subtotal is not None and tax_total is not None:
            subtotal_dec = Decimal(str(subtotal)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            tax_dec = Decimal(str(tax_total)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if subtotal_dec < Decimal('0.00') or tax_dec < Decimal('0.00'):
                raise ValidationError({"amount": "Subtotal and tax total must be non-negative."})
            if (subtotal_dec + tax_dec) != amount_decimal:
                raise ValidationError({"amount": f"Subtotal (${subtotal_dec}) + Tax (${tax_dec}) must equal total credit amount (${amount_decimal})."})
        elif subtotal is not None and tax_total is None:
            subtotal_dec = Decimal(str(subtotal)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if subtotal_dec < Decimal('0.00') or subtotal_dec > amount_decimal:
                raise ValidationError({"amount": "Subtotal must be non-negative and not exceed total credit amount."})
            tax_dec = (amount_decimal - subtotal_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        elif tax_total is not None and subtotal is None:
            tax_dec = Decimal(str(tax_total)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if tax_dec < Decimal('0.00') or tax_dec > amount_decimal:
                raise ValidationError({"amount": "Tax total must be non-negative and not exceed total credit amount."})
            subtotal_dec = (amount_decimal - tax_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            subtotal_dec = amount_decimal
            tax_dec = Decimal('0.00')

        valid_reasons = dict(CreditNote.REASON_CHOICES).keys()
        reason_clean = (reason or 'CORRECTION').strip().upper()
        if reason_clean not in valid_reasons:
            raise ValidationError({"reason": f"Invalid reason '{reason_clean}'. Allowed: {list(valid_reasons)}."})

        if not issued_date:
            issued_date = date.today()
        elif isinstance(issued_date, str):
            issued_date = date.fromisoformat(issued_date)

        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    cn_num = cls.generate_next_credit_note_number()
                    credit_note = CreditNote.objects.create(
                        credit_note_number=cn_num,
                        customer=customer,
                        invoice=invoice,
                        reason=reason_clean,
                        subtotal=subtotal_dec,
                        tax_total=tax_dec,
                        total_amount=amount_decimal,
                        unallocated_amount=amount_decimal,
                        status='ISSUED',
                        issued_date=issued_date
                    )

                    if invoice and invoice.subscription:
                        BillingAuditService.log_financial_event(
                            subscription=invoice.subscription,
                            action='CREDIT_NOTE_ISSUED',
                            actor=user,
                            reason=reason_clean,
                            metadata={
                                'credit_note_id': credit_note.id,
                                'credit_note_number': credit_note.credit_note_number,
                                'amount': str(credit_note.total_amount),
                                'invoice_id': invoice.id,
                                'invoice_number': invoice.invoice_number,
                            }
                        )

                    return credit_note
            except IntegrityError:
                if attempt == max_retries - 1:
                    raise ValidationError({"credit_note_number": "Could not generate a unique credit note number due to concurrent writes. Please try again."})
                continue

    @classmethod
    def get_customer_unapplied_credit(cls, customer):
        """
        Calculates the total unapplied credit balance across all ISSUED credit notes for a customer.
        """
        if not customer:
            return Decimal('0.00')
        cust_id = customer.id if hasattr(customer, 'id') else customer
        agg = CreditNote.objects.filter(customer_id=cust_id, status='ISSUED').aggregate(total=Sum('unallocated_amount'))
        return Decimal(str(agg['total'] or '0.00')).quantize(Decimal('0.01'))


class DebitNoteService:
    @staticmethod
    def generate_next_debit_note_number():
        """
        Calculates the next available sequential candidate DN-YYYY-XXXXX across the entire database.
        Zero count()+1. Excludes malformed numbers from numeric sequence calculation.
        """
        current_year = date.today().year
        pattern = f"^DN-{current_year}-(\\d{{5}})$"
        year_regex = re.compile(pattern)

        existing_numbers = DebitNote.objects.values_list('debit_note_number', flat=True)
        max_seq = 0
        for num in existing_numbers:
            match = year_regex.match(num or '')
            if match:
                seq_val = int(match.group(1))
                if seq_val > max_seq:
                    max_seq = seq_val

        next_seq = max_seq + 1
        if next_seq > MAX_DEBIT_NOTE_NUMBER_INT:
            raise ValidationError({
                "debit_note_number": f"Debit note number sequence limit reached (DN-{current_year}-99999). Contact system administrator."
            })
        return f"DN-{current_year}-{next_seq:05d}"

    @classmethod
    def issue_debit_note(cls, invoice, amount, reason='', issued_date=None, user=None, max_retries=5):
        """
        Authoritative service method for issuing Debit Notes.
        - Validates amount > 0 (Decimal '0.01').
        - Validates target invoice status (POSTED, PARTIALLY_PAID, PAID).
        - Preserves posted invoice immutability (does NOT mutate original invoice totals or line items).
        - Generates atomic sequential debit_note_number (DN-YYYY-XXXXX).
        - Sets issued_date = today if not provided.
        """
        if invoice is None:
            raise ValidationError({"invoice": "Invoice is required."})

        if invoice.status not in ['POSTED', 'PARTIALLY_PAID', 'PAID']:
            raise ValidationError({"invoice": f"Cannot issue debit note against invoice in status '{invoice.status}'. Only POSTED, PARTIALLY_PAID, or PAID invoices are eligible."})

        if user:
            org = get_billing_tenant_organization(user)
            if org is not None and invoice.customer.organization_id != org.id:
                raise PermissionDenied("Cannot issue debit note for invoice outside your organization.")

        if amount is None:
            raise ValidationError({"amount": "Debit amount is required."})

        try:
            amount_decimal = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception:
            raise ValidationError({"amount": "Invalid monetary amount format."})

        if amount_decimal <= Decimal('0.00'):
            raise ValidationError({"amount": "Debit amount must be greater than zero."})

        if not issued_date:
            issued_date = date.today()
        elif isinstance(issued_date, str):
            issued_date = date.fromisoformat(issued_date)

        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    dn_num = cls.generate_next_debit_note_number()
                    debit_note = DebitNote.objects.create(
                        debit_note_number=dn_num,
                        invoice=invoice,
                        amount=amount_decimal,
                        reason=reason or '',
                        issued_date=issued_date
                    )

                    if invoice.subscription:
                        BillingAuditService.log_financial_event(
                            subscription=invoice.subscription,
                            action='DEBIT_NOTE_ISSUED',
                            actor=user,
                            reason=reason or '',
                            metadata={
                                'debit_note_id': debit_note.id,
                                'debit_note_number': debit_note.debit_note_number,
                                'amount': str(debit_note.amount),
                                'invoice_id': invoice.id,
                                'invoice_number': invoice.invoice_number,
                            }
                        )

                    return debit_note
            except IntegrityError:
                if attempt == max_retries - 1:
                    raise ValidationError({"debit_note_number": "Could not generate a unique debit note number due to concurrent writes. Please try again."})
                continue


class CreditNoteAllocationService:
    @classmethod
    def allocate_credit_note(cls, credit_note_id, allocations_data, user=None):
        """
        Authoritative Credit Note allocation service with atomic ledger settlement.
        - Wraps execution in single transaction.atomic()
        - Acquires select_for_update() row locks on CreditNote and target Invoices
        - Validates credit_note status is ISSUED and has unallocated_amount > 0
        - Validates total allocated amount <= credit_note.unallocated_amount
        - For each target invoice:
            - Validates same customer and tenant organization
            - Validates invoice status in ['POSTED', 'PARTIALLY_PAID'] with balance > 0
            - Validates allocation amount <= invoice.balance
            - Creates CreditNoteAllocation record
            - Decrements credit_note.unallocated_amount
            - Decrements invoice.balance directly
            - Updates invoice status to PAID or PARTIALLY_PAID
        """
        if not allocations_data:
            raise ValidationError({"allocations": "At least one allocation item is required."})

        # 1. Parse and validate input data structure
        total_requested = Decimal('0.00')
        validated_items = []

        for idx, item in enumerate(allocations_data):
            inv_id = item.get('invoice_id') or item.get('invoice')
            if not inv_id:
                raise ValidationError({"allocations": f"Item {idx}: invoice_id is required."})

            try:
                inv_id = int(inv_id)
            except (ValueError, TypeError):
                raise ValidationError({"allocations": f"Item {idx}: invalid invoice_id format."})

            raw_amt = item.get('amount')
            if raw_amt is None:
                raise ValidationError({"allocations": f"Item {idx}: amount is required."})

            try:
                amt_dec = Decimal(str(raw_amt)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            except Exception:
                raise ValidationError({"allocations": f"Item {idx}: invalid monetary amount format."})

            if amt_dec <= Decimal('0.00'):
                raise ValidationError({"allocations": f"Item {idx}: allocation amount must be greater than zero."})

            total_requested += amt_dec
            validated_items.append((inv_id, amt_dec))

        with transaction.atomic():
            # 2. Acquire row lock on CreditNote
            try:
                credit_note = CreditNote.objects.select_for_update().select_related('customer').get(pk=credit_note_id)
            except CreditNote.DoesNotExist:
                raise ValidationError({"credit_note": f"Credit Note with id {credit_note_id} does not exist."})

            if user:
                org = get_billing_tenant_organization(user)
                if org is not None and credit_note.customer.organization_id != org.id:
                    raise PermissionDenied("Cannot allocate credit note outside your organization.")

            if credit_note.status != 'ISSUED':
                raise ValidationError({
                    "credit_note": f"Cannot allocate credit note in status '{credit_note.status}'. Only ISSUED credit notes can be allocated."
                })

            if credit_note.unallocated_amount <= Decimal('0.00'):
                raise ValidationError({
                    "credit_note": "This credit note has already been fully allocated ($0.00 remaining)."
                })

            if total_requested > credit_note.unallocated_amount:
                raise ValidationError({
                    "allocations": f"Total requested allocation (${total_requested}) exceeds available credit note balance (${credit_note.unallocated_amount})."
                })

            # Fetch and lock target Invoices
            invoice_ids = [item[0] for item in validated_items]
            invoices_qs = Invoice.objects.select_for_update().select_related('customer').filter(id__in=invoice_ids)
            invoices_map = {inv.id: inv for inv in invoices_qs}

            missing_invoices = set(invoice_ids) - set(invoices_map.keys())
            if missing_invoices:
                raise ValidationError({"allocations": f"Invoice(s) {list(missing_invoices)} not found."})

            created_allocations = []
            updated_invoices = []

            # 3. Process each allocation against target invoice
            for inv_id, amt_dec in validated_items:
                invoice = invoices_map[inv_id]

                # Check customer ownership match
                if invoice.customer_id != credit_note.customer_id:
                    raise ValidationError({
                        "allocations": f"Invoice {invoice.invoice_number} belongs to customer '{invoice.customer.name}', which does not match credit note customer '{credit_note.customer.name}'."
                    })

                if user:
                    org = get_billing_tenant_organization(user)
                    if org is not None and invoice.customer.organization_id != org.id:
                        raise PermissionDenied("Cannot allocate to invoice outside your organization.")

                # Check eligible invoice status
                if invoice.status not in ['POSTED', 'PARTIALLY_PAID']:
                    raise ValidationError({
                        "allocations": f"Cannot allocate to invoice {invoice.invoice_number} because it is in status '{invoice.status}'. Only POSTED or PARTIALLY_PAID invoices can accept credit allocations."
                    })

                if invoice.balance <= Decimal('0.00'):
                    raise ValidationError({
                        "allocations": f"Invoice {invoice.invoice_number} has zero remaining balance and cannot accept additional allocations."
                    })

                if amt_dec > invoice.balance:
                    raise ValidationError({
                        "allocations": f"Allocation amount (${amt_dec}) exceeds invoice {invoice.invoice_number} remaining balance (${invoice.balance})."
                    })

                # Create CreditNoteAllocation record
                alloc = CreditNoteAllocation.objects.create(
                    credit_note=credit_note,
                    invoice=invoice,
                    amount=amt_dec
                )
                created_allocations.append(alloc)

                # Update Credit Note unallocated balance
                credit_note.unallocated_amount = (credit_note.unallocated_amount - amt_dec).quantize(Decimal('0.01'))

                # Update Invoice balance directly
                invoice.balance = (invoice.balance - amt_dec).quantize(Decimal('0.01'))

                if invoice.balance == Decimal('0.00'):
                    invoice.status = 'PAID'
                    invoice.paid_at = timezone.now()
                else:
                    invoice.status = 'PARTIALLY_PAID'

                invoice.save()
                updated_invoices.append(invoice)

                if invoice.subscription:
                    BillingAuditService.log_financial_event(
                        subscription=invoice.subscription,
                        action='CREDIT_NOTE_ALLOCATED',
                        actor=user,
                        reason=f"Credit note allocation from {credit_note.credit_note_number}",
                        metadata={
                            'credit_note_id': credit_note.id,
                            'credit_note_number': credit_note.credit_note_number,
                            'invoice_id': invoice.id,
                            'invoice_number': invoice.invoice_number,
                            'allocated_amount': str(amt_dec),
                            'invoice_balance_after': str(invoice.balance),
                        }
                    )

            credit_note.save()

            return {
                "credit_note": credit_note,
                "allocations": created_allocations,
                "invoices": updated_invoices
            }


class EntitlementService:
    """
    Authoritative Standalone Billing Service for evaluating feature entitlements and commercial limits.
    Strictly decoupled from CRM; evaluates purely on Billing subscriptions and Catalog plans.
    """
    ACTIVE_STATUSES = ('LIVE', 'TRIAL', 'NON_RENEWING')

    @classmethod
    def get_active_subscription(cls, organization_id, target_date=None):
        """
        Retrieves the active entitlement-eligible subscription for an organization.
        Enforces term start/end date invariants: current_term_start <= target_date <= current_term_end.
        FUTURE subscriptions (start_date > today), PAUSED, CANCELLED, UNPAID, and DRAFT are non-entitled.
        """
        if not target_date:
            target_date = date.today()

        subs = (
            Subscription.objects.filter(
                customer__organization_id=organization_id,
                status__in=cls.ACTIVE_STATUSES
            )
            .select_related('customer')
            .prefetch_related('items__plan', 'items__addon')
            .order_by('-created_at')
        )

        for sub in subs:
            if sub.current_term_start and sub.current_term_start > target_date:
                continue
            if sub.current_term_end and sub.current_term_end < target_date:
                continue
            return sub

        return None

    @classmethod
    def has_feature(cls, organization_id, feature_code, target_date=None):
        """
        Determines whether the given organization has access to a specific feature/module.
        Returns Boolean.
        """
        sub = cls.get_active_subscription(organization_id, target_date=target_date)
        if not sub:
            return False

        plan_item = sub.items.filter(item_type='PLAN').first()
        if not plan_item or not plan_item.plan:
            return False

        return PlanModule.objects.filter(
            plan=plan_item.plan,
            module__code=feature_code,
            is_enabled=True
        ).exists()

    @classmethod
    def get_limit(cls, organization_id, limit_code, target_date=None):
        """
        Calculates the authoritative limit for a given module code, including Plan base limits and AddOn contributions.
        Returns a structured dictionary with evaluation results.
        """
        sub = cls.get_active_subscription(organization_id, target_date=target_date)
        if not sub:
            return {
                "limit": limit_code,
                "allowed": False,
                "value": None,
                "reason": "No active subscription found for organization."
            }

        plan_item = sub.items.filter(item_type='PLAN').first()
        if not plan_item or not plan_item.plan:
            return {
                "limit": limit_code,
                "allowed": False,
                "value": None,
                "reason": "Active subscription has no associated plan."
            }

        plan_module = PlanModule.objects.filter(
            plan=plan_item.plan,
            module__code=limit_code,
            is_enabled=True
        ).select_related('module').first()

        if not plan_module:
            return {
                "limit": limit_code,
                "allowed": False,
                "value": None,
                "reason": f"Limit '{limit_code}' is not defined or enabled in active plan."
            }

        addon_qty = 0
        addon_unit = None
        for item in sub.items.filter(item_type='ADDON', addon__code=limit_code):
            addon_qty += (item.quantity or 0)
            if item.addon and item.addon.unit_label:
                addon_unit = item.addon.unit_label

        raw_val = (plan_module.limit_value or '').strip()

        # Case 1: Unlimited
        if not raw_val or raw_val.lower() == 'unlimited':
            return {
                "limit": limit_code,
                "allowed": True,
                "is_unlimited": True,
                "value": "unlimited",
                "numeric_value": None,
                "addon_quantity": addon_qty,
            }

        # Case 2: Purely numeric string (e.g. "5", "500", "10")
        if raw_val.isdigit():
            base_limit = int(raw_val)
            total_limit = base_limit + addon_qty
            return {
                "limit": limit_code,
                "allowed": True,
                "is_unlimited": False,
                "base_limit": base_limit,
                "addon_quantity": addon_qty,
                "total_limit": total_limit,
                "unit": addon_unit or "units",
            }

        # Case 3: Unit-bearing text string (e.g. "500 leads", "10GB")
        return {
            "limit": limit_code,
            "allowed": True,
            "is_unlimited": False,
            "value": raw_val,
            "addon_quantity": addon_qty,
            "unit": addon_unit or (plan_module.module.name if plan_module.module else None),
        }

    @classmethod
    def get_entitlement_summary(cls, organization_id, target_date=None):
        """
        Returns a comprehensive summary of all feature entitlements and limits for an organization.
        """
        sub = cls.get_active_subscription(organization_id, target_date=target_date)
        if not sub:
            return {
                "organization_id": organization_id,
                "has_active_subscription": False,
                "plan": None,
                "subscription_number": None,
                "status": None,
                "features": {},
                "limits": {},
            }

        plan_item = sub.items.filter(item_type='PLAN').first()
        plan = plan_item.plan if plan_item else None

        features = {}
        limits = {}

        if plan:
            for pm in plan.plan_modules.filter(is_enabled=True).select_related('module'):
                mod_code = pm.module.code
                features[mod_code] = True
                limits[mod_code] = cls.get_limit(organization_id, mod_code, target_date=target_date)

        return {
            "organization_id": organization_id,
            "has_active_subscription": True,
            "subscription_id": sub.id,
            "subscription_number": sub.subscription_number,
            "status": sub.status,
            "plan": {
                "id": plan.id,
                "name": plan.name,
                "billing_cycle": plan.billing_cycle,
                "price": str(plan.price),
                "currency": plan.currency,
            } if plan else None,
            "features": features,
            "limits": limits,
        }


class CrmOpportunityProvisioningService:
    """
    Authoritative Integration Service for provisioning Standalone Billing Customers and Subscriptions
    when a CRM Opportunity reaches CLOSED_WON.
    Guarantees concurrency-safe idempotency via row-locking (select_for_update) and metadata identity.
    """
    @classmethod
    def provision_won_opportunity(cls, organization, payload, actor=None):
        """
        Provisions or retrieves a subscription and customer for a WON opportunity.
        """
        opportunity_id = payload.get('opportunity_id')
        if not opportunity_id:
            raise ValidationError({"opportunity_id": "opportunity_id is required."})

        plan_id = payload.get('plan_id')
        if not plan_id:
            raise ValidationError({"plan_id": "plan_id is required."})

        plan = PricingPlan.objects.filter(id=plan_id, is_active=True).first()
        if not plan:
            raise ValidationError({"plan_id": f"PricingPlan {plan_id} does not exist or is inactive."})

        # Validate billing_cycle authority
        provided_cycle = payload.get('billing_cycle')
        if provided_cycle and provided_cycle.upper() != plan.billing_cycle.upper():
            raise ValidationError({
                "billing_cycle": f"Provided billing_cycle '{provided_cycle}' does not match PricingPlan frequency '{plan.billing_cycle}'."
            })

        company_id = payload.get('company_id')
        company_name = (payload.get('company_name') or '').strip()
        contact_email = (payload.get('contact_email') or '').strip().lower()

        with transaction.atomic():
            # 1. Concurrency and Idempotency Lock
            existing_sub = (
                Subscription.objects.select_for_update()
                .filter(customer__organization=organization, metadata__crm_opportunity_id=opportunity_id)
                .first()
            )
            if existing_sub:
                return {
                    "success": True,
                    "idempotent": True,
                    "subscription": existing_sub,
                    "customer": existing_sub.customer,
                    "message": "Subscription already provisioned for this opportunity."
                }

            # 2. Customer Resolution
            customer = None
            if company_id:
                ext_ref = f"crm_company_{company_id}"
                customer = (
                    BillingCustomer.objects.select_for_update()
                    .filter(organization=organization, external_reference_id=ext_ref)
                    .first()
                )

            if not customer and contact_email:
                customer = (
                    BillingCustomer.objects.select_for_update()
                    .filter(organization=organization, email__iexact=contact_email)
                    .first()
                )

            if not customer and company_name:
                customer = (
                    BillingCustomer.objects.select_for_update()
                    .filter(organization=organization, name__iexact=company_name)
                    .first()
                )

            if not customer:
                cust_data = {
                    "name": company_name or f"Company {company_id or 'Unknown'}",
                    "email": contact_email or f"billing+opp{opportunity_id}@tenant.local",
                    "currency": plan.currency or "USD",
                    "external_reference_id": f"crm_company_{company_id}" if company_id else "",
                    "metadata": {
                        "created_via": "crm_closed_won_hook",
                        "crm_opportunity_id": opportunity_id,
                        "crm_company_id": company_id
                    }
                }
                customer = CustomerService.create_customer(
                    organization=organization,
                    user=actor,
                    validated_data=cust_data
                )

            # 3. Term calculation
            start_date_val = payload.get('start_date')
            if start_date_val:
                if isinstance(start_date_val, str):
                    start_dt = date.fromisoformat(start_date_val)
                else:
                    start_dt = start_date_val
            else:
                start_dt = date.today()

            billing_cycle = plan.billing_cycle.upper()
            term_start, term_end, next_billing = SubscriptionService.calculate_term_dates(
                start_date=start_dt,
                billing_cycle=billing_cycle
            )

            # 4. Create Subscription Header
            sub_data = {
                "customer": customer,
                "status": "DRAFT",
                "currency": plan.currency or "USD",
                "collection_method": payload.get('collection_method', 'CHARGE_AUTOMATIC'),
                "payment_terms_days": payload.get('payment_terms_days', 0),
                "current_term_start": term_start,
                "current_term_end": term_end,
                "next_billing_date": next_billing,
                "billing_cycle": billing_cycle,
                "metadata": {
                    "crm_opportunity_id": opportunity_id,
                    "crm_company_id": company_id,
                    "provisioned_via": "crm_opportunity_won"
                }
            }
            sub = SubscriptionService.create_subscription(
                organization=organization,
                user=actor,
                validated_data=sub_data
            )

            # 5. Create Plan Item
            plan_qty = int(payload.get('plan_quantity', 1))
            SubscriptionItem.objects.create(
                subscription=sub,
                item_type='PLAN',
                plan=plan,
                quantity=plan_qty,
                unit_price=plan.price,
                discount_amount=Decimal('0.00')
            )

            # 6. Create Add-on Items if any
            add_ons_list = payload.get('add_ons', [])
            for item in add_ons_list:
                addon_id = item.get('addon_id')
                addon_qty = int(item.get('quantity', 1))
                addon = AddOn.objects.filter(id=addon_id, is_active=True).first()
                if not addon:
                    raise ValidationError({"add_ons": f"AddOn {addon_id} does not exist or is inactive."})
                SubscriptionItem.objects.create(
                    subscription=sub,
                    item_type='ADDON',
                    addon=addon,
                    quantity=addon_qty,
                    unit_price=addon.price,
                    discount_amount=Decimal('0.00')
                )

            # Recalculate MRR/ARR
            SubscriptionItemService.recalculate_subscription_mrr_arr(sub)

            # 7. State Transition to LIVE or FUTURE
            target_status = 'LIVE' if start_dt <= date.today() else 'FUTURE'
            SubscriptionStateMachineService.transition(
                subscription=sub,
                to_status=target_status,
                user=actor,
                reason="Closed-Won CRM Opportunity conversion",
                metadata={"crm_opportunity_id": opportunity_id}
            )

            return {
                "success": True,
                "idempotent": False,
                "subscription": sub,
                "customer": customer,
                "message": "Subscription provisioned successfully."
            }


class BillingAnalyticsService:
    """
    Authoritative Read-Only SaaS Analytics & Revenue Service.
    Calculates derived commercial KPIs and metrics from authoritative Billing records:
    - Subscriptions, SubscriptionItems, PricingPlans, AddOns, Invoices, Payments, Allocations.
    - Strictly read-only: performs zero DB mutations.
    - Strictly tenant-isolated and RBAC-scoped.
    - Uses Decimal arithmetic throughout.
    """
    ACTIVE_STATUSES = ('LIVE', 'TRIAL', 'NON_RENEWING', 'PAST_DUE')

    @classmethod
    def _get_scoped_subscriptions(cls, organization, user=None, scope='ALL'):
        if not organization or scope == 'NONE':
            return Subscription.objects.none()
        qs = Subscription.objects.filter(customer__organization=organization)
        if scope == 'OWN' and user:
            qs = qs.filter(Q(customer__metadata__created_by_id=user.id) | Q(metadata__created_by_id=user.id))
        return qs

    @classmethod
    def calculate_live_mrr(cls, organization, user=None, scope='ALL', as_of_date=None):
        """
        Calculates live MRR for an organization using active subscriptions and historical line item snapshots.
        """
        if not organization or scope == 'NONE':
            return Decimal('0.00')

        if as_of_date is None:
            eval_date = date.today()
        elif isinstance(as_of_date, str):
            eval_date = date.fromisoformat(as_of_date)
        else:
            eval_date = as_of_date

        subs = cls._get_scoped_subscriptions(organization, user=user, scope=scope).filter(
            status__in=cls.ACTIVE_STATUSES
        ).prefetch_related('items__plan', 'items__addon')

        total_mrr = Decimal('0.00')

        for sub in subs:
            for item in sub.items.all():
                if item.start_date and item.start_date > eval_date:
                    continue
                if item.end_date and item.end_date < eval_date:
                    continue

                unit_price = item.unit_price or Decimal('0.00')
                qty = item.quantity or 1
                discount = item.discount_amount or Decimal('0.00')
                item_total = max(Decimal('0.00'), (unit_price * Decimal(qty)) - discount)

                cycle = 'monthly'
                if item.item_type == 'PLAN' and item.plan:
                    cycle = (item.plan.billing_cycle or 'monthly').lower()
                elif item.item_type == 'ADDON' and item.addon:
                    cycle = (item.addon.billing_cycle or 'monthly').lower()

                if cycle == 'yearly':
                    mrr_contrib = (item_total / Decimal('12.00')).quantize(Decimal('0.01'))
                elif cycle == 'one_time':
                    mrr_contrib = Decimal('0.00')
                else:
                    mrr_contrib = item_total.quantize(Decimal('0.01'))

                total_mrr += mrr_contrib

        return total_mrr.quantize(Decimal('0.01'))

    @classmethod
    def calculate_live_arr(cls, organization, user=None, scope='ALL', as_of_date=None):
        """
        Derives live ARR from live MRR (MRR * 12).
        """
        live_mrr = cls.calculate_live_mrr(organization, user=user, scope=scope, as_of_date=as_of_date)
        return (live_mrr * Decimal('12.00')).quantize(Decimal('0.01'))

    @classmethod
    def calculate_churn_metrics(cls, organization, user=None, scope='ALL', period_days=30, end_date=None):
        """
        Calculates subscriber churn rate over a given measurement period.
        Churn Rate (%) = (Cancelled Subscriptions in Period / (Active Subscriptions + Cancelled Subscriptions)) * 100
        """
        if not organization or scope == 'NONE':
            return {
                "period_days": period_days,
                "active_count": 0,
                "cancelled_count": 0,
                "total_at_risk": 0,
                "subscriber_churn_rate_pct": Decimal('0.00')
            }

        if end_date is None:
            end_dt = date.today()
        elif isinstance(end_date, str):
            end_dt = date.fromisoformat(end_date)
        else:
            end_dt = end_date

        start_dt = end_dt - timedelta(days=period_days)

        scoped_subs = cls._get_scoped_subscriptions(organization, user=user, scope=scope)
        active_count = scoped_subs.filter(status__in=cls.ACTIVE_STATUSES).count()

        # Cancelled in period (via cancelled_at or audit logs or updated_at)
        canc_qs = scoped_subs.filter(status='CANCELLED')
        canc_filter = Q(cancelled_at__date__gte=start_dt, cancelled_at__date__lte=end_dt) | Q(
            audit_logs__action__in=['STATE_TRANSITION', 'SUBSCRIPTION_CANCELLED'],
            audit_logs__new_state='CANCELLED',
            audit_logs__timestamp__date__gte=start_dt,
            audit_logs__timestamp__date__lte=end_dt
        ) | Q(updated_at__date__gte=start_dt, updated_at__date__lte=end_dt)

        cancelled_count = canc_qs.filter(canc_filter).distinct().count()

        total_at_risk = active_count + cancelled_count
        if total_at_risk > 0 and cancelled_count > 0:
            churn_rate_pct = ((Decimal(str(cancelled_count)) / Decimal(str(total_at_risk))) * Decimal('100.00')).quantize(Decimal('0.01'))
        else:
            churn_rate_pct = Decimal('0.00')

        return {
            "period_days": period_days,
            "active_count": active_count,
            "cancelled_count": cancelled_count,
            "total_at_risk": total_at_risk,
            "subscriber_churn_rate_pct": churn_rate_pct
        }

    @classmethod
    def calculate_ltv(cls, organization, user=None, scope='ALL', period_days=30):
        """
        Calculates LTV = ARPU / Monthly Churn Rate.
        If churn rate is 0%, returns 12-month baseline realized projection.
        """
        if not organization or scope == 'NONE':
            return {
                "arpu": Decimal('0.00'),
                "ltv": Decimal('0.00'),
                "churn_rate_pct": Decimal('0.00')
            }

        live_mrr = cls.calculate_live_mrr(organization, user=user, scope=scope)
        churn_data = cls.calculate_churn_metrics(organization, user=user, scope=scope, period_days=period_days)
        active_count = churn_data['active_count']
        churn_pct = churn_data['subscriber_churn_rate_pct']

        if active_count > 0:
            arpu = (live_mrr / Decimal(str(active_count))).quantize(Decimal('0.01'))
        else:
            arpu = Decimal('0.00')

        if churn_pct > Decimal('0.00'):
            churn_fraction = churn_pct / Decimal('100.00')
            ltv = (arpu / churn_fraction).quantize(Decimal('0.01'))
        elif arpu > Decimal('0.00'):
            ltv = (arpu * Decimal('12.00')).quantize(Decimal('0.01'))
        else:
            ltv = Decimal('0.00')

        return {
            "arpu": arpu,
            "ltv": ltv,
            "churn_rate_pct": churn_pct
        }

    @classmethod
    def get_active_subscriber_breakdown(cls, organization, user=None, scope='ALL'):
        """
        Returns distributions of subscriptions by status, active plans, and billing cycles.
        """
        if not organization or scope == 'NONE':
            return {
                "by_status": {},
                "by_plan": {},
                "by_billing_cycle": {}
            }

        subs = cls._get_scoped_subscriptions(organization, user=user, scope=scope).select_related('customer').prefetch_related('items__plan')

        by_status = {}
        by_plan = {}
        by_billing_cycle = {}

        for sub in subs:
            # Status breakdown
            st = sub.status
            by_status[st] = by_status.get(st, 0) + 1

            if sub.status in cls.ACTIVE_STATUSES:
                # Plan breakdown
                plan_item = next((i for i in sub.items.all() if i.item_type == 'PLAN' and i.plan), None)
                if plan_item and plan_item.plan:
                    pname = plan_item.plan.name
                    by_plan[pname] = by_plan.get(pname, 0) + 1
                    cycle = (plan_item.plan.billing_cycle or 'monthly').lower()
                    by_billing_cycle[cycle] = by_billing_cycle.get(cycle, 0) + 1
                else:
                    by_billing_cycle['monthly'] = by_billing_cycle.get('monthly', 0) + 1

        return {
            "by_status": by_status,
            "by_plan": by_plan,
            "by_billing_cycle": by_billing_cycle
        }

    @classmethod
    def get_analytics_overview(cls, organization, user=None, scope='ALL'):
        """
        Aggregates authoritative executive overview metrics for the organization.
        """
        if not organization or scope == 'NONE':
            return {
                "live_mrr": "0.00",
                "live_arr": "0.00",
                "active_subscribers": 0,
                "arpu": "0.00",
                "ltv": "0.00",
                "churn_rate_pct": "0.00",
                "subscriber_breakdown": {"by_status": {}, "by_plan": {}, "by_billing_cycle": {}},
                "total_collected_revenue": "0.00"
            }

        mrr = cls.calculate_live_mrr(organization, user=user, scope=scope)
        arr = cls.calculate_live_arr(organization, user=user, scope=scope)
        ltv_data = cls.calculate_ltv(organization, user=user, scope=scope)
        churn_data = cls.calculate_churn_metrics(organization, user=user, scope=scope)
        breakdown = cls.get_active_subscriber_breakdown(organization, user=user, scope=scope)

        # Calculate total collected cash payments for the tenant
        payments_qs = Payment.objects.filter(customer__organization=organization, status='SUCCEEDED')
        if scope == 'OWN' and user:
            payments_qs = payments_qs.filter(customer__metadata__created_by_id=user.id)

        total_collected = sum((p.amount for p in payments_qs), Decimal('0.00')).quantize(Decimal('0.01'))

        return {
            "live_mrr": str(mrr),
            "live_arr": str(arr),
            "active_subscribers": churn_data['active_count'],
            "arpu": str(ltv_data['arpu']),
            "ltv": str(ltv_data['ltv']),
            "churn_rate_pct": str(churn_data['subscriber_churn_rate_pct']),
            "subscriber_breakdown": breakdown,
            "total_collected_revenue": str(total_collected)
        }

    @classmethod
    def get_mrr_movement(cls, organization, user=None, scope='ALL', months=6, end_date=None):
        """
        Generates deterministic monthly MRR movement buckets:
        - New MRR
        - Expansion MRR
        - Contraction MRR
        - Churned MRR
        - Reactivation MRR
        - Net MRR Growth
        - Ending MRR
        """
        if not organization or scope == 'NONE':
            return []

        if end_date is None:
            end_dt = date.today()
        elif isinstance(end_date, str):
            end_dt = date.fromisoformat(end_date)
        else:
            end_dt = end_date

        months_list = []
        cur_year = end_dt.year
        cur_month = end_dt.month

        for i in range(months - 1, -1, -1):
            m = cur_month - i
            y = cur_year
            while m <= 0:
                m += 12
                y -= 1
            months_list.append((y, m))

        scoped_subs = cls._get_scoped_subscriptions(organization, user=user, scope=scope)
        results = []

        for y, m in months_list:
            period_str = f"{y:04d}-{m:02d}"
            # Month start and end dates
            start_of_month = date(y, m, 1)
            if m == 12:
                end_of_month = date(y + 1, 1, 1) - timedelta(days=1)
            else:
                end_of_month = date(y, m + 1, 1) - timedelta(days=1)

            # Query change logs & audit logs in this month window
            new_mrr = Decimal('0.00')
            expansion_mrr = Decimal('0.00')
            contraction_mrr = Decimal('0.00')
            churned_mrr = Decimal('0.00')
            reactivation_mrr = Decimal('0.00')

            # Subscriptions created in this month
            created_subs = scoped_subs.filter(
                created_at__year=y,
                created_at__month=m
            )
            for s in created_subs:
                new_mrr += (s.cached_mrr or Decimal('0.00'))

            # Check change logs for upgrades / downgrades / addons
            change_logs = SubscriptionChangeLog.objects.filter(
                subscription__in=scoped_subs,
                effective_date__year=y,
                effective_date__month=m
            )
            for cl in change_logs:
                ctype = (cl.change_type or '').upper()
                det = cl.details or {}
                delta = Decimal(str(det.get('mrr_delta', '0.00'))) if 'mrr_delta' in det else (cl.proration_amount or Decimal('0.00'))
                if ctype in ('PLAN_UPGRADE', 'UPGRADE') or delta > Decimal('0.00'):
                    expansion_mrr += abs(delta)
                elif ctype in ('PLAN_DOWNGRADE', 'DOWNGRADE') or delta < Decimal('0.00'):
                    contraction_mrr += abs(delta)
                elif ctype == 'ADDON_AMENDMENT':
                    if delta >= Decimal('0.00'):
                        expansion_mrr += delta
                    else:
                        contraction_mrr += abs(delta)

            # Check cancellations in this month
            canc_subs = scoped_subs.filter(
                status='CANCELLED',
                cancelled_at__year=y,
                cancelled_at__month=m
            )
            for s in canc_subs:
                churned_mrr += (s.cached_mrr or Decimal('0.00'))

            # Net growth
            net_growth = (new_mrr + expansion_mrr + reactivation_mrr - contraction_mrr - churned_mrr).quantize(Decimal('0.01'))

            # Ending MRR as of end_of_month
            ending_mrr = cls.calculate_live_mrr(organization, user=user, scope=scope, as_of_date=end_of_month)

            results.append({
                "period": period_str,
                "new_mrr": str(new_mrr.quantize(Decimal('0.01'))),
                "expansion_mrr": str(expansion_mrr.quantize(Decimal('0.01'))),
                "contraction_mrr": str(contraction_mrr.quantize(Decimal('0.01'))),
                "churned_mrr": str(churned_mrr.quantize(Decimal('0.01'))),
                "reactivation_mrr": str(reactivation_mrr.quantize(Decimal('0.01'))),
                "net_mrr_growth": str(net_growth),
                "ending_mrr": str(ending_mrr.quantize(Decimal('0.01')))
            })

        return results

