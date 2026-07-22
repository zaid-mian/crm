from django.db.models import Count
from leads.models import Lead

class LeadStatsService:
    """Handles database aggregations and lead statistics reporting."""
    
    @staticmethod
    def get_status_grouped_stats(queryset) -> dict:
        counts_query = queryset.values('status').annotate(total=Count('id'))
        
        status_counts = {status: 0 for status, _ in Lead.LeadStatus.choices}
        for item in counts_query:
            status_counts[item['status']] = item['total']
            
        total_leads = queryset.count()
        return {
            "status_counts": status_counts,
            "total_leads": total_leads
        }
