from leads.models import Lead
from opportunities.models import Opportunity
from leads.services import LeadQueryService
from opportunities.services import OpportunityQueryService

def map_stage_to_enum(pipeline_stage, default_val):
    if not pipeline_stage:
        return default_val
    st = pipeline_stage.stage_type
    order = pipeline_stage.order
    if st == 'NORMAL_LEAD':
        if order == 0: return 'NEW'
        if order == 1: return 'CONTACTED'
        return 'FOLLOW_UP'
    if st == 'CONVERSION':
        return 'QUALIFIED'
    if st == 'NORMAL_OPPORTUNITY':
        if order == 4: return 'PROPOSAL'
        return 'NEGOTIATION'
    if st == 'WON':
        return 'WON'
    if st == 'LOST':
        return 'LOST'
    return default_val

class PipelineQueryService:
    @staticmethod
    def get_pipeline_cards(user, pipeline_id=None):
        """
        Retrieves and normalizes unconverted Leads and all Opportunities
        visible to the requesting user based on role-based scoping (RBAC).
        """
        # 1. Fetch active unconverted leads
        leads_qs = Lead.objects.filter(is_converted=False).select_related('pipeline_stage', 'assigned_salesperson')
        if pipeline_id:
            leads_qs = leads_qs.filter(pipeline_id=pipeline_id)
        leads_qs = LeadQueryService.get_visible_leads(user, base_queryset=leads_qs)
        
        # 2. Fetch visible opportunities
        opps_qs = OpportunityQueryService.get_visible_opportunities(user).select_related('company', 'pipeline_stage', 'primary_contact', 'assigned_salesperson')
        if pipeline_id:
            opps_qs = opps_qs.filter(pipeline_id=pipeline_id)
        
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
                "stage": map_stage_to_enum(lead.pipeline_stage, lead.status),
                "amount": None,
                "expected_close_date": None,
                "probability": None,
                "notes": lead.notes or '',
                "company_id": None,
                "primary_contact_id": None,
                "pipeline_stage_id": lead.pipeline_stage_id
            })
            
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
                "stage": map_stage_to_enum(opp.pipeline_stage, opp.stage),
                "amount": opp.amount,
                "expected_close_date": opp.expected_close_date,
                "probability": opp.probability,
                "notes": opp.description or '',
                "company_id": opp.company_id,
                "primary_contact_id": opp.primary_contact_id,
                "pipeline_stage_id": opp.pipeline_stage_id
            })
            
        return cards
