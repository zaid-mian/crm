from leads.models import Lead
from opportunities.models import Opportunity
from leads.services import LeadQueryService
from opportunities.services import OpportunityQueryService

class PipelineQueryService:
    @staticmethod
    def get_pipeline_cards(user):
        """
        Retrieves and normalizes unconverted Leads and all Opportunities
        visible to the requesting user based on role-based scoping (RBAC).
        """
        # 1. Fetch active unconverted leads
        leads_qs = Lead.objects.filter(is_converted=False)
        leads_qs = LeadQueryService.get_visible_leads(user, base_queryset=leads_qs)
        
        # 2. Fetch visible opportunities
        opps_qs = OpportunityQueryService.get_visible_opportunities(user).select_related('company')
        
        cards = []
        
        # Normalize Leads into card DTO dicts
        for lead in leads_qs:
            cards.append({
                "entity_type": "lead",
                "id": lead.id,
                "name": lead.full_name,
                "company_name": lead.company_name,
                "phone": lead.phone or '',
                "email": lead.email or '',
                "assigned_salesperson_id": lead.assigned_salesperson_id,
                "assigned_salesperson_name": lead.assigned_salesperson.username if lead.assigned_salesperson else None,
                "stage": lead.status,  # NEW, CONTACTED, FOLLOW_UP, LOST
                "amount": None,
                "expected_close_date": None,
                "probability": None,
                "notes": lead.notes or '',
                "company_id": None,
                "primary_contact_id": None
            })
            
        # Map OpportunityStage to Pipeline stages
        stage_mapping = {
            'QUALIFICATION': 'QUALIFIED',
            'DISCOVERY': 'FOLLOW_UP',      # Fallback / map to FOLLOW_UP
            'PROPOSAL': 'PROPOSAL',
            'NEGOTIATION': 'NEGOTIATION',
            'CLOSED_WON': 'WON',
            'CLOSED_LOST': 'LOST'
        }
            
        # Normalize Opportunities into card DTO dicts
        for opp in opps_qs:
            contact = opp.primary_contact
            cards.append({
                "entity_type": "opportunity",
                "id": opp.id,
                "name": contact.full_name if contact else '',
                "company_name": opp.company.name if opp.company else '',
                "phone": (contact.phone_number if contact else '') or '',
                "email": (contact.email if contact else '') or '',
                "assigned_salesperson_id": opp.assigned_salesperson_id,
                "assigned_salesperson_name": opp.assigned_salesperson.username if opp.assigned_salesperson else None,
                "stage": stage_mapping.get(opp.stage, 'QUALIFIED'),
                "amount": opp.amount,
                "expected_close_date": opp.expected_close_date,
                "probability": opp.probability,
                "notes": opp.description or '',
                "company_id": opp.company_id,
                "primary_contact_id": opp.primary_contact_id
            })
            
        return cards
