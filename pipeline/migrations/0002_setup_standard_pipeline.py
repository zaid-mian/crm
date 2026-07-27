from django.db import migrations

def create_default_pipeline(apps, schema_editor):
    Pipeline = apps.get_model('pipeline', 'Pipeline')
    PipelineStage = apps.get_model('pipeline', 'PipelineStage')
    Lead = apps.get_model('leads', 'Lead')
    Opportunity = apps.get_model('opportunities', 'Opportunity')

    # Create default pipeline
    pipeline, _ = Pipeline.objects.get_or_create(
        name="Standard Pipeline",
        defaults={"description": "Standard Sales and Leads Pipeline"}
    )

    # Create default stages
    stages = [
        ("New", "LEAD", "NORMAL_LEAD", 0, "#6c757d"),
        ("Contacted", "LEAD", "NORMAL_LEAD", 1, "#0d6efd"),
        ("Follow Up", "LEAD", "NORMAL_LEAD", 2, "#ffc107"),
        ("Qualified", "OPPORTUNITY", "CONVERSION", 3, "#198754"),
        ("Proposal", "OPPORTUNITY", "NORMAL_OPPORTUNITY", 4, "#0dcaf0"),
        ("Negotiation", "OPPORTUNITY", "NORMAL_OPPORTUNITY", 5, "#fd7e14"),
        ("Won", "OPPORTUNITY", "WON", 6, "#198754"),
        ("Lost", "OPPORTUNITY", "LOST", 7, "#dc3545"),
    ]

    for name, entity_type, stage_type, order, color in stages:
        PipelineStage.objects.get_or_create(
            pipeline=pipeline,
            order=order,
            defaults={
                "name": name,
                "entity_type": entity_type,
                "stage_type": stage_type,
                "color": color
            }
        )

    # Fetch stages for mapping
    stage_new = PipelineStage.objects.get(pipeline=pipeline, order=0)
    stage_contacted = PipelineStage.objects.get(pipeline=pipeline, order=1)
    stage_followup = PipelineStage.objects.get(pipeline=pipeline, order=2)
    stage_conversion = PipelineStage.objects.get(pipeline=pipeline, order=3)
    stage_proposal = PipelineStage.objects.get(pipeline=pipeline, order=4)
    stage_negotiation = PipelineStage.objects.get(pipeline=pipeline, order=5)
    stage_won = PipelineStage.objects.get(pipeline=pipeline, order=6)
    stage_lost = PipelineStage.objects.get(pipeline=pipeline, order=7)

    # Map Leads
    for lead in Lead.objects.all():
        if lead.status == 'NEW':
            lead.pipeline_stage = stage_new
        elif lead.status in ['CONTACTED', 'ASSIGNED']:
            lead.pipeline_stage = stage_contacted
        elif lead.status in ['FOLLOW_UP', 'DEMO_SCHEDULED', 'PROPOSAL_SENT']:
            lead.pipeline_stage = stage_followup
        elif lead.status in ['QUALIFIED', 'CONVERTED']:
            lead.pipeline_stage = stage_conversion
        elif lead.status == 'LOST':
            lead.pipeline_stage = stage_lost
        lead.save()

    # Map Opportunities
    for opp in Opportunity.objects.all():
        if opp.stage == 'QUALIFICATION':
            opp.pipeline_stage = stage_conversion
        elif opp.stage == 'DISCOVERY':
            opp.pipeline_stage = stage_followup
        elif opp.stage == 'PROPOSAL':
            opp.pipeline_stage = stage_proposal
        elif opp.stage == 'NEGOTIATION':
            opp.pipeline_stage = stage_negotiation
        elif opp.stage == 'CLOSED_WON':
            opp.pipeline_stage = stage_won
        elif opp.stage == 'CLOSED_LOST':
            opp.pipeline_stage = stage_lost
        opp.save()

def rollback_default_pipeline(apps, schema_editor):
    Pipeline = apps.get_model('pipeline', 'Pipeline')
    Pipeline.objects.filter(name="Standard Pipeline").delete()

class Migration(migrations.Migration):

    dependencies = [
        ('pipeline', '0001_initial'),
        ('leads', '0004_lead_pipeline_stage'),
        ('opportunities', '0004_opportunity_pipeline_stage'),
    ]

    operations = [
        migrations.RunPython(create_default_pipeline, reverse_code=rollback_default_pipeline),
    ]
