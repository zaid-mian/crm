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
    Scopes querysets by user roles. 
    Admins see everything. Salespeople see only records assigned to them.
    """
    if hasattr(user, 'profile') and user.profile.user_type == 'ADMIN':
        return queryset
    return queryset.filter(**{salesperson_field: user})


class DashboardService:
    @staticmethod
    def get_summary_metrics(user) -> dict:
        leads_scoped = _get_scoped_queryset(Lead.objects.all(), user)
        opps_scoped = _get_scoped_queryset(Opportunity.objects.all(), user)
        payments_scoped = _get_scoped_queryset(Payment.objects.all(), user)
        companies_scoped = _get_scoped_queryset(Company.objects.all(), user)
        contacts_scoped = _get_scoped_queryset(Contact.objects.filter(is_deleted=False), user)

        total_leads = leads_scoped.count()
        new_leads = leads_scoped.filter(status='NEW').count()
        qualified_leads = leads_scoped.filter(status='QUALIFIED').count()
        converted_leads = leads_scoped.filter(is_converted=True).count()

        active_opps_qs = opps_scoped.exclude(stage__in=['CLOSED_WON', 'CLOSED_LOST'])
        active_opportunities = active_opps_qs.count()
        won_deals = opps_scoped.filter(Q(pipeline_stage__stage_type='WON') | Q(stage='CLOSED_WON')).count()
        lost_deals = opps_scoped.filter(Q(pipeline_stage__stage_type='LOST') | Q(stage='CLOSED_LOST')).count()

        total_pipeline_value = active_opps_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        won_deals_qs = opps_scoped.filter(Q(pipeline_stage__stage_type='WON') | Q(stage='CLOSED_WON'))
        won_revenue = won_deals_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        pending_payments = payments_scoped.exclude(status='PAID').annotate(
            balance=F('total_amount') - F('paid_amount')
        ).aggregate(total_balance=Sum('balance'))['total_balance'] or Decimal('0.00')

        paid_payments = payments_scoped.aggregate(total_paid=Sum('paid_amount'))['total_paid'] or Decimal('0.00')

        total_companies = companies_scoped.count()
        total_contacts = contacts_scoped.count()

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
    def get_pipeline_funnel(user) -> list:
        stages = PipelineStage.objects.filter(is_deleted=False).order_by('order')
        data = []
        for stage in stages:
            leads_qs = _get_scoped_queryset(stage.leads.all(), user)
            opps_qs = _get_scoped_queryset(stage.opportunities.all(), user)
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
    def get_recent_activities(user) -> list:
        leads_qs = _get_scoped_queryset(Lead.objects.all(), user).order_by('-created_at')[:7]
        converted_qs = _get_scoped_queryset(Lead.objects.filter(is_converted=True), user).order_by('-converted_at')[:7]
        opps_qs = _get_scoped_queryset(Opportunity.objects.filter(Q(pipeline_stage__stage_type='WON') | Q(stage='CLOSED_WON')), user).order_by('-updated_at')[:7]
        companies_qs = _get_scoped_queryset(Company.objects.all(), user).order_by('-created_at')[:7]

        txns_qs = PaymentTransaction.objects.select_related('payment', 'payment__assigned_salesperson').order_by('-payment_date', '-created_at')
        if not (hasattr(user, 'profile') and user.profile.user_type == 'ADMIN'):
            txns_qs = txns_qs.filter(payment__assigned_salesperson=user)
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
    def get_upcoming_followups(user) -> list:
        opps = _get_scoped_queryset(
            Opportunity.objects.exclude(stage__in=['CLOSED_WON', 'CLOSED_LOST']), 
            user
        ).order_by('expected_close_date')[:7]

        followups = []
        for opp in opps:
            priority = getattr(opp, 'priority', 'MEDIUM')
            followups.append({
                "id": opp.id,
                "entity_type": "OPPORTUNITY",
                "entity_id": opp.id,
                "title": f"Target Close: {opp.name}",
                "date": opp.expected_close_date.isoformat() if hasattr(opp.expected_close_date, 'isoformat') else str(opp.expected_close_date),
                "status": "PENDING",
                "assigned_salesperson": opp.assigned_salesperson.username if opp.assigned_salesperson else "Unassigned",
                "priority": priority
            })
        return followups

    @staticmethod
    def get_chart_data(user) -> dict:
        leads_scoped = _get_scoped_queryset(Lead.objects.all(), user)
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
