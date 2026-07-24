from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from leads.utils.responses import api_success, api_error
from pipeline.services.query import PipelineQueryService
from pipeline.serializers import PipelineCardSerializer

class PipelineViewSet(viewsets.ViewSet):
    """
    Unified Pipeline API ViewSet coordinating board list retrieving
    and drag-and-drop card transitions.
    """
    permission_classes = [IsAuthenticated]

    def list(self, request):
        """
        GET /api/pipeline/
        Returns unconverted Leads and all Opportunities unified under a single list.
        """
        cards = PipelineQueryService.get_pipeline_cards(request.user)
        serializer = PipelineCardSerializer(cards, many=True)
        return api_success(
            data=serializer.data,
            message="Pipeline cards listed successfully."
        )

    @action(detail=False, methods=['post'])
    def move(self, request):
        """
        POST /api/pipeline/move/
        Validates rules and transitions a Pipeline Card between stages.
        """
        entity_type = request.data.get('entity_type')
        id_val = request.data.get('id')
        target_stage = request.data.get('target_stage')

        if not entity_type or id_val is None or not target_stage:
            return api_error(
                message="Missing required fields: entity_type, id, and target_stage.",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        # Enforce valid target stages
        valid_stages = ['NEW', 'CONTACTED', 'FOLLOW_UP', 'QUALIFIED', 'PROPOSAL', 'NEGOTIATION', 'WON', 'LOST']
        if target_stage not in valid_stages:
            return api_error(
                message=f"Invalid target stage. Must be one of: {', '.join(valid_stages)}",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        from leads.models import Lead
        from opportunities.models import Opportunity
        from django.db import transaction

        if entity_type == 'lead':
            try:
                lead = Lead.objects.get(pk=id_val)
            except Lead.DoesNotExist:
                return api_error(
                    message="Lead does not exist.",
                    status_code=status.HTTP_404_NOT_FOUND
                )

            # Row-level check: salesperson must be the owner, manager/admin is bypassed
            from leads.permissions import is_manager_or_admin
            if not is_manager_or_admin(request.user) and lead.assigned_salesperson != request.user:
                return api_error(
                    message="You do not have permission to modify this lead.",
                    status_code=status.HTTP_403_FORBIDDEN
                )

            # Rule: Terminal stage lock
            if lead.is_converted:
                return api_error(
                    message="Converted leads are read-only and cannot be modified.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            if lead.status == 'LOST':
                return api_error(
                    message="Lost leads are locked and cannot be modified.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Rule: Unidirectional promotion check
            if target_stage in ['PROPOSAL', 'NEGOTIATION', 'WON']:
                return api_error(
                    message="Unconverted leads cannot be moved to Opportunity-only stages.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Rule: Move validation (salesperson must be assigned before moving past NEW)
            if target_stage != 'NEW' and not lead.assigned_salesperson:
                return api_error(
                    message="Assign the lead to a salesperson before moving it from NEW.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Execution
            if target_stage == 'QUALIFIED':
                from leads.services import LeadWorkflowService
                try:
                    with transaction.atomic():
                        # Briefly set status to QUALIFIED
                        lead.status = 'QUALIFIED'
                        lead.save()
                        
                        # Convert lead
                        converted_lead = LeadWorkflowService.convert_lead(lead)
                        opportunity = converted_lead.converted_opportunity
                        
                    # Return newly created Opportunity card DTO
                    opportunity = Opportunity.objects.select_related('assigned_salesperson', 'primary_contact', 'company').get(pk=opportunity.pk)
                    contact = opportunity.primary_contact
                    card_data = {
                        "entity_type": "opportunity",
                        "id": opportunity.id,
                        "name": contact.full_name if contact else '',
                        "company_name": opportunity.company.name if opportunity.company else '',
                        "phone": (contact.phone_number if contact else '') or '',
                        "email": (contact.email if contact else '') or '',
                        "assigned_salesperson_id": opportunity.assigned_salesperson_id,
                        "assigned_salesperson_name": opportunity.assigned_salesperson.username if opportunity.assigned_salesperson else None,
                        "stage": "QUALIFIED",
                        "amount": opportunity.amount,
                        "expected_close_date": opportunity.expected_close_date,
                        "probability": opportunity.probability,
                        "notes": opportunity.description or '',
                        "company_id": opportunity.company_id,
                        "primary_contact_id": opportunity.primary_contact_id
                    }
                    return api_success(
                        data=card_data,
                        message="Lead successfully converted to Opportunity."
                    )
                except Exception as e:
                    return api_error(
                        message=str(e),
                        status_code=status.HTTP_400_BAD_REQUEST
                    )
            else:
                # Update Lead status (NEW, CONTACTED, FOLLOW_UP, LOST)
                lead.status = target_stage
                lead.save()
                
                card_data = {
                    "entity_type": "lead",
                    "id": lead.id,
                    "name": lead.full_name,
                    "company_name": lead.company_name,
                    "phone": lead.phone or '',
                    "email": lead.email or '',
                    "assigned_salesperson_id": lead.assigned_salesperson_id,
                    "assigned_salesperson_name": lead.assigned_salesperson.username if lead.assigned_salesperson else None,
                    "stage": lead.status,
                    "amount": None,
                    "expected_close_date": None,
                    "probability": None,
                    "notes": lead.notes or '',
                    "company_id": None,
                    "primary_contact_id": None
                }
                return api_success(
                    data=card_data,
                    message="Lead stage updated successfully."
                )

        elif entity_type == 'opportunity':
            try:
                opp = Opportunity.objects.get(pk=id_val)
            except Opportunity.DoesNotExist:
                return api_error(
                    message="Opportunity does not exist.",
                    status_code=status.HTTP_404_NOT_FOUND
                )

            # Row-level check
            from leads.permissions import is_manager_or_admin
            if not is_manager_or_admin(request.user) and opp.assigned_salesperson != request.user:
                return api_error(
                    message="You do not have permission to modify this opportunity.",
                    status_code=status.HTTP_403_FORBIDDEN
                )

            # Rule: Terminal stage lock for salespeople
            if opp.stage in ['CLOSED_WON', 'CLOSED_LOST']:
                if not is_manager_or_admin(request.user):
                    return api_error(
                        message="Closed opportunities are locked and cannot be modified by salespeople.",
                        status_code=status.HTTP_400_BAD_REQUEST
                    )

            # Rule: Unidirectional promotion check
            if target_stage in ['NEW', 'CONTACTED', 'FOLLOW_UP']:
                return api_error(
                    message="Opportunities cannot be moved to Lead-only stages.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Map target stage back to Opportunity stage
            opp_stage_mapping = {
                'QUALIFIED': 'QUALIFICATION',
                'PROPOSAL': 'PROPOSAL',
                'NEGOTIATION': 'NEGOTIATION',
                'WON': 'CLOSED_WON',
                'LOST': 'CLOSED_LOST'
            }
            opp.stage = opp_stage_mapping[target_stage]
            opp.save()

            # Return updated Opportunity card DTO
            opp = Opportunity.objects.select_related('assigned_salesperson', 'primary_contact', 'company').get(pk=opp.pk)
            contact = opp.primary_contact
            card_data = {
                "entity_type": "opportunity",
                "id": opp.id,
                "name": contact.full_name if contact else '',
                "company_name": opp.company.name if opp.company else '',
                "phone": (contact.phone_number if contact else '') or '',
                "email": (contact.email if contact else '') or '',
                "assigned_salesperson_id": opp.assigned_salesperson_id,
                "assigned_salesperson_name": opp.assigned_salesperson.username if opp.assigned_salesperson else None,
                "stage": target_stage,
                "amount": opp.amount,
                "expected_close_date": opp.expected_close_date,
                "probability": opp.probability,
                "notes": opp.description or '',
                "company_id": opp.company_id,
                "primary_contact_id": opp.primary_contact_id
            }
            return api_success(
                data=card_data,
                message="Opportunity stage updated successfully."
            )
        else:
            return api_error(
                message="Invalid entity_type. Must be 'lead' or 'opportunity'.",
                status_code=status.HTTP_400_BAD_REQUEST
            )
