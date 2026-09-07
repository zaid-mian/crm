from decimal import Decimal
from datetime import datetime, timedelta
from django.db.models import Sum, Count, F, Q
from django.utils import timezone

from leads.models import Lead
from contacts.models import Contact
from companies.models import Company
from opportunities.models import Opportunity
from payments.models import Payment, PaymentTransaction
from pipeline.models import PipelineStage


def _get_scoped_queryset(queryset, user, salesperson_field='assigned_salesperson'):
    """
    Scopes querysets dynamically based on user roles and scopes.
    """
    from roles.permissions import get_scoped_queryset
    
    # Resolve the resource codename based on model name
    model_name = queryset.model._meta.model_name
    if model_name == 'payment':
        codename = 'payments'
    elif model_name == 'lead':
        codename = 'leads'
    elif model_name == 'opportunity':
        codename = 'opportunities'
    elif model_name == 'company':
        codename = 'companies'
    elif model_name == 'contact':
        codename = 'contacts'
    else:
        codename = queryset.model._meta.app_label.lower()
        
    return get_scoped_queryset(queryset, user, resource_codename=codename, owner_field=salesperson_field)


def _get_date_bounds(date_range_str):
    if not date_range_str or date_range_str == 'lifetime':
        return None, None
    today = timezone.now().date()
    if date_range_str == 'this_month':
        start_date = today.replace(day=1)
        return start_date, None
    elif date_range_str == 'this_quarter':
        quarter_month = 3 * ((today.month - 1) // 3) + 1
        start_date = today.replace(month=quarter_month, day=1)
        return start_date, None
    elif date_range_str == 'last_30_days':
        start_date = today - timedelta(days=30)
        return start_date, None
    return None, None


class DashboardService:
    @staticmethod
    def get_summary_metrics(user, filters: dict = None) -> dict:
        filters = filters or {}
        salesperson_id = filters.get('salesperson_id')
        pipeline_id = filters.get('pipeline_id')
        date_range = filters.get('date_range')

        start_date, end_date = _get_date_bounds(date_range)

        leads_qs = _get_scoped_queryset(Lead.objects.all(), user)
        opps_qs = _get_scoped_queryset(Opportunity.objects.all(), user)
        payments_qs = _get_scoped_queryset(Payment.objects.all(), user)
        companies_qs = _get_scoped_queryset(Company.objects.all(), user)
        contacts_qs = _get_scoped_queryset(Contact.objects.filter(is_deleted=False), user)

        if salesperson_id:
            leads_qs = leads_qs.filter(assigned_salesperson_id=salesperson_id)
            opps_qs = opps_qs.filter(assigned_salesperson_id=salesperson_id)
            payments_qs = payments_qs.filter(assigned_salesperson_id=salesperson_id)
            companies_qs = companies_qs.filter(assigned_salesperson_id=salesperson_id)
            contacts_qs = contacts_qs.filter(assigned_salesperson_id=salesperson_id)

        if pipeline_id:
            leads_qs = leads_qs.filter(pipeline_id=pipeline_id)
            opps_qs = opps_qs.filter(pipeline_id=pipeline_id)
            opp_ids = list(opps_qs.values_list('id', flat=True))
            payments_qs = payments_qs.filter(opportunity_id__in=opp_ids)

        if start_date:
            leads_qs = leads_qs.filter(created_at__date__gte=start_date)
            opps_qs = opps_qs.filter(created_at__date__gte=start_date)
            payments_qs = payments_qs.filter(Q(payment_date__gte=start_date) | Q(created_at__date__gte=start_date))

        total_leads = leads_qs.count()
        new_leads = leads_qs.filter(status='NEW').count()
        qualified_leads = leads_qs.filter(status='QUALIFIED').count()
        converted_leads = leads_qs.filter(is_converted=True).count()

        active_opps_qs = opps_qs.exclude(stage__in=['CLOSED_WON', 'CLOSED_LOST'])
        active_opportunities = active_opps_qs.count()
        won_deals = opps_qs.filter(Q(pipeline_stage__stage_type='WON') | Q(stage='CLOSED_WON')).count()
        lost_deals = opps_qs.filter(Q(pipeline_stage__stage_type='LOST') | Q(stage='CLOSED_LOST')).count()

        total_pipeline_value = active_opps_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        won_deals_qs = opps_qs.filter(Q(pipeline_stage__stage_type='WON') | Q(stage='CLOSED_WON'))
        won_revenue = won_deals_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        pending_payments = payments_qs.exclude(status='PAID').annotate(
            balance=F('total_amount') - F('paid_amount')
        ).aggregate(total_balance=Sum('balance'))['total_balance'] or Decimal('0.00')

        paid_payments = payments_qs.aggregate(total_paid=Sum('paid_amount'))['total_paid'] or Decimal('0.00')

        total_companies = companies_qs.count()
        total_contacts = contacts_qs.count()

        conversion_rate = (converted_leads / total_leads * 100.0) if total_leads > 0 else 0.0
        average_deal_size = (total_pipeline_value / active_opportunities) if active_opportunities > 0 else Decimal('0.00')

        return {
            "total_leads": total_leads,
            "new_leads": new_leads,
            "qualified_leads": qualified_leads,
            "converted_leads": converted_leads,
            "active_opportunities": active_opportunities,
            "won_deals": won_deals,
            "lost_deals": lost_deals,
            "total_pipeline_value": total_pipeline_value,
            "won_revenue": won_revenue,
            "pending_payments": pending_payments,
            "paid_payments": paid_payments,
            "total_companies": total_companies,
            "total_contacts": total_contacts,
            "conversion_rate": round(conversion_rate, 2),
            "average_deal_size": average_deal_size
        }

    @staticmethod
    def get_pipeline_funnel(user, filters: dict = None) -> list:
        filters = filters or {}
        salesperson_id = filters.get('salesperson_id')
        pipeline_id = filters.get('pipeline_id')
        date_range = filters.get('date_range')
        start_date, _ = _get_date_bounds(date_range)

        stages_qs = PipelineStage.objects.filter(is_deleted=False)
        if pipeline_id:
            stages_qs = stages_qs.filter(pipeline_id=pipeline_id)
        stages = stages_qs.order_by('order')

        data = []
        for stage in stages:
            leads_qs = _get_scoped_queryset(stage.leads.all(), user)
            opps_qs = _get_scoped_queryset(stage.opportunities.all(), user)

            if salesperson_id:
                leads_qs = leads_qs.filter(assigned_salesperson_id=salesperson_id)
                opps_qs = opps_qs.filter(assigned_salesperson_id=salesperson_id)

            if start_date:
                leads_qs = leads_qs.filter(created_at__date__gte=start_date)
                opps_qs = opps_qs.filter(created_at__date__gte=start_date)

            total_val = opps_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

            data.append({
                "stage_id": stage.id,
                "stage_name": stage.name,
                "entity_type": stage.entity_type,
                "stage_type": stage.stage_type,
                "color": stage.color,
                "order": stage.order,
                "lead_count": leads_qs.count(),
                "opportunity_count": opps_qs.count(),
                "total_value": total_val
            })
        return data

    @staticmethod
    def get_recent_activities(user, filters: dict = None) -> list:
        filters = filters or {}
        salesperson_id = filters.get('salesperson_id')

        leads_qs = _get_scoped_queryset(Lead.objects.all(), user)
        converted_qs = _get_scoped_queryset(Lead.objects.filter(is_converted=True), user)
        opps_qs = _get_scoped_queryset(Opportunity.objects.filter(Q(pipeline_stage__stage_type='WON') | Q(stage='CLOSED_WON')), user)
        companies_qs = _get_scoped_queryset(Company.objects.all(), user)

        if salesperson_id:
            leads_qs = leads_qs.filter(assigned_salesperson_id=salesperson_id)
            converted_qs = converted_qs.filter(assigned_salesperson_id=salesperson_id)
            opps_qs = opps_qs.filter(assigned_salesperson_id=salesperson_id)
            companies_qs = companies_qs.filter(assigned_salesperson_id=salesperson_id)

        leads_qs = leads_qs.order_by('-created_at')[:7]
        converted_qs = converted_qs.order_by('-converted_at')[:7]
        opps_qs = opps_qs.order_by('-updated_at')[:7]
        companies_qs = companies_qs.order_by('-created_at')[:7]

        txns_qs = PaymentTransaction.objects.select_related('payment', 'payment__assigned_salesperson').order_by('-payment_date', '-created_at')
        from roles.services import PermissionService
        scope = PermissionService.get_permission_scope(user, 'payments', 'VIEW')
        if scope == 'ALL':
            from leads.utils.tenant import get_user_organization
            org = get_user_organization(user)
            if org:
                txns_qs = txns_qs.filter(payment__organization=org)
        elif scope == 'OWN':
            txns_qs = txns_qs.filter(payment__assigned_salesperson=user)
        else:
            txns_qs = txns_qs.none()
        txns_qs = txns_qs[:7]

        activities = []

        for lead in leads_qs:
            activities.append({
                "type": "LEAD_CREATED",
                "timestamp": lead.created_at,
                "description": f"Lead {lead.full_name} created.",
                "actor_name": lead.assigned_salesperson.username if lead.assigned_salesperson else "System",
                "reference_id": lead.id,
                "reference_name": lead.full_name
            })

        for lead in converted_qs:
            activities.append({
                "type": "LEAD_CONVERTED",
                "timestamp": lead.converted_at or lead.updated_at,
                "description": f"Lead {lead.full_name} converted to Opportunity.",
                "actor_name": lead.assigned_salesperson.username if lead.assigned_salesperson else "System",
                "reference_id": lead.id,
                "reference_name": lead.full_name
            })

        for opp in opps_qs:
            activities.append({
                "type": "OPPORTUNITY_WON",
                "timestamp": opp.updated_at,
                "description": f"Opportunity {opp.name} won.",
                "actor_name": opp.assigned_salesperson.username if opp.assigned_salesperson else "System",
                "reference_id": opp.id,
                "reference_name": opp.name
            })

        for txn in txns_qs:
            timestamp = timezone.make_aware(datetime.combine(txn.payment_date, datetime.min.time())) if txn.payment_date else txn.created_at
            activities.append({
                "type": "PAYMENT_RECEIVED",
                "timestamp": timestamp,
                "description": f"Payment of {txn.amount} received for Invoice {txn.payment.invoice_number}.",
                "actor_name": txn.recorded_by.username if txn.recorded_by else "System",
                "reference_id": txn.payment.id,
                "reference_name": txn.payment.invoice_number
            })

        for company in companies_qs:
            activities.append({
                "type": "COMPANY_CREATED",
                "timestamp": company.created_at,
                "description": f"Company {company.name} created.",
                "actor_name": company.assigned_salesperson.username if company.assigned_salesperson else "System",
                "reference_id": company.id,
                "reference_name": company.name
            })

        activities.sort(key=lambda x: x['timestamp'], reverse=True)
        activities = activities[:7]

        for idx, act in enumerate(activities, 1):
            act['id'] = idx
            act['timestamp'] = act['timestamp'].isoformat() if hasattr(act['timestamp'], 'isoformat') else str(act['timestamp'])

        return activities

    @staticmethod
    def get_upcoming_followups(user, filters: dict = None) -> list:
        filters = filters or {}
        salesperson_id = filters.get('salesperson_id')
        pipeline_id = filters.get('pipeline_id')

        opps_qs = _get_scoped_queryset(
            Opportunity.objects.exclude(stage__in=['CLOSED_WON', 'CLOSED_LOST']), 
            user
        )
        if salesperson_id:
            opps_qs = opps_qs.filter(assigned_salesperson_id=salesperson_id)
        if pipeline_id:
            opps_qs = opps_qs.filter(pipeline_id=pipeline_id)

        opps = opps_qs.order_by('expected_close_date')[:7]

        followups = []
        for opp in opps:
            amt = float(opp.amount or 0)
            if hasattr(opp, 'priority') and getattr(opp, 'priority', None):
                priority = opp.priority
            else:
                priority = 'HIGH' if amt >= 50000 else 'MEDIUM' if amt >= 15000 else 'LOW'

            followups.append({
                "id": opp.id,
                "entity_type": "OPPORTUNITY",
                "entity_id": opp.id,
                "title": f"Target Close: {opp.name}",
                "date": opp.expected_close_date.isoformat() if hasattr(opp.expected_close_date, 'isoformat') else str(opp.expected_close_date),
                "status": "PENDING",
                "assigned_salesperson": opp.assigned_salesperson.username if opp.assigned_salesperson else "Unassigned",
                "priority": priority,
                "amount": opp.amount or Decimal('0.00')
            })
        return followups

    @staticmethod
    def get_leaderboard(user, filters: dict = None) -> list:
        filters = filters or {}
        salesperson_id = filters.get('salesperson_id')
        pipeline_id = filters.get('pipeline_id')
        date_range = filters.get('date_range')

        start_date, _ = _get_date_bounds(date_range)

        # 1. Base scoped querysets (Security authority: _get_scoped_queryset enforces RBAC & tenant isolation)
        leads_qs = _get_scoped_queryset(Lead.objects.all(), user)
        opps_qs = _get_scoped_queryset(Opportunity.objects.all(), user)

        # 2. Apply optional filters
        if salesperson_id:
            leads_qs = leads_qs.filter(assigned_salesperson_id=salesperson_id)
            opps_qs = opps_qs.filter(assigned_salesperson_id=salesperson_id)

        if pipeline_id:
            leads_qs = leads_qs.filter(pipeline_id=pipeline_id)
            opps_qs = opps_qs.filter(pipeline_id=pipeline_id)

        if start_date:
            leads_qs = leads_qs.filter(created_at__date__gte=start_date)
            opps_qs = opps_qs.filter(created_at__date__gte=start_date)

        # 3. Aggregations per Salesperson
        lead_stats = leads_qs.exclude(assigned_salesperson__isnull=True).values('assigned_salesperson_id').annotate(
            total_leads=Count('id')
        )
        opp_stats = opps_qs.exclude(assigned_salesperson__isnull=True).values('assigned_salesperson_id').annotate(
            total_opps=Count('id'),
            won_deals=Count('id', filter=Q(pipeline_stage__stage_type='WON') | Q(stage='CLOSED_WON')),
            lost_deals=Count('id', filter=Q(pipeline_stage__stage_type='LOST') | Q(stage='CLOSED_LOST')),
            won_revenue=Sum('amount', filter=Q(pipeline_stage__stage_type='WON') | Q(stage='CLOSED_WON'))
        )

        lead_map = {item['assigned_salesperson_id']: item for item in lead_stats}
        opp_map = {item['assigned_salesperson_id']: item for item in opp_stats}

        all_sp_ids = set(lead_map.keys()) | set(opp_map.keys())

        if not all_sp_ids and hasattr(user, 'id'):
            all_sp_ids = {user.id}

        from django.contrib.auth import get_user_model
        User = get_user_model()
        users_by_id = {u.id: u for u in User.objects.filter(id__in=all_sp_ids).select_related('profile', 'profile__role')}

        leaderboard_data = []
        for sp_id in all_sp_ids:
            sp_user = users_by_id.get(sp_id)
            if not sp_user:
                continue

            l_info = lead_map.get(sp_id, {})
            o_info = opp_map.get(sp_id, {})

            full_name = sp_user.get_full_name() or sp_user.username
            profile = getattr(sp_user, 'profile', None)
            role_name = profile.role.name if (profile and profile.role) else ("Administrator" if (profile and profile.user_type == 'ADMIN') or sp_user.is_superuser else "Salesperson")

            total_leads_count = l_info.get('total_leads', 0)
            won_deals_count = o_info.get('won_deals', 0)
            lost_deals_count = o_info.get('lost_deals', 0)
            won_rev = o_info.get('won_revenue') or Decimal('0.00')

            closed_count = won_deals_count + lost_deals_count
            win_rate = round((won_deals_count / closed_count * 100.0), 1) if closed_count > 0 else 0.0

            leaderboard_data.append({
                "user_id": sp_id,
                "user_name": full_name,
                "user_email": sp_user.email,
                "role_name": role_name,
                "assigned_leads_count": total_leads_count,
                "won_deals_count": won_deals_count,
                "total_won_amount": won_rev,
                "win_rate": win_rate
            })

        sorted_leaderboard = sorted(
            leaderboard_data,
            key=lambda x: (x.get('won_deals_count', 0), float(x.get('total_won_amount', 0) or 0)),
            reverse=True
        )
        return sorted_leaderboard[:5]

    @staticmethod
    def get_chart_data(user, filters: dict = None) -> dict:
        filters = filters or {}
        salesperson_id = filters.get('salesperson_id')
        pipeline_id = filters.get('pipeline_id')
        date_range = filters.get('date_range')
        start_date, _ = _get_date_bounds(date_range)

        leads_scoped = _get_scoped_queryset(Lead.objects.all(), user)
        if salesperson_id:
            leads_scoped = leads_scoped.filter(assigned_salesperson_id=salesperson_id)
        if pipeline_id:
            leads_scoped = leads_scoped.filter(pipeline_id=pipeline_id)
        if start_date:
            leads_scoped = leads_scoped.filter(created_at__date__gte=start_date)

        source_counts = leads_scoped.values('source').annotate(count=Count('id'))
        lead_sources_data = {
            "WEBSITE": 0,
            "REFERRAL": 0,
            "FACEBOOK": 0,
            "WALK_IN": 0,
            "OTHER": 0
        }
        for sc in source_counts:
            src = sc['source']
            if src in lead_sources_data:
                lead_sources_data[src] = sc['count']
            else:
                lead_sources_data["OTHER"] += sc['count']

        payments_scoped = _get_scoped_queryset(Payment.objects.all(), user)
        if salesperson_id:
            payments_scoped = payments_scoped.filter(assigned_salesperson_id=salesperson_id)
        if pipeline_id:
            opp_ids = list(Opportunity.objects.filter(pipeline_id=pipeline_id).values_list('id', flat=True))
            payments_scoped = payments_scoped.filter(opportunity_id__in=opp_ids)
        if start_date:
            payments_scoped = payments_scoped.filter(Q(payment_date__gte=start_date) | Q(created_at__date__gte=start_date))
        overdue_cutoff = timezone.now() - timedelta(days=30)

        paid_payments_qs = payments_scoped.filter(status='PAID')
        paid_aggr = paid_payments_qs.aggregate(count=Count('id'), total=Sum('paid_amount'))

        overdue_payments_qs = payments_scoped.exclude(status='PAID').filter(created_at__lt=overdue_cutoff)
        overdue_aggr = overdue_payments_qs.aggregate(count=Count('id'), total=Sum(F('total_amount') - F('paid_amount')))

        pending_payments_qs = payments_scoped.exclude(status='PAID').filter(created_at__gte=overdue_cutoff)
        pending_aggr = pending_payments_qs.aggregate(count=Count('id'), total=Sum(F('total_amount') - F('paid_amount')))

        payment_summary_data = {
            "paid": {
                "count": paid_aggr['count'] or 0,
                "amount": paid_aggr['total'] or Decimal('0.00')
            },
            "pending": {
                "count": pending_aggr['count'] or 0,
                "amount": pending_aggr['total'] or Decimal('0.00')
            },
            "overdue": {
                "count": overdue_aggr['count'] or 0,
                "amount": overdue_aggr['total'] or Decimal('0.00')
            }
        }

        return {
            "lead_sources": lead_sources_data,
            "payment_summary": payment_summary_data
        }


class UserReportingService:
    @staticmethod
    def get_user_performance_report(user, filters=None) -> dict:
        """
        Generates organization-wide sales performance statistics aggregated per salesperson.
        Strictly enforces tenant isolation and RBAC permission checks.
        """
        if not user or not user.is_authenticated:
            return {"summary": {}, "users": [], "stages": []}

        # 1. Tenant Resolution
        from leads.utils.tenant import get_user_organization
        org = get_user_organization(user)

        is_global_admin = user.is_superuser or user.is_staff
        crm_profile = getattr(user, 'profile', None)
        is_crm_admin = crm_profile and crm_profile.user_type == 'ADMIN'

        # Check permissions: caller MUST be CRM Administrator or Django staff/superuser
        if not (is_global_admin or is_crm_admin):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not have permission to access User Reporting.")

        # 2. Get Users Queryset (Scoped to Organization)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        if org:
            users_qs = User.objects.filter(
                Q(profile__organization=org) | Q(ownerprofile__organization=org)
            ).distinct()
        elif is_global_admin:
            users_qs = User.objects.all()
        else:
            return {"summary": {}, "users": [], "stages": []}

        filters = filters or {}
        search = filters.get('search')
        if search:
            users_qs = users_qs.filter(
                Q(username__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search)
            )

        role_id = filters.get('role_id')
        if role_id:
            users_qs = users_qs.filter(profile__role_id=role_id)

        # 3. Scoped Leads and Opportunities
        from leads.models import Lead
        from opportunities.models import Opportunity
        from pipeline.models import PipelineStage

        if org:
            leads_qs = Lead.objects.filter(organization=org)
            opps_qs = Opportunity.objects.filter(organization=org)
            stages_qs = PipelineStage.objects.filter(is_deleted=False).order_by('order')
        else:
            leads_qs = Lead.objects.all()
            opps_qs = Opportunity.objects.all()
            stages_qs = PipelineStage.objects.filter(is_deleted=False).order_by('order')

        date_from = filters.get('date_from')
        date_to = filters.get('date_to')
        if date_from:
            leads_qs = leads_qs.filter(created_at__date__gte=date_from)
            opps_qs = opps_qs.filter(created_at__date__gte=date_from)
        if date_to:
            leads_qs = leads_qs.filter(created_at__date__lte=date_to)
            opps_qs = opps_qs.filter(created_at__date__lte=date_to)

        pipeline_id = filters.get('pipeline_id')
        if pipeline_id:
            leads_qs = leads_qs.filter(pipeline_id=pipeline_id)
            opps_qs = opps_qs.filter(pipeline_id=pipeline_id)
            stages_qs = stages_qs.filter(pipeline_id=pipeline_id)

        stages_data = [
            {
                "id": st.id,
                "name": st.name,
                "stage_type": st.stage_type,
                "entity_type": st.entity_type,
            }
            for st in stages_qs
        ]

        # 4. Aggregations per User
        lead_user_stats = leads_qs.values('assigned_salesperson_id').annotate(
            total=Count('id'),
            new_count=Count('id', filter=Q(status='NEW')),
            contacted_count=Count('id', filter=Q(status='CONTACTED')),
            followup_count=Count('id', filter=Q(status='DEMO_SCHEDULED')),
            proposal_count=Count('id', filter=Q(status='PROPOSAL_SENT')),
            converted_count=Count('id', filter=Q(is_converted=True)),
            lost_count=Count('id', filter=Q(status='LOST')),
        )
        lead_stats_map = {item['assigned_salesperson_id']: item for item in lead_user_stats}

        opp_user_stats = opps_qs.values('assigned_salesperson_id').annotate(
            total=Count('id'),
            won_count=Count('id', filter=Q(pipeline_stage__stage_type='WON') | Q(stage='CLOSED_WON')),
            lost_count=Count('id', filter=Q(pipeline_stage__stage_type='LOST') | Q(stage='CLOSED_LOST')),
            pipeline_val=Sum('amount', filter=~Q(pipeline_stage__stage_type__in=['WON', 'LOST']) & ~Q(stage__in=['CLOSED_WON', 'CLOSED_LOST'])),
            won_val=Sum('amount', filter=Q(pipeline_stage__stage_type='WON') | Q(stage='CLOSED_WON')),
        )
        opp_stats_map = {item['assigned_salesperson_id']: item for item in opp_user_stats}

        stage_lead_stats = leads_qs.values('assigned_salesperson_id', 'pipeline_stage_id').annotate(count=Count('id'))
        stage_opp_stats = opps_qs.values('assigned_salesperson_id', 'pipeline_stage_id').annotate(count=Count('id'))

        stage_counts_map = {}
        for item in stage_lead_stats:
            uid = item['assigned_salesperson_id']
            sid = item['pipeline_stage_id']
            if uid and sid:
                stage_counts_map[(uid, sid)] = item['count']

        for item in stage_opp_stats:
            uid = item['assigned_salesperson_id']
            sid = item['pipeline_stage_id']
            if uid and sid:
                stage_counts_map[(uid, sid)] = stage_counts_map.get((uid, sid), 0) + item['count']

        # 5. Build Users List
        users_list = []
        total_org_leads = 0
        total_org_opps = 0
        total_org_won_deals = 0
        total_org_lost_deals = 0
        total_org_won_revenue = Decimal('0.00')

        for u in users_qs:
            profile = getattr(u, 'profile', None)
            role_name = profile.role.name if (profile and profile.role) else ("Administrator" if profile and profile.user_type == 'ADMIN' else "Salesperson")
            full_name = u.get_full_name() or u.username

            l_stat = lead_stats_map.get(u.id, {})
            o_stat = opp_stats_map.get(u.id, {})

            tot_leads = l_stat.get('total', 0)
            tot_opps = o_stat.get('total', 0)
            won_opps = o_stat.get('won_count', 0)
            lost_opps = o_stat.get('lost_count', 0)
            pipeline_val = o_stat.get('pipeline_val') or Decimal('0.00')
            won_val = o_stat.get('won_val') or Decimal('0.00')

            total_org_leads += tot_leads
            total_org_opps += tot_opps
            total_org_won_deals += won_opps
            total_org_lost_deals += lost_opps
            total_org_won_revenue += won_val

            user_stage_counts = {}
            for st in stages_data:
                sid = st['id']
                user_stage_counts[sid] = stage_counts_map.get((u.id, sid), 0)

            closed_deals = won_opps + lost_opps
            win_rate = round((won_opps / closed_deals * 100), 1) if closed_deals > 0 else 0.0
            conv_rate = round((l_stat.get('converted_count', 0) / tot_leads * 100), 1) if tot_leads > 0 else 0.0

            users_list.append({
                "user_id": u.id,
                "full_name": full_name,
                "username": u.username,
                "email": u.email,
                "role": role_name,
                "role_id": profile.role_id if profile else None,
                "is_active": u.is_active,
                "total_leads": tot_leads,
                "new_leads": l_stat.get('new_count', 0),
                "contacted_leads": l_stat.get('contacted_count', 0),
                "followup_leads": l_stat.get('followup_count', 0),
                "proposal_leads": l_stat.get('proposal_count', 0),
                "converted_leads": l_stat.get('converted_count', 0),
                "lost_leads": l_stat.get('lost_count', 0),
                "total_opportunities": tot_opps,
                "won_opportunities": won_opps,
                "lost_opportunities": lost_opps,
                "pipeline_value": pipeline_val,
                "won_revenue": won_val,
                "conversion_rate": conv_rate,
                "win_rate": win_rate,
                "stage_counts": user_stage_counts,
            })

        summary = {
            "total_users": len(users_list),
            "total_leads": total_org_leads,
            "total_opportunities": total_org_opps,
            "total_won_deals": total_org_won_deals,
            "total_lost_deals": total_org_lost_deals,
            "total_won_revenue": total_org_won_revenue,
            "avg_win_rate": round((total_org_won_deals / (total_org_won_deals + total_org_lost_deals) * 100), 1) if (total_org_won_deals + total_org_lost_deals) > 0 else 0.0,
        }

        return {
            "summary": summary,
            "users": users_list,
            "stages": stages_data,
        }

