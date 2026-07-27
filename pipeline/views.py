from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, BasePermission
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
        pipeline_id = request.query_params.get('pipeline')
        if not pipeline_id:
            from pipeline.models import Pipeline
            default_pipeline = Pipeline.objects.filter(is_default=True).first()
            if not default_pipeline:
                default_pipeline = Pipeline.objects.first()
            if default_pipeline:
                pipeline_id = default_pipeline.id
                
        cards = PipelineQueryService.get_pipeline_cards(request.user, pipeline_id=pipeline_id)
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
        target_stage_name = request.data.get('target_stage')
        target_stage_id = request.data.get('target_stage_id')

        if not entity_type or id_val is None:
            return api_error(
                message="Missing required fields: entity_type and id.",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        from pipeline.models import PipelineStage
        from leads.models import Lead
        from opportunities.models import Opportunity
        from django.db import transaction

        # Look up stage
        target_stage = None
        if target_stage_id is not None:
            try:
                target_stage = PipelineStage.objects.get(pk=target_stage_id)
            except PipelineStage.DoesNotExist:
                return api_error(
                    message="Target stage does not exist.",
                    status_code=status.HTTP_404_NOT_FOUND
                )
        elif target_stage_name:
            # Backward compatibility mapping
            stage_mapping = {
                'NEW': 0,
                'CONTACTED': 1,
                'FOLLOW_UP': 2,
                'QUALIFIED': 3,
                'PROPOSAL': 4,
                'NEGOTIATION': 5,
                'WON': 6,
                'LOST': 7
            }
            order_val = stage_mapping.get(target_stage_name)
            if order_val is None:
                return api_error(
                    message=f"Invalid target stage name: {target_stage_name}",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            try:
                target_stage = PipelineStage.objects.get(pipeline__name="Standard Pipeline", order=order_val)
            except PipelineStage.DoesNotExist:
                return api_error(
                    message="Standard Pipeline default stages are not configured.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
        else:
            return api_error(
                message="Provide target_stage_id or target_stage name.",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        if entity_type == 'lead':
            try:
                lead = Lead.objects.select_related('pipeline_stage', 'assigned_salesperson').get(pk=id_val)
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
            current_stage = lead.pipeline_stage
            is_current_terminal = current_stage and current_stage.stage_type in ['WON', 'LOST']
            if (is_current_terminal or lead.status == 'LOST') and not is_manager_or_admin(request.user):
                return api_error(
                    message="Closed leads are locked and cannot be modified by salespeople.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Rule: Pipeline mismatch check
            if lead.pipeline and target_stage.pipeline != lead.pipeline:
                return api_error(
                    message="Target stage does not belong to the lead's active pipeline.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            if lead.is_converted:
                return api_error(
                    message="Converted leads are read-only and cannot be modified.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Rule: Unidirectional promotion check
            if target_stage.entity_type == 'OPPORTUNITY' and target_stage.stage_type not in ['CONVERSION', 'LOST']:
                return api_error(
                    message="Unconverted leads cannot be moved to Opportunity-only stages.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Rule: Move validation (salesperson must be assigned before moving past NEW)
            if not lead.assigned_salesperson:
                first_stage = PipelineStage.objects.filter(pipeline=target_stage.pipeline).order_by('order').first()
                if target_stage != first_stage:
                    return api_error(
                        message="Assign the lead to a salesperson before moving it from NEW.",
                        status_code=status.HTTP_400_BAD_REQUEST
                    )

            # Execution
            if target_stage.stage_type == 'CONVERSION':
                from leads.services import LeadWorkflowService
                try:
                    with transaction.atomic():
                        lead.status = 'QUALIFIED'
                        lead.pipeline_stage = target_stage
                        lead.save()
                        
                        converted_lead = LeadWorkflowService.convert_lead(lead)
                        opportunity = converted_lead.converted_opportunity
                        
                        opportunity.pipeline_stage = target_stage
                        opportunity.pipeline = lead.pipeline
                        opportunity.stage = 'QUALIFICATION'
                        opportunity.save()
                        
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
                        "primary_contact_id": opportunity.primary_contact_id,
                        "pipeline_stage_id": opportunity.pipeline_stage_id
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
                lead.pipeline_stage = target_stage
                if target_stage.stage_type == 'NORMAL_LEAD':
                    if target_stage.order == 0:
                        lead.status = 'NEW'
                    elif target_stage.order == 1:
                        lead.status = 'CONTACTED'
                    else:
                        lead.status = 'FOLLOW_UP'
                elif target_stage.stage_type == 'LOST':
                    lead.status = 'LOST'
                lead.save()
                
                from pipeline.services.query import map_stage_to_enum
                stage_repr = map_stage_to_enum(target_stage, lead.status)
                
                card_data = {
                    "entity_type": "lead",
                    "id": lead.id,
                    "name": lead.full_name,
                    "company_name": lead.company_name,
                    "phone": lead.phone or '',
                    "email": lead.email or '',
                    "assigned_salesperson_id": lead.assigned_salesperson_id,
                    "assigned_salesperson_name": lead.assigned_salesperson.username if lead.assigned_salesperson else None,
                    "stage": stage_repr,
                    "amount": None,
                    "expected_close_date": None,
                    "probability": None,
                    "notes": lead.notes or '',
                    "company_id": None,
                    "primary_contact_id": None,
                    "pipeline_stage_id": lead.pipeline_stage_id
                }
                return api_success(
                    data=card_data,
                    message="Lead stage updated successfully."
                )

        elif entity_type == 'opportunity':
            try:
                opp = Opportunity.objects.select_related('pipeline_stage', 'assigned_salesperson').get(pk=id_val)
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
            current_stage = opp.pipeline_stage
            is_current_terminal = current_stage and current_stage.stage_type in ['WON', 'LOST']
            if (is_current_terminal or opp.stage in ['CLOSED_WON', 'CLOSED_LOST']) and not is_manager_or_admin(request.user):
                return api_error(
                    message="Closed opportunities are locked and cannot be modified by salespeople.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            # Rule: Pipeline mismatch check
            if opp.pipeline and target_stage.pipeline != opp.pipeline:
                return api_error(
                    message="Target stage does not belong to the opportunity's active pipeline.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Rule: Unidirectional promotion check
            if target_stage.entity_type == 'LEAD':
                return api_error(
                    message="Opportunities cannot be moved to Lead-only stages.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Map stage and save
            opp.pipeline_stage = target_stage
            if target_stage.stage_type == 'CONVERSION':
                opp.stage = 'QUALIFICATION'
            elif target_stage.stage_type == 'NORMAL_OPPORTUNITY':
                if target_stage.order == 4:
                    opp.stage = 'PROPOSAL'
                else:
                    opp.stage = 'NEGOTIATION'
            elif target_stage.stage_type == 'WON':
                opp.stage = 'CLOSED_WON'
            elif target_stage.stage_type == 'LOST':
                opp.stage = 'CLOSED_LOST'
            opp.save()

            from pipeline.services.query import map_stage_to_enum
            stage_repr = map_stage_to_enum(target_stage, opp.stage)

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
                "stage": stage_repr,
                "amount": opp.amount,
                "expected_close_date": opp.expected_close_date,
                "probability": opp.probability,
                "notes": opp.description or '',
                "company_id": opp.company_id,
                "primary_contact_id": opp.primary_contact_id,
                "pipeline_stage_id": opp.pipeline_stage_id
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

class IsManagerOrAdmin(BasePermission):
    def has_permission(self, request, view):
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            return True
        from leads.permissions import is_manager_or_admin
        return is_manager_or_admin(request.user)

class PipelineModelViewSet(viewsets.ModelViewSet):
    from pipeline.models import Pipeline
    from pipeline.serializers import PipelineSerializer
    serializer_class = PipelineSerializer
    queryset = Pipeline.objects.all()
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

class PipelineStageViewSet(viewsets.ModelViewSet):
    from pipeline.models import PipelineStage
    from pipeline.serializers import PipelineStageSerializer
    serializer_class = PipelineStageSerializer
    queryset = PipelineStage.objects.all()
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get_queryset(self):
        pipeline_id = self.request.query_params.get('pipeline')
        if pipeline_id:
            return self.queryset.filter(pipeline_id=pipeline_id)
        return self.queryset

    def destroy(self, request, *args, **kwargs):
        stage = self.get_object()
        from leads.models import Lead
        from opportunities.models import Opportunity
        from pipeline.models import PipelineStage

        # Validation Rule: check if there are active cards in the stage
        active_leads = Lead.objects.filter(pipeline_stage=stage, is_converted=False).count()
        active_opps = Opportunity.objects.filter(pipeline_stage=stage).count()

        if active_leads > 0 or active_opps > 0:
            reassign_stage_id = request.data.get('reassign_stage_id') or request.query_params.get('reassign_stage_id')
            if not reassign_stage_id:
                return api_error(
                    message="Cannot delete stage containing active cards. Please provide a reassign_stage_id.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                reassign_stage = PipelineStage.objects.get(pk=reassign_stage_id, pipeline=stage.pipeline)
            except PipelineStage.DoesNotExist:
                return api_error(
                    message="Reassignment stage does not exist or belongs to a different pipeline.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Move active cards to reassignment stage
            Lead.objects.filter(pipeline_stage=stage).update(pipeline_stage=reassign_stage)
            Opportunity.objects.filter(pipeline_stage=stage).update(pipeline_stage=reassign_stage)

        # Deletion constraints for stage types:
        if stage.stage_type == 'WON':
            if PipelineStage.objects.filter(pipeline=stage.pipeline, stage_type='WON').count() <= 1:
                return api_error(
                    message="Cannot delete the only WON stage of the pipeline.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
        elif stage.stage_type == 'CONVERSION':
            if PipelineStage.objects.filter(pipeline=stage.pipeline, stage_type='CONVERSION').count() <= 1:
                return api_error(
                    message="Cannot delete the only CONVERSION stage of the pipeline.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
        elif stage.stage_type == 'LOST':
            if PipelineStage.objects.filter(pipeline=stage.pipeline, stage_type='LOST').count() <= 1:
                return api_error(
                    message="Cannot delete the last LOST stage of the pipeline.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

        stage.delete()
        return api_success(message="Stage deleted successfully.")
