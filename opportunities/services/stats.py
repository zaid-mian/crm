from django.db.models import Sum, Avg, Count, Q
from decimal import Decimal
from opportunities.models import Opportunity

class OpportunityStatsService:
    @staticmethod
    def get_summary_stats(queryset) -> dict:
        """
        Aggregates opportunity KPIs from the provided (scoped) queryset.
        """
        counts = queryset.aggregate(
            total=Count('id'),
            open_count=Count('id', filter=~Q(pipeline_stage__stage_type__in=['WON', 'LOST'])),
            won_count=Count('id', filter=Q(pipeline_stage__stage_type='WON')),
            lost_count=Count('id', filter=Q(pipeline_stage__stage_type='LOST')),
            pipeline_sum=Sum('amount', filter=~Q(pipeline_stage__stage_type__in=['WON', 'LOST'])),
            avg_size=Avg('amount')
        )
        
        total_deals = counts['total'] or 0
        open_deals = counts['open_count'] or 0
        closed_won = counts['won_count'] or 0
        closed_lost = counts['lost_count'] or 0
        pipeline_value = counts['pipeline_sum'] or Decimal('0.00')
        avg_deal_size = counts['avg_size'] or Decimal('0.00')
        
        # Calculate expected revenue for open deals dynamically based on stage mapping
        open_deals_list = queryset.filter(
            ~Q(pipeline_stage__stage_type__in=['WON', 'LOST'])
        )
        expected_revenue = Decimal('0.00')
        for deal in open_deals_list:
            expected_revenue += deal.expected_revenue
            
        return {
            "total_deals": total_deals,
            "open_deals": open_deals,
            "closed_won": closed_won,
            "closed_lost": closed_lost,
            "pipeline_value": float(pipeline_value),
            "expected_revenue": float(expected_revenue),
            "avg_deal_size": float(avg_deal_size),
        }
