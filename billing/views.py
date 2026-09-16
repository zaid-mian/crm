import json
from django.utils import timezone
from django.db.models import Q
from rest_framework import viewsets, status, permissions

from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from roles.permissions import DynamicCRMPermission
from roles.services import PermissionService
from billing.models import (
    BillingCustomer,
    Subscription,
    AddOn,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
    CreditNote,
    CreditNoteAllocation,
    DebitNote,
    WebhookInbox,
    DunningLog,
    SubscriptionAuditLog,
    SubscriptionChangeLog,
)
from catalog.models.plan import PricingPlan
from rest_framework.views import APIView
from django.db import IntegrityError, transaction
from billing.serializers import (
    BillingCustomerSerializer,
    SubscriptionSerializer,
    SubscriptionDetailSerializer,
    SubscriptionItemSerializer,
    AvailablePlanSerializer,
    AvailableAddonSerializer,
    SubscriptionTransitionSerializer,
    SubscriptionCancelSerializer,
    SubscriptionPauseSerializer,
    SubscriptionResumeSerializer,
    SubscriptionProrationPreviewSerializer,
    SubscriptionAmendSerializer,
    InvoiceSerializer,
    InvoiceDetailSerializer,
    InvoiceGenerateSerializer,
    InvoiceLineSerializer,
    PaymentSerializer,
    PaymentAllocationSerializer,
    PaymentCreateSerializer,
    PaymentAllocateSerializer,
    PaymentMethodAttachSerializer,
    CreditNoteSerializer,
    CreditNoteAllocationSerializer,
    CreditNoteIssueSerializer,
    CreditNoteAllocateSerializer,
    DebitNoteSerializer,
    DebitNoteIssueSerializer,
    DunningLogSerializer,
    SubscriptionAuditLogSerializer,
    SubscriptionChangeLogSerializer,
    UnifiedAuditActivitySerializer,
    EntitlementCheckQuerySerializer,
    WonOpportunityProvisionSerializer,
    AnalyticsOverviewSerializer,
    MrrMovementResponseSerializer,
)
from billing.services import (
    CustomerService,
    SubscriptionService,
    SubscriptionItemService,
    SubscriptionStateMachineService,
    SubscriptionLifecycleService,
    ProrationService,
    SubscriptionAmendmentService,
    InvoicingEngineService,
    PaymentService,
    PaymentAllocationService,
    CreditNoteService,
    DebitNoteService,
    CreditNoteAllocationService,
    WebhookInboxProcessor,
    SubscriptionRenewalService,
    DunningService,
    EntitlementService,
    CrmOpportunityProvisioningService,
    BillingAnalyticsService,
)

from billing.gateways import StripeGatewayService
from billing.documents import generate_invoice_pdf
from billing.utils.tenant import get_billing_tenant_organization



class BillingCustomerPermission(DynamicCRMPermission):
    """
    Extends DynamicCRMPermission to support metadata-based ownership for BillingCustomer
    without modifying database schema.
    """
    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True

        codename = self.get_resource_codename(view)
        if not codename:
            return True

        action = self.get_action(request, view)

        scope = PermissionService.get_permission_scope(request.user, codename, action)
        if scope == 'ALL':
            return True

        if scope == 'OWN':
            created_by_id = obj.metadata.get('created_by_id') if (obj.metadata and isinstance(obj.metadata, dict)) else None
            return created_by_id == request.user.id

        return False


class BillingCustomerViewSet(viewsets.ModelViewSet):
    """
    REST ViewSet managing BillingCustomer domain operations with authoritative
    tenant isolation and RBAC scope filtering.
    """
    serializer_class = BillingCustomerSerializer
    permission_classes = [BillingCustomerPermission]
    resource_codename = 'billing_customers'
    owner_field = 'created_by'

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return BillingCustomer.objects.none()

        queryset = BillingCustomer.objects.all()

        # 1. Tenant Organization Isolation
        org = get_billing_tenant_organization(user)
        if org is not None:
            queryset = queryset.filter(organization=org)
        else:
            if not (user.is_superuser or user.is_staff):
                return queryset.none()

        # 2. RBAC Permission Scope Resolution
        scope = PermissionService.get_permission_scope(user, self.resource_codename, 'VIEW')
        if scope == 'ALL':
            pass
        elif scope == 'OWN':
            queryset = queryset.filter(metadata__created_by_id=user.id)
        else:
            return queryset.none()

        # 3. Search Filter (?search=<query>) across approved fields
        search_query = self.request.query_params.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(email__icontains=search_query) |
                Q(customer_number__icontains=search_query)
            )

        # 4. External Reference Filter (?external_reference_id=<value>)
        ext_ref = self.request.query_params.get('external_reference_id', '').strip()
        if ext_ref:
            queryset = queryset.filter(external_reference_id=ext_ref)

        return queryset

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if request.user.is_superuser:
            return

        # Tenant isolation check
        org = get_billing_tenant_organization(request.user)
        if org is not None and obj.organization_id != org.id:
            raise PermissionDenied("You do not have permission to access customers outside your organization.")

    def perform_create(self, serializer):
        org = get_billing_tenant_organization(self.request.user)
        customer = CustomerService.create_customer(
            organization=org,
            user=self.request.user,
            validated_data=serializer.validated_data
        )
        serializer.instance = customer

    def destroy(self, request, *args, **kwargs):
        """Soft delete deactivation setting is_active = False."""
        customer = self.get_object()
        customer.is_active = False
        customer.save(update_fields=['is_active', 'updated_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class SubscriptionPermission(DynamicCRMPermission):
    """
    Extends DynamicCRMPermission to support metadata-based ownership for Subscription
    without modifying database schema.
    """
    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True

        codename = self.get_resource_codename(view)
        if not codename:
            return True

        action = self.get_action(request, view)

        scope = PermissionService.get_permission_scope(request.user, codename, action)
        if scope == 'ALL':
            return True

        if scope == 'OWN':
            created_by_id = obj.metadata.get('created_by_id') if (obj.metadata and isinstance(obj.metadata, dict)) else None
            return created_by_id == request.user.id

        return False


class SubscriptionViewSet(viewsets.ModelViewSet):
    """
    REST ViewSet managing Subscription header domain operations with authoritative
    tenant isolation and RBAC scope filtering.
    """
    serializer_class = SubscriptionSerializer
    permission_classes = [SubscriptionPermission]
    resource_codename = 'billing_subscriptions'
    owner_field = 'created_by'

    def get_serializer_class(self):
        if self.action in ['retrieve']:
            return SubscriptionDetailSerializer
        return SubscriptionSerializer

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return Subscription.objects.none()

        queryset = Subscription.objects.select_related('customer').all()

        # 1. Tenant Organization Isolation
        org = get_billing_tenant_organization(user)
        if org is not None:
            queryset = queryset.filter(customer__organization=org)
        else:
            if not (user.is_superuser or user.is_staff):
                return queryset.none()

        # 2. RBAC Permission Scope Resolution
        scope = PermissionService.get_permission_scope(user, self.resource_codename, 'VIEW')
        if scope == 'ALL':
            pass
        elif scope == 'OWN':
            queryset = queryset.filter(metadata__created_by_id=user.id)
        else:
            return queryset.none()

        # 3. Query Parameter Filters
        search_query = self.request.query_params.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(subscription_number__icontains=search_query) |
                Q(customer__name__icontains=search_query) |
                Q(customer__customer_number__icontains=search_query)
            )

        status_param = self.request.query_params.get('status', '').strip()
        if status_param:
            queryset = queryset.filter(status=status_param.upper())

        customer_param = self.request.query_params.get('customer', '').strip()
        if customer_param and customer_param.isdigit():
            queryset = queryset.filter(customer_id=int(customer_param))

        collection_param = self.request.query_params.get('collection_method', '').strip()
        if collection_param:
            queryset = queryset.filter(collection_method=collection_param.upper())

        return queryset

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if request.user.is_superuser:
            return

        # Tenant isolation check
        org = get_billing_tenant_organization(request.user)
        if org is not None and obj.customer.organization_id != org.id:
            raise PermissionDenied("You do not have permission to access subscriptions outside your organization.")

    def perform_create(self, serializer):
        org = get_billing_tenant_organization(self.request.user)
        customer = serializer.validated_data.get('customer')
        if org is not None and customer.organization_id != org.id:
            raise PermissionDenied("Cannot create subscription for customer outside your organization.")

        subscription = SubscriptionService.create_subscription(
            organization=org,
            user=self.request.user,
            validated_data=serializer.validated_data
        )
        serializer.instance = subscription

    @action(detail=False, methods=['get'], url_path='available-plans', url_name='available-plans')
    def available_plans(self, request):
        plans = PricingPlan.objects.filter(is_active=True)
        serializer = AvailablePlanSerializer(plans, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='available-addons', url_name='available-addons')
    def available_addons(self, request):
        addons = AddOn.objects.filter(is_active=True)
        serializer = AvailableAddonSerializer(addons, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='items', url_name='items')
    def add_item(self, request, pk=None):
        subscription = self.get_object()
        serializer = SubscriptionItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = SubscriptionItemService.add_item_to_subscription(
            subscription=subscription,
            user=request.user,
            validated_data=serializer.validated_data
        )
        response_serializer = SubscriptionItemSerializer(item)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path=r'items/(?P<item_id>\d+)', url_name='remove-item')
    def remove_item(self, request, pk=None, item_id=None):
        subscription = self.get_object()
        SubscriptionItemService.remove_item_from_subscription(
            subscription=subscription,
            item_id=item_id
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='transition', url_name='transition')
    def transition(self, request, pk=None):
        subscription = self.get_object()
        serializer = SubscriptionTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated_sub = SubscriptionStateMachineService.transition(
            subscription=subscription,
            to_status=serializer.validated_data['to_status'],
            user=request.user,
            reason=serializer.validated_data.get('reason', ''),
            metadata=serializer.validated_data.get('metadata', {})
        )
        response_serializer = SubscriptionDetailSerializer(updated_sub)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='cancel', url_name='cancel')
    def cancel(self, request, pk=None):
        """
        Cancels a subscription (IMMEDIATE or PERIOD_END).
        Enforces RBAC and tenant isolation via SubscriptionPermission.
        """
        subscription = self.get_object()
        serializer = SubscriptionCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated_sub = SubscriptionLifecycleService.cancel_subscription(
            subscription=subscription,
            cancel_type=serializer.validated_data.get('cancel_type', 'IMMEDIATE'),
            reason=serializer.validated_data['reason'],
            user=request.user
        )
        response_serializer = SubscriptionDetailSerializer(updated_sub)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='pause', url_name='pause')
    def pause(self, request, pk=None):
        """
        Pauses a LIVE subscription immediately.
        Enforces RBAC and tenant isolation via SubscriptionPermission.
        """
        subscription = self.get_object()
        serializer = SubscriptionPauseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated_sub = SubscriptionLifecycleService.pause_subscription(
            subscription=subscription,
            reason=serializer.validated_data['reason'],
            user=request.user
        )
        response_serializer = SubscriptionDetailSerializer(updated_sub)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='resume', url_name='resume')
    def resume(self, request, pk=None):
        """
        Resumes a PAUSED subscription immediately with term extension.
        Enforces RBAC and tenant isolation via SubscriptionPermission.
        """
        subscription = self.get_object()
        serializer = SubscriptionResumeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated_sub = SubscriptionLifecycleService.resume_subscription(
            subscription=subscription,
            user=request.user
        )
        response_serializer = SubscriptionDetailSerializer(updated_sub)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='preview-amend', url_name='preview_amend')
    def preview_amend(self, request, pk=None):
        """
        Calculates a read-only proration preview for plan/add-on amendments.
        Zero DB mutations. Enforces RBAC & tenant isolation.
        """
        subscription = self.get_object()
        serializer = SubscriptionProrationPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        proration_result = ProrationService.calculate_proration(
            subscription=subscription,
            new_plan_id=serializer.validated_data.get('new_plan_id'),
            add_ons=serializer.validated_data.get('add_ons'),
            effective_date=serializer.validated_data.get('effective_date')
        )
        return Response(proration_result, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='amend', url_name='amend')
    def amend(self, request, pk=None):
        """
        Commits a subscription amendment transactionally with server-side proration
        recalculation, historical snapshot preservation, and audit logging.
        """
        subscription = self.get_object()
        serializer = SubscriptionAmendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = SubscriptionAmendmentService.apply_amendment(
            subscription=subscription,
            new_plan_id=serializer.validated_data.get('new_plan_id'),
            add_ons=serializer.validated_data.get('add_ons'),
            reason=serializer.validated_data['reason'],
            user=request.user,
            effective_date=serializer.validated_data.get('effective_date')
        )

        response_data = {
            "success": True,
            "subscription": SubscriptionDetailSerializer(result['subscription']).data,
            "proration": {
                "net_amount": result['proration']['net_amount'],
                "total_credit": result['proration']['total_credit'],
                "total_charge": result['proration']['total_charge'],
                "is_upgrade": result['proration']['is_upgrade'],
                "is_downgrade": result['proration']['is_downgrade'],
                "invoice_id": result['invoice'].id if result.get('invoice') else None,
                "invoice_number": result['invoice'].invoice_number if result.get('invoice') else None
            }
        }
        return Response(response_data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='run-renewals', url_name='run_renewals')
    def run_renewals(self, request):
        """
        Administrative / Scheduled trigger endpoint executing automated subscription renewals.
        - Enforces RBAC Admin/Manager permissions (Salesperson denied).
        - Multi-tenant isolated to requesting user's organization.
        - Delegates processing to SubscriptionRenewalService.process_due_renewals.
        """
        if not request.user or not request.user.is_authenticated:
            raise PermissionDenied("Authentication credentials were not provided.")

        perm_scope = PermissionService.get_permission_scope(request.user, 'billing_subscriptions', 'CREATE')
        if perm_scope != 'ALL':
            raise PermissionDenied("Administrative permission with ALL scope on billing subscriptions is required to trigger subscription renewals.")


        org = get_billing_tenant_organization(request.user)
        batch_size = request.data.get('batch_size') or request.query_params.get('batch_size') or 50

        results = SubscriptionRenewalService.process_due_renewals(
            organization=org,
            user=request.user,
            batch_size=batch_size
        )

        return Response(results, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='dunning-history', url_name='dunning_history')
    def dunning_history(self, request, pk=None):
        """
        Retrieves historical DunningLog records for a specific subscription.
        Respects tenant isolation and RBAC scope.
        """
        subscription = self.get_object()
        logs = DunningLog.objects.filter(subscription=subscription).order_by('-timestamp')
        serializer = DunningLogSerializer(logs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='audit-logs', url_name='audit_logs')
    def audit_logs(self, request, pk=None):
        """
        Returns a unified, chronologically sorted activity feed for a given subscription,
        combining SubscriptionAuditLog, SubscriptionChangeLog, and DunningLog.
        """
        subscription = self.get_object()

        audit_records = list(subscription.audit_logs.all())
        change_records = list(subscription.change_logs.all())
        dunning_records = list(subscription.dunning_logs.all())

        feed = []

        for log in audit_records:
            feed.append({
                'id': f"audit_{log.id}",
                'subscription': subscription.id,
                'subscription_number': subscription.subscription_number,
                'category': 'LIFECYCLE' if log.action in ['STATE_TRANSITION', 'SUBSCRIPTION_CREATED', 'CANCEL_SCHEDULED', 'CANCEL_IMMEDIATE', 'PAUSE_EXECUTED', 'RESUME_EXECUTED', 'RENEWAL_COMPLETED'] else 'FINANCIAL',
                'action': log.action,
                'title': log.action.replace('_', ' ').title(),
                'actor_type': log.actor_type,
                'actor_id': log.actor_id,
                'actor_name': log.metadata.get('actor_username') if isinstance(log.metadata, dict) else None,
                'timestamp': log.timestamp,
                'reason': log.reason,
                'state_delta': {'old': log.old_state, 'new': log.new_state} if (log.old_state or log.new_state) else {},
                'details': log.metadata if isinstance(log.metadata, dict) else {},
                'proration_amount': '0.00',
            })

        for chg in change_records:
            actor_id = chg.details.get('actor_id') if isinstance(chg.details, dict) else None
            actor_username = chg.details.get('actor_username') if isinstance(chg.details, dict) else None
            feed.append({
                'id': f"change_{chg.id}",
                'subscription': subscription.id,
                'subscription_number': subscription.subscription_number,
                'category': 'AMENDMENT',
                'action': chg.change_type,
                'title': chg.change_type.replace('_', ' ').title(),
                'actor_type': 'USER',
                'actor_id': str(actor_id) if actor_id else None,
                'actor_name': actor_username,
                'timestamp': chg.timestamp,
                'reason': chg.details.get('reason', '') if isinstance(chg.details, dict) else '',
                'state_delta': {},
                'details': chg.details if isinstance(chg.details, dict) else {},
                'proration_amount': str(chg.proration_amount),
            })

        for dunn in dunning_records:
            feed.append({
                'id': f"dunning_{dunn.id}",
                'subscription': subscription.id,
                'subscription_number': subscription.subscription_number,
                'category': 'DUNNING',
                'action': f"DUNNING_ATTEMPT_{dunn.attempt_number}",
                'title': f"Dunning Attempt #{dunn.attempt_number} ({dunn.status})",
                'actor_type': 'SYSTEM',
                'actor_id': 'SYSTEM',
                'actor_name': 'Dunning Engine',
                'timestamp': dunn.timestamp,
                'reason': dunn.error_message or '',
                'state_delta': {},
                'details': {
                    'status': dunn.status,
                    'attempt_number': dunn.attempt_number,
                    'error_code': dunn.error_code,
                    'invoice_id': dunn.invoice_id,
                },
                'proration_amount': '0.00',
            })

        feed.sort(key=lambda x: (x['timestamp'], x['id']), reverse=True)

        category_param = request.query_params.get('category', '').strip().upper()
        if category_param and category_param != 'ALL':
            feed = [item for item in feed if item['category'] == category_param]

        serializer = UnifiedAuditActivitySerializer(feed, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='run-dunning', url_name='run_dunning')
    def run_dunning(self, request):
        """
        Administrative trigger endpoint executing scheduled dunning retries across subscriptions.
        - Enforces RBAC ALL scope check on 'billing' 'CREATE' or 'UPDATE'.
        - Multi-tenant isolated to requesting user's organization.
        """
        if not request.user or not request.user.is_authenticated:
            raise PermissionDenied("Authentication credentials were not provided.")

        perm_scope = PermissionService.get_permission_scope(request.user, 'billing_subscriptions', 'CREATE')
        if perm_scope != 'ALL':
            raise PermissionDenied("Administrative permission with ALL scope on billing subscriptions is required to trigger dunning retries.")

        force = request.data.get('force', False) if isinstance(request.data, dict) else False
        org = get_billing_tenant_organization(request.user)
        results = DunningService.process_dunning_retries(organization=org, force_next_attempt=bool(force))
        return Response(results, status=status.HTTP_200_OK)




class InvoicePermission(DynamicCRMPermission):
    """
    Extends DynamicCRMPermission for Invoice domain operations with multi-tenant
    and metadata-based ownership scoping.
    """
    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True

        codename = self.get_resource_codename(view)
        if not codename:
            return True

        action = self.get_action(request, view)
        scope = PermissionService.get_permission_scope(request.user, codename, action)
        if scope == 'ALL':
            return True

        if scope == 'OWN':
            created_by_id = obj.customer.metadata.get('created_by_id') if (obj.customer.metadata and isinstance(obj.customer.metadata, dict)) else None
            return created_by_id == request.user.id

        return False


class InvoiceViewSet(viewsets.ModelViewSet):
    """
    REST ViewSet managing Invoice domain operations with authoritative tenant isolation,
    RBAC scope filtering, deterministic invoice generation, and PDF streaming.
    """
    serializer_class = InvoiceSerializer
    permission_classes = [InvoicePermission]
    resource_codename = 'billing_invoices'
    owner_field = 'created_by'

    def get_serializer_class(self):
        if self.action in ['retrieve']:
            return InvoiceDetailSerializer
        elif self.action in ['create']:
            return InvoiceGenerateSerializer
        return InvoiceSerializer

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return Invoice.objects.none()

        queryset = Invoice.objects.select_related('customer', 'subscription').all()

        # 1. Tenant Isolation
        org = get_billing_tenant_organization(user)
        if org is not None:
            queryset = queryset.filter(customer__organization=org)
        else:
            if not (user.is_superuser or user.is_staff):
                return queryset.none()

        # 2. RBAC Permission Scope Resolution
        scope = PermissionService.get_permission_scope(user, self.resource_codename, 'VIEW')
        if scope == 'ALL':
            pass
        elif scope == 'OWN':
            queryset = queryset.filter(customer__metadata__created_by_id=user.id)
        else:
            return queryset.none()

        # 3. Query Parameter Filters
        search_query = self.request.query_params.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(invoice_number__icontains=search_query) |
                Q(customer__name__icontains=search_query) |
                Q(customer__customer_number__icontains=search_query) |
                Q(subscription__subscription_number__icontains=search_query)
            )

        status_param = self.request.query_params.get('status', '').strip()
        if status_param:
            queryset = queryset.filter(status=status_param.upper())

        customer_param = self.request.query_params.get('customer', '').strip()
        if customer_param and customer_param.isdigit():
            queryset = queryset.filter(customer_id=int(customer_param))

        subscription_param = self.request.query_params.get('subscription', '').strip()
        if subscription_param and subscription_param.isdigit():
            queryset = queryset.filter(subscription_id=int(subscription_param))

        return queryset

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if request.user.is_superuser:
            return

        org = get_billing_tenant_organization(request.user)
        if org is not None and obj.customer.organization_id != org.id:
            raise PermissionDenied("You do not have permission to access invoices outside your organization.")

    def create(self, request, *args, **kwargs):
        serializer = InvoiceGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        subscription = serializer.validated_data['subscription']

        # Tenant isolation check on parent subscription/customer
        org = get_billing_tenant_organization(request.user)
        if org is not None and subscription.customer.organization_id != org.id:
            raise PermissionDenied("Cannot generate invoice for subscription outside your organization.")

        invoice = InvoicingEngineService.generate_invoice(
            subscription=subscription,
            billing_period_start=serializer.validated_data.get('billing_period_start'),
            billing_period_end=serializer.validated_data.get('billing_period_end'),
            issue_date=serializer.validated_data.get('issue_date'),
            due_date=serializer.validated_data.get('due_date'),
            user=request.user
        )

        response_serializer = InvoiceDetailSerializer(invoice)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='pdf', url_name='pdf')
    def pdf(self, request, pk=None):
        invoice = self.get_object()
        return generate_invoice_pdf(invoice)


class PaymentPermission(DynamicCRMPermission):
    """
    Extends DynamicCRMPermission for Payment operations with multi-tenant
    and metadata-based ownership scoping.
    """
    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True

        codename = self.get_resource_codename(view)
        if not codename:
            return True

        action = self.get_action(request, view)
        scope = PermissionService.get_permission_scope(request.user, codename, action)
        if scope == 'ALL':
            return True

        if scope == 'OWN':
            created_by_id = obj.customer.metadata.get('created_by_id') if (obj.customer.metadata and isinstance(obj.customer.metadata, dict)) else None
            return created_by_id == request.user.id

        return False


class PaymentViewSet(viewsets.ModelViewSet):
    """
    Standalone REST ViewSet for Payment Receipts and Multi-Invoice Allocations under /api/v1/billing/payments/.
    """
    serializer_class = PaymentSerializer
    permission_classes = [PaymentPermission]
    resource_codename = 'billing_payments'
    owner_field = 'created_by'
    search_fields = ['payment_number', 'gateway_transaction_id', 'customer__name', 'notes']

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return Payment.objects.none()

        qs = Payment.objects.select_related('customer').prefetch_related('allocations__invoice').all()

        # 1. Tenant Organization Isolation
        org = get_billing_tenant_organization(user)
        if org is not None:
            qs = qs.filter(customer__organization=org)
        else:
            if not (user.is_superuser or user.is_staff):
                return Payment.objects.none()

        # 2. RBAC Permission Scope Resolution
        scope = PermissionService.get_permission_scope(user, self.resource_codename, 'VIEW')
        if scope == 'ALL':
            pass
        elif scope == 'OWN':
            qs = qs.filter(customer__metadata__created_by_id=user.id)
        else:
            return Payment.objects.none()

        customer_id = self.request.query_params.get('customer') or self.request.query_params.get('customer_id')
        if customer_id:
            qs = qs.filter(customer_id=customer_id)

        subscription_id = self.request.query_params.get('subscription') or self.request.query_params.get('subscription_id')
        if subscription_id:
            qs = qs.filter(customer__subscriptions__id=subscription_id).distinct()

        return qs

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if request.user.is_superuser:
            return

        org = get_billing_tenant_organization(request.user)
        if org is not None and obj.customer.organization_id != org.id:
            raise PermissionDenied("You do not have permission to access payments outside your organization.")

    def create(self, request, *args, **kwargs):
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        customer = serializer.validated_data['customer']

        org = get_billing_tenant_organization(request.user)
        if org is not None and customer.organization_id != org.id:
            raise PermissionDenied("Cannot record payment for customer outside your organization.")

        payment = PaymentService.record_payment(
            customer=customer,
            amount=serializer.validated_data['amount'],
            currency=serializer.validated_data.get('currency', 'USD'),
            payment_method=serializer.validated_data.get('payment_method', 'CREDIT_CARD'),
            payment_method_id=serializer.validated_data.get('payment_method_id', ''),
            gateway_transaction_id=serializer.validated_data.get('gateway_transaction_id', ''),
            payment_date=serializer.validated_data.get('payment_date'),
            notes=serializer.validated_data.get('notes', '')
        )

        response_serializer = PaymentSerializer(payment)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='allocate', url_name='allocate')
    def allocate(self, request, pk=None):
        payment = self.get_object()

        serializer = PaymentAllocateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = PaymentAllocationService.allocate_payment(
            payment_id=payment.id,
            allocations_data=serializer.validated_data['allocations'],
            user=request.user
        )

        response_serializer = PaymentSerializer(result['payment'])
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='attach-payment-method', url_name='attach_payment_method')
    def attach_payment_method(self, request):
        serializer = PaymentMethodAttachSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        customer = serializer.validated_data['customer']
        pm_id = serializer.validated_data['payment_method_id']
        set_as_default = serializer.validated_data.get('set_as_default', True)

        # 1. Tenant organization isolation check
        org = get_billing_tenant_organization(request.user)
        if org is not None and customer.organization_id != org.id:
            raise PermissionDenied("Cannot manage payment methods for customer outside your organization.")

        # 2. RBAC ownership check (OWN vs ALL scope)
        perm_scope = PermissionService.get_permission_scope(request.user, 'billing_payments', 'CREATE')
        if perm_scope == 'OWN':
            created_by = (customer.metadata or {}).get('created_by_id')
            if str(created_by) != str(request.user.id):
                raise PermissionDenied("You do not have permission to attach payment methods to customers owned by others.")
        elif perm_scope == 'NONE':
            raise PermissionDenied("You do not have permission to perform billing operations.")

        result = StripeGatewayService().attach_payment_method(
            customer=customer,
            payment_method_id=pm_id,
            set_as_default=set_as_default
        )

        return Response({
            "success": True,
            "customer_id": customer.id,
            "default_payment_method_id": customer.default_payment_method_id,
            "payment_method_details": (customer.metadata or {}).get('payment_method_details', {})
        }, status=status.HTTP_200_OK)


class PaymentMethodAttachView(APIView):
    """
    Standalone REST View for attaching safe Stripe payment methods.
    POST /api/v1/billing/payment-methods/attach/
    """
    permission_classes = [PaymentPermission]

    def post(self, request):
        serializer = PaymentMethodAttachSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        customer = serializer.validated_data['customer']
        pm_id = serializer.validated_data['payment_method_id']
        set_as_default = serializer.validated_data.get('set_as_default', True)

        org = get_billing_tenant_organization(request.user)
        if org is not None and customer.organization_id != org.id:
            raise PermissionDenied("Cannot manage payment methods for customer outside your organization.")

        perm_scope = PermissionService.get_permission_scope(request.user, 'billing_payments', 'CREATE')
        if perm_scope == 'OWN':
            created_by = (customer.metadata or {}).get('created_by_id')
            if str(created_by) != str(request.user.id):
                raise PermissionDenied("You do not have permission to attach payment methods to customers owned by others.")
        elif perm_scope == 'NONE':
            raise PermissionDenied("You do not have permission to perform billing operations.")

        try:
            result = StripeGatewayService().attach_payment_method(
                customer=customer,
                payment_method_id=pm_id,
                set_as_default=set_as_default
            )
        except Exception as e:
            return Response(
                {"error": f"Failed to attach payment method: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({
            "success": True,
            "payment_method_id": pm_id,
            "customer_id": customer.id,
            "default_payment_method_id": customer.default_payment_method_id,
            "payment_method_details": (customer.metadata or {}).get('payment_method_details', {})
        }, status=status.HTTP_200_OK)



class StripeWebhookView(APIView):
    """
    Cryptographically authenticated endpoint for Stripe Webhook ingestion.
    POST /api/v1/billing/webhooks/stripe/
    Unauthenticated via DRF session/JWT token; authenticated strictly via Stripe-Signature header.
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request, *args, **kwargs):
        payload_bytes = request.body
        sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

        # 1. Cryptographic Signature Verification using Stripe SDK
        try:
            event = StripeGatewayService().verify_webhook_signature(payload_bytes, sig_header)
        except Exception as e:
            return Response(
                {"error": f"Cryptographic signature verification failed: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        event_id = getattr(event, 'id', None) or event.get('id', '')
        event_type = getattr(event, 'type', None) or event.get('type', '')
        if isinstance(event, dict):
            event_dict = event
        else:
            try:
                event_dict = json.loads(payload_bytes.decode('utf-8'))
            except Exception:
                event_dict = {"id": event_id, "type": event_type}


        if not event_id or not event_type:
            return Response(
                {"error": "Invalid or missing Stripe event structure."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2. Database-Enforced Idempotent Webhook Ingestion (Layer 1 Deduplication)
        try:
            with transaction.atomic():
                inbox_item = WebhookInbox.objects.create(
                    event_id=event_id,
                    gateway='STRIPE',
                    event_type=event_type,
                    payload=event_dict,
                    status='PENDING'
                )
        except IntegrityError:

            # Duplicate event_id delivered twice by Stripe
            return Response(
                {"received": True, "message": "Duplicate event ID acknowledged without reprocessing", "event_id": event_id},
                status=status.HTTP_200_OK
            )

        # 3. Process supported events via WebhookInboxProcessor
        if event_type in ['payment_intent.succeeded', 'payment_intent.payment_failed']:
            WebhookInboxProcessor.process_inbox_item(inbox_item)
        else:
            inbox_item.status = 'PROCESSED'
            inbox_item.processed_at = timezone.now()
            inbox_item.error_message = f"Acknowledged unhandled event type '{event_type}'."
            inbox_item.save(update_fields=['status', 'processed_at', 'error_message'])

        return Response(
            {
                "received": True,
                "event_id": event_id,
                "event_type": event_type,
                "status": inbox_item.status
            },
            status=status.HTTP_200_OK
        )


class CreditNotePermission(DynamicCRMPermission):
    """
    Extends DynamicCRMPermission for CreditNote operations with multi-tenant
    and metadata-based ownership scoping.
    """
    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True

        codename = self.get_resource_codename(view)
        if not codename:
            return True

        action = self.get_action(request, view)
        scope = PermissionService.get_permission_scope(request.user, codename, action)
        if scope == 'ALL':
            return True

        if scope == 'OWN':
            created_by_id = obj.customer.metadata.get('created_by_id') if (obj.customer.metadata and isinstance(obj.customer.metadata, dict)) else None
            return created_by_id == request.user.id

        return False


class CreditNoteViewSet(viewsets.ModelViewSet):
    """
    Standalone REST ViewSet for Credit Notes and Allocations under /api/v1/billing/credit-notes/.
    """
    serializer_class = CreditNoteSerializer
    permission_classes = [CreditNotePermission]
    resource_codename = 'billing_payments'
    owner_field = 'created_by'
    search_fields = ['credit_note_number', 'customer__name', 'reason']

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return CreditNote.objects.none()

        qs = CreditNote.objects.select_related('customer', 'invoice').prefetch_related('allocations__invoice').all()

        # 1. Tenant Organization Isolation
        org = get_billing_tenant_organization(user)
        if org is not None:
            qs = qs.filter(customer__organization=org)
        else:
            if not (user.is_superuser or user.is_staff):
                return CreditNote.objects.none()

        # 2. RBAC Permission Scope Resolution
        scope = PermissionService.get_permission_scope(user, self.resource_codename, 'VIEW')
        if scope == 'ALL':
            pass
        elif scope == 'OWN':
            qs = qs.filter(customer__metadata__created_by_id=user.id)
        else:
            return CreditNote.objects.none()

        # Query Filters
        search_query = self.request.query_params.get('search', '').strip()
        if search_query:
            qs = qs.filter(
                Q(credit_note_number__icontains=search_query) |
                Q(customer__name__icontains=search_query) |
                Q(customer__customer_number__icontains=search_query) |
                Q(reason__icontains=search_query)
            )

        status_param = self.request.query_params.get('status', '').strip()
        if status_param:
            qs = qs.filter(status=status_param.upper())

        customer_id = self.request.query_params.get('customer') or self.request.query_params.get('customer_id')
        if customer_id and customer_id.isdigit():
            qs = qs.filter(customer_id=int(customer_id))

        subscription_id = self.request.query_params.get('subscription') or self.request.query_params.get('subscription_id')
        if subscription_id and subscription_id.isdigit():
            qs = qs.filter(customer__subscriptions__id=int(subscription_id)).distinct()

        invoice_id = self.request.query_params.get('invoice') or self.request.query_params.get('invoice_id')
        if invoice_id and invoice_id.isdigit():
            qs = qs.filter(invoice_id=int(invoice_id))

        return qs

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if request.user.is_superuser:
            return

        org = get_billing_tenant_organization(request.user)
        if org is not None and obj.customer.organization_id != org.id:
            raise PermissionDenied("You do not have permission to access credit notes outside your organization.")

    def create(self, request, *args, **kwargs):
        serializer = CreditNoteIssueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        customer = serializer.validated_data['customer']

        org = get_billing_tenant_organization(request.user)
        if org is not None and customer.organization_id != org.id:
            raise PermissionDenied("Cannot issue credit note for customer outside your organization.")

        perm_scope = PermissionService.get_permission_scope(request.user, self.resource_codename, 'CREATE')
        if perm_scope == 'OWN':
            created_by = (customer.metadata or {}).get('created_by_id')
            if str(created_by) != str(request.user.id):
                raise PermissionDenied("You do not have permission to issue credit notes for customers owned by others.")
        elif perm_scope == 'NONE':
            raise PermissionDenied("You do not have permission to perform billing operations.")

        credit_note = CreditNoteService.issue_credit_note(
            customer=customer,
            amount=serializer.validated_data['amount'],
            reason=serializer.validated_data.get('reason', 'CORRECTION'),
            invoice=serializer.validated_data.get('invoice'),
            subtotal=serializer.validated_data.get('subtotal'),
            tax_total=serializer.validated_data.get('tax_total'),
            issued_date=serializer.validated_data.get('issued_date'),
            user=request.user
        )

        response_serializer = CreditNoteSerializer(credit_note)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='allocate', url_name='allocate')
    def allocate(self, request, pk=None):
        credit_note = self.get_object()

        serializer = CreditNoteAllocateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = CreditNoteAllocationService.allocate_credit_note(
            credit_note_id=credit_note.id,
            allocations_data=serializer.validated_data['allocations'],
            user=request.user
        )

        response_serializer = CreditNoteSerializer(result['credit_note'])
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='unapplied-credit', url_name='unapplied_credit')
    def unapplied_credit(self, request):
        customer_id = request.query_params.get('customer') or request.query_params.get('customer_id')
        if not customer_id:
            return Response({"error": "customer or customer_id query parameter is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            customer = BillingCustomer.objects.get(pk=customer_id)
        except BillingCustomer.DoesNotExist:
            return Response({"error": f"Customer with id {customer_id} not found."}, status=status.HTTP_404_NOT_FOUND)

        org = get_billing_tenant_organization(request.user)
        if org is not None and customer.organization_id != org.id:
            raise PermissionDenied("Cannot access customer outside your organization.")

        unapplied = CreditNoteService.get_customer_unapplied_credit(customer)
        return Response({
            "customer_id": customer.id,
            "unapplied_credit": str(unapplied)
        }, status=status.HTTP_200_OK)


class DebitNotePermission(DynamicCRMPermission):
    """
    Extends DynamicCRMPermission for DebitNote operations with multi-tenant
    and metadata-based ownership scoping.
    """
    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True

        codename = self.get_resource_codename(view)
        if not codename:
            return True

        action = self.get_action(request, view)
        scope = PermissionService.get_permission_scope(request.user, codename, action)
        if scope == 'ALL':
            return True

        if scope == 'OWN':
            created_by_id = obj.invoice.customer.metadata.get('created_by_id') if (obj.invoice.customer.metadata and isinstance(obj.invoice.customer.metadata, dict)) else None
            return created_by_id == request.user.id

        return False


class DebitNoteViewSet(viewsets.ModelViewSet):
    """
    Standalone REST ViewSet for Debit Notes under /api/v1/billing/debit-notes/.
    """
    serializer_class = DebitNoteSerializer
    permission_classes = [DebitNotePermission]
    resource_codename = 'billing_payments'
    owner_field = 'created_by'
    search_fields = ['debit_note_number', 'invoice__invoice_number', 'reason']

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return DebitNote.objects.none()

        qs = DebitNote.objects.select_related('invoice__customer').all()

        # 1. Tenant Organization Isolation
        org = get_billing_tenant_organization(user)
        if org is not None:
            qs = qs.filter(invoice__customer__organization=org)
        else:
            if not (user.is_superuser or user.is_staff):
                return DebitNote.objects.none()

        # 2. RBAC Permission Scope Resolution
        scope = PermissionService.get_permission_scope(user, self.resource_codename, 'VIEW')
        if scope == 'ALL':
            pass
        elif scope == 'OWN':
            qs = qs.filter(invoice__customer__metadata__created_by_id=user.id)
        else:
            return DebitNote.objects.none()

        # Query Filters
        search_query = self.request.query_params.get('search', '').strip()
        if search_query:
            qs = qs.filter(
                Q(debit_note_number__icontains=search_query) |
                Q(invoice__invoice_number__icontains=search_query) |
                Q(invoice__customer__name__icontains=search_query) |
                Q(reason__icontains=search_query)
            )

        customer_id = self.request.query_params.get('customer') or self.request.query_params.get('customer_id')
        if customer_id and customer_id.isdigit():
            qs = qs.filter(invoice__customer_id=int(customer_id))

        subscription_id = self.request.query_params.get('subscription') or self.request.query_params.get('subscription_id')
        if subscription_id and subscription_id.isdigit():
            qs = qs.filter(invoice__subscription_id=int(subscription_id))

        invoice_id = self.request.query_params.get('invoice') or self.request.query_params.get('invoice_id')
        if invoice_id and invoice_id.isdigit():
            qs = qs.filter(invoice_id=int(invoice_id))

        return qs

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if request.user.is_superuser:
            return

        org = get_billing_tenant_organization(request.user)
        if org is not None and obj.invoice.customer.organization_id != org.id:
            raise PermissionDenied("You do not have permission to access debit notes outside your organization.")

    def create(self, request, *args, **kwargs):
        serializer = DebitNoteIssueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        invoice = serializer.validated_data['invoice']

        org = get_billing_tenant_organization(request.user)
        if org is not None and invoice.customer.organization_id != org.id:
            raise PermissionDenied("Cannot issue debit note for invoice outside your organization.")

        perm_scope = PermissionService.get_permission_scope(request.user, self.resource_codename, 'CREATE')
        if perm_scope == 'OWN':
            created_by = (invoice.customer.metadata or {}).get('created_by_id')
            if str(created_by) != str(request.user.id):
                raise PermissionDenied("You do not have permission to issue debit notes for invoices owned by others.")
        elif perm_scope == 'NONE':
            raise PermissionDenied("You do not have permission to perform billing operations.")

        debit_note = DebitNoteService.issue_debit_note(
            invoice=invoice,
            amount=serializer.validated_data['amount'],
            reason=serializer.validated_data.get('reason', ''),
            issued_date=serializer.validated_data.get('issued_date'),
            user=request.user
        )

        response_serializer = DebitNoteSerializer(debit_note)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class BillingAuditPermission(permissions.BasePermission):
    """
    Ensures user has billing VIEW permissions before accessing the audit endpoint.
    Mutating methods will be rejected with 405 Method Not Allowed by the ViewSet.
    """
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        scope = PermissionService.get_permission_scope(user, 'billing_subscriptions', 'VIEW')
        return scope in ('ALL', 'OWN')


class BillingAuditViewSet(viewsets.ViewSet):
    """
    REST ViewSet exposing tenant-scoped, read-only audit log records across
    SubscriptionAuditLog, SubscriptionChangeLog, and DunningLog.
    Normalized into UnifiedAuditActivity records with post-merge pagination and deterministic sorting.
    Strictly forbids non-GET methods (POST, PUT, PATCH, DELETE) returning 405 Method Not Allowed.
    """
    permission_classes = [BillingAuditPermission]
    http_method_names = ['get', 'head', 'options']
    resource_codename = 'billing_subscriptions'

    def list(self, request):
        user = request.user
        if not user or not user.is_authenticated:
            return Response([], status=status.HTTP_200_OK)

        org = get_billing_tenant_organization(user)
        if org is None and not (user.is_superuser or user.is_staff):
            return Response([], status=status.HTTP_200_OK)

        scope = PermissionService.get_permission_scope(user, self.resource_codename, 'VIEW')
        if scope not in ('ALL', 'OWN') and not user.is_superuser:
            return Response([], status=status.HTTP_200_OK)

        # 1. Base Querysets with Tenant Isolation
        audit_qs = SubscriptionAuditLog.objects.select_related('subscription', 'subscription__customer').all()
        change_qs = SubscriptionChangeLog.objects.select_related('subscription', 'subscription__customer').all()
        dunning_qs = DunningLog.objects.select_related('subscription', 'subscription__customer', 'invoice').all()

        if org is not None:
            audit_qs = audit_qs.filter(subscription__customer__organization=org)
            change_qs = change_qs.filter(subscription__customer__organization=org)
            dunning_qs = dunning_qs.filter(subscription__customer__organization=org)

        # 2. RBAC Scope (OWN vs ALL)
        if scope == 'OWN' and not user.is_superuser:
            audit_qs = audit_qs.filter(subscription__metadata__created_by_id=user.id)
            change_qs = change_qs.filter(subscription__metadata__created_by_id=user.id)
            dunning_qs = dunning_qs.filter(subscription__metadata__created_by_id=user.id)

        # 3. Query Parameter Filters
        sub_param = request.query_params.get('subscription', '').strip()
        if sub_param and sub_param.isdigit():
            sub_id = int(sub_param)
            audit_qs = audit_qs.filter(subscription_id=sub_id)
            change_qs = change_qs.filter(subscription_id=sub_id)
            dunning_qs = dunning_qs.filter(subscription_id=sub_id)

        action_param = request.query_params.get('action', '').strip().upper()
        if action_param:
            audit_qs = audit_qs.filter(action=action_param)
            change_qs = change_qs.filter(change_type=action_param)
            dunning_qs = dunning_qs.filter(status=action_param)

        actor_type_param = request.query_params.get('actor_type', '').strip().upper()
        if actor_type_param:
            audit_qs = audit_qs.filter(actor_type=actor_type_param)
            if actor_type_param != 'USER':
                change_qs = change_qs.none()
            if actor_type_param != 'SYSTEM':
                dunning_qs = dunning_qs.none()

        start_date = request.query_params.get('start_date', '').strip()
        if start_date:
            try:
                start_dt = date.fromisoformat(start_date)
                audit_qs = audit_qs.filter(timestamp__date__gte=start_dt)
                change_qs = change_qs.filter(timestamp__date__gte=start_dt)
                dunning_qs = dunning_qs.filter(timestamp__date__gte=start_dt)
            except Exception:
                pass

        end_date = request.query_params.get('end_date', '').strip()
        if end_date:
            try:
                end_dt = date.fromisoformat(end_date)
                audit_qs = audit_qs.filter(timestamp__date__lte=end_dt)
                change_qs = change_qs.filter(timestamp__date__lte=end_dt)
                dunning_qs = dunning_qs.filter(timestamp__date__lte=end_dt)
            except Exception:
                pass

        search_query = request.query_params.get('search', '').strip()
        if search_query:
            audit_qs = audit_qs.filter(
                Q(action__icontains=search_query) |
                Q(reason__icontains=search_query) |
                Q(subscription__subscription_number__icontains=search_query) |
                Q(subscription__customer__name__icontains=search_query)
            )
            change_qs = change_qs.filter(
                Q(change_type__icontains=search_query) |
                Q(subscription__subscription_number__icontains=search_query) |
                Q(subscription__customer__name__icontains=search_query)
            )
            dunning_qs = dunning_qs.filter(
                Q(error_code__icontains=search_query) |
                Q(error_message__icontains=search_query) |
                Q(subscription__subscription_number__icontains=search_query) |
                Q(subscription__customer__name__icontains=search_query)
            )

        # 4. Multi-Model Normalization
        feed = []
        for log in audit_qs:
            feed.append({
                'id': f"audit_{log.id}",
                'subscription': log.subscription_id,
                'subscription_number': log.subscription.subscription_number if log.subscription else '',
                'category': 'LIFECYCLE' if log.action in ['STATE_TRANSITION', 'SUBSCRIPTION_CREATED', 'CANCEL_SCHEDULED', 'CANCEL_IMMEDIATE', 'PAUSE_EXECUTED', 'RESUME_EXECUTED', 'RENEWAL_COMPLETED'] else 'FINANCIAL',
                'action': log.action,
                'title': log.action.replace('_', ' ').title(),
                'actor_type': log.actor_type,
                'actor_id': log.actor_id,
                'actor_name': log.metadata.get('actor_username') if isinstance(log.metadata, dict) else None,
                'timestamp': log.timestamp,
                'reason': log.reason,
                'state_delta': {'old': log.old_state, 'new': log.new_state} if (log.old_state or log.new_state) else {},
                'details': log.metadata if isinstance(log.metadata, dict) else {},
                'proration_amount': '0.00',
            })

        for chg in change_qs:
            actor_id = chg.details.get('actor_id') if isinstance(chg.details, dict) else None
            actor_username = chg.details.get('actor_username') if isinstance(chg.details, dict) else None
            feed.append({
                'id': f"change_{chg.id}",
                'subscription': chg.subscription_id,
                'subscription_number': chg.subscription.subscription_number if chg.subscription else '',
                'category': 'AMENDMENT',
                'action': chg.change_type,
                'title': chg.change_type.replace('_', ' ').title(),
                'actor_type': 'USER',
                'actor_id': str(actor_id) if actor_id else None,
                'actor_name': actor_username,
                'timestamp': chg.timestamp,
                'reason': chg.details.get('reason', '') if isinstance(chg.details, dict) else '',
                'state_delta': {},
                'details': chg.details if isinstance(chg.details, dict) else {},
                'proration_amount': str(chg.proration_amount),
            })

        for dunn in dunning_qs:
            feed.append({
                'id': f"dunning_{dunn.id}",
                'subscription': dunn.subscription_id,
                'subscription_number': dunn.subscription.subscription_number if dunn.subscription else '',
                'category': 'DUNNING',
                'action': f"DUNNING_ATTEMPT_{dunn.attempt_number}",
                'title': f"Dunning Attempt #{dunn.attempt_number} ({dunn.status})",
                'actor_type': 'SYSTEM',
                'actor_id': 'SYSTEM',
                'actor_name': 'Dunning Engine',
                'timestamp': dunn.timestamp,
                'reason': dunn.error_message or '',
                'state_delta': {},
                'details': {
                    'status': dunn.status,
                    'attempt_number': dunn.attempt_number,
                    'error_code': dunn.error_code,
                    'invoice_id': dunn.invoice_id,
                },
                'proration_amount': '0.00',
            })

        # 5. Deterministic Sort: (-timestamp, -id)
        feed.sort(key=lambda x: (x['timestamp'], x['id']), reverse=True)

        category_param = request.query_params.get('category', '').strip().upper()
        if category_param and category_param != 'ALL':
            feed = [item for item in feed if item['category'] == category_param]

        # 6. Post-Merge DRF Pagination
        page_param = request.query_params.get('page')
        if page_param:
            from rest_framework.pagination import PageNumberPagination
            paginator = PageNumberPagination()
            page_size = request.query_params.get('page_size', 20)
            try:
                paginator.page_size = int(page_size)
            except Exception:
                paginator.page_size = 20
            page = paginator.paginate_queryset(feed, request, view=self)
            if page is not None:
                serializer = UnifiedAuditActivitySerializer(page, many=True)
                return paginator.get_paginated_response(serializer.data)

        serializer = UnifiedAuditActivitySerializer(feed, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def retrieve(self, request, pk=None):
        """
        Retrieves a single unified audit activity record by compound key (audit_X, change_Y, dunning_Z) or numeric ID.
        """
        user = request.user
        if not user or not user.is_authenticated:
            return Response({"detail": "Not authenticated"}, status=status.HTTP_401_UNAUTHORIZED)

        org = get_billing_tenant_organization(user)
        scope = PermissionService.get_permission_scope(user, self.resource_codename, 'VIEW')
        if scope not in ('ALL', 'OWN') and not user.is_superuser:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        pk_str = str(pk).strip()
        if pk_str.startswith('audit_') or pk_str.isdigit():
            raw_id = int(pk_str.replace('audit_', ''))
            log = SubscriptionAuditLog.objects.select_related('subscription', 'subscription__customer').filter(id=raw_id).first()
            if not log:
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
            if org and log.subscription.customer.organization != org:
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
            if scope == 'OWN' and not user.is_superuser and log.subscription.metadata.get('created_by_id') != user.id:
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
            data = {
                'id': f"audit_{log.id}",
                'subscription': log.subscription_id,
                'subscription_number': log.subscription.subscription_number if log.subscription else '',
                'category': 'LIFECYCLE' if log.action in ['STATE_TRANSITION', 'SUBSCRIPTION_CREATED', 'CANCEL_SCHEDULED', 'CANCEL_IMMEDIATE', 'PAUSE_EXECUTED', 'RESUME_EXECUTED', 'RENEWAL_COMPLETED'] else 'FINANCIAL',
                'action': log.action,
                'title': log.action.replace('_', ' ').title(),
                'actor_type': log.actor_type,
                'actor_id': log.actor_id,
                'actor_name': log.metadata.get('actor_username') if isinstance(log.metadata, dict) else None,
                'timestamp': log.timestamp,
                'reason': log.reason,
                'state_delta': {'old': log.old_state, 'new': log.new_state} if (log.old_state or log.new_state) else {},
                'details': log.metadata if isinstance(log.metadata, dict) else {},
                'proration_amount': '0.00',
            }
            return Response(data, status=status.HTTP_200_OK)
        elif pk_str.startswith('change_'):
            raw_id = int(pk_str.replace('change_', ''))
            chg = SubscriptionChangeLog.objects.select_related('subscription', 'subscription__customer').filter(id=raw_id).first()
            if not chg:
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
            if org and chg.subscription.customer.organization != org:
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
            if scope == 'OWN' and not user.is_superuser and chg.subscription.metadata.get('created_by_id') != user.id:
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
            actor_id = chg.details.get('actor_id') if isinstance(chg.details, dict) else None
            actor_username = chg.details.get('actor_username') if isinstance(chg.details, dict) else None
            data = {
                'id': f"change_{chg.id}",
                'subscription': chg.subscription_id,
                'subscription_number': chg.subscription.subscription_number if chg.subscription else '',
                'category': 'AMENDMENT',
                'action': chg.change_type,
                'title': chg.change_type.replace('_', ' ').title(),
                'actor_type': 'USER',
                'actor_id': str(actor_id) if actor_id else None,
                'actor_name': actor_username,
                'timestamp': chg.timestamp,
                'reason': chg.details.get('reason', '') if isinstance(chg.details, dict) else '',
                'state_delta': {},
                'details': chg.details if isinstance(chg.details, dict) else {},
                'proration_amount': str(chg.proration_amount),
            }
            return Response(data, status=status.HTTP_200_OK)
        elif pk_str.startswith('dunning_'):
            raw_id = int(pk_str.replace('dunning_', ''))
            dunn = DunningLog.objects.select_related('subscription', 'subscription__customer').filter(id=raw_id).first()
            if not dunn:
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
            if org and dunn.subscription.customer.organization != org:
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
            if scope == 'OWN' and not user.is_superuser and dunn.subscription.metadata.get('created_by_id') != user.id:
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
            data = {
                'id': f"dunning_{dunn.id}",
                'subscription': dunn.subscription_id,
                'subscription_number': dunn.subscription.subscription_number if dunn.subscription else '',
                'category': 'DUNNING',
                'action': f"DUNNING_ATTEMPT_{dunn.attempt_number}",
                'title': f"Dunning Attempt #{dunn.attempt_number} ({dunn.status})",
                'actor_type': 'SYSTEM',
                'actor_id': 'SYSTEM',
                'actor_name': 'Dunning Engine',
                'timestamp': dunn.timestamp,
                'reason': dunn.error_message or '',
                'state_delta': {},
                'details': {
                    'status': dunn.status,
                    'attempt_number': dunn.attempt_number,
                    'error_code': dunn.error_code,
                    'invoice_id': dunn.invoice_id,
                },
                'proration_amount': '0.00',
            }
            return Response(data, status=status.HTTP_200_OK)
        else:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)


class EntitlementCheckViewSet(viewsets.ViewSet):
    """
    Read-only endpoint for checking feature entitlements and commercial limits.
    GET /api/v1/billing/entitlements/check/
    """
    permission_classes = [permissions.IsAuthenticated, DynamicCRMPermission]
    http_method_names = ['get', 'head', 'options']

    def list(self, request):
        scope = PermissionService.get_permission_scope(request.user, 'billing_subscriptions', 'VIEW')
        if scope == 'NONE':
            raise PermissionDenied("You do not have permission to view billing entitlements.")

        org = get_billing_tenant_organization(request.user)
        if not org:
            return Response({"detail": "Tenant organization could not be resolved."}, status=status.HTTP_400_BAD_REQUEST)

        feature = (request.query_params.get('feature') or '').strip()
        limit = (request.query_params.get('limit') or '').strip()

        if feature and not limit:
            allowed = EntitlementService.has_feature(org.id, feature)
            return Response({
                "feature": feature,
                "allowed": allowed,
                "reason": "Feature included in active subscription." if allowed else "Feature not included in active plan or no active subscription."
            }, status=status.HTTP_200_OK)

        if limit and not feature:
            res = EntitlementService.get_limit(org.id, limit)
            return Response(res, status=status.HTTP_200_OK)

        if feature and limit:
            feat_allowed = EntitlementService.has_feature(org.id, feature)
            lim_res = EntitlementService.get_limit(org.id, limit)
            return Response({
                "feature": feature,
                "feature_allowed": feat_allowed,
                **lim_res
            }, status=status.HTTP_200_OK)

        # Neither feature nor limit provided -> return full summary
        summary = EntitlementService.get_entitlement_summary(org.id)
        return Response(summary, status=status.HTTP_200_OK)


class CrmIntegrationViewSet(viewsets.ViewSet):
    """
    Integration endpoints for CRM ↔ Standalone Billing bridge.
    POST /api/v1/billing/integrations/crm/opportunity-won/
    """
    permission_classes = [permissions.IsAuthenticated, DynamicCRMPermission]
    http_method_names = ['post', 'options']

    @action(detail=False, methods=['post'], url_path='opportunity-won')
    def opportunity_won(self, request):
        scope = PermissionService.get_permission_scope(request.user, 'billing_subscriptions', 'CREATE')
        if scope == 'NONE':
            raise PermissionDenied("You do not have permission to provision billing subscriptions.")

        org = get_billing_tenant_organization(request.user)
        if not org:
            return Response({"detail": "Tenant organization could not be resolved."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = WonOpportunityProvisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = CrmOpportunityProvisioningService.provision_won_opportunity(
            organization=org,
            payload=serializer.validated_data,
            actor=request.user
        )

        sub = result['subscription']
        cust = result['customer']
        status_code = status.HTTP_200_OK if result.get('idempotent') else status.HTTP_201_CREATED

        return Response({
            "success": True,
            "idempotent": result.get('idempotent', False),
            "message": result.get('message', ''),
            "opportunity_id": serializer.validated_data.get('opportunity_id'),
            "subscription_id": sub.id,
            "subscription_number": sub.subscription_number,
            "status": sub.status,
            "customer_id": cust.id,
            "customer_number": cust.customer_number,
            "customer_name": cust.name,
            "mrr": str(sub.cached_mrr),
            "arr": str(sub.cached_arr),
        }, status=status_code)


class BillingAnalyticsViewSet(viewsets.ViewSet):
    """
    Authoritative SaaS Analytics & Revenue Dashboard ViewSet.
    Exposes:
    - GET /api/v1/billing/analytics/overview/
    - GET /api/v1/billing/analytics/mrr-movement/
    Strictly read-only: POST, PUT, PATCH, DELETE are rejected with 405 Method Not Allowed.
    Tenant isolated and RBAC enforced (VIEW permission on 'billing_analytics').
    """
    permission_classes = [permissions.IsAuthenticated, DynamicCRMPermission]
    http_method_names = ['get', 'head', 'options']

    @action(detail=False, methods=['get'], url_path='overview')
    def overview(self, request):
        scope = PermissionService.get_permission_scope(request.user, 'billing_analytics', 'VIEW')
        if scope == 'NONE':
            raise PermissionDenied("You do not have permission to view billing analytics.")

        org = get_billing_tenant_organization(request.user)
        if not org:
            return Response({"detail": "Tenant organization could not be resolved."}, status=status.HTTP_400_BAD_REQUEST)

        overview_data = BillingAnalyticsService.get_analytics_overview(
            organization=org,
            user=request.user,
            scope=scope
        )
        serializer = AnalyticsOverviewSerializer(overview_data)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='mrr-movement')
    def mrr_movement(self, request):
        scope = PermissionService.get_permission_scope(request.user, 'billing_analytics', 'VIEW')
        if scope == 'NONE':
            raise PermissionDenied("You do not have permission to view billing analytics.")

        org = get_billing_tenant_organization(request.user)
        if not org:
            return Response({"detail": "Tenant organization could not be resolved."}, status=status.HTTP_400_BAD_REQUEST)

        months = request.query_params.get('months', 6)
        try:
            months = int(months)
            if months < 1 or months > 36:
                months = 6
        except (ValueError, TypeError):
            months = 6

        movement_data = BillingAnalyticsService.get_mrr_movement(
            organization=org,
            months=months,
            user=request.user,
            scope=scope
        )
        serializer = MrrMovementResponseSerializer({'results': movement_data})
        return Response(serializer.data, status=status.HTTP_200_OK)
