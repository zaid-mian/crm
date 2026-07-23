from django.db import migrations

def migrate_legacy_data(apps, schema_editor):
    Company = apps.get_model('companies', 'Company')
    Contact = apps.get_model('contacts', 'Contact')
    Opportunity = apps.get_model('opportunities', 'Opportunity')

    created_count = 0
    reused_count = 0
    contacts_migrated = 0
    opps_migrated = 0

    # 1. Migrate Contacts (including deleted ones to keep historical integrity)
    for contact in Contact.objects.all():
        if not contact.company_name:
            continue
        c_name = contact.company_name.strip()
        if not c_name:
            continue

        company = Company.objects.filter(name__iexact=c_name).first()
        if not company:
            company = Company.objects.create(
                name=c_name,
                assigned_salesperson=contact.assigned_salesperson,
                phone=contact.phone_number or '',
                email=contact.email
            )
            created_count += 1
        else:
            reused_count += 1

        contact.company = company
        contact.save(update_fields=['company'])
        contacts_migrated += 1

    # 2. Migrate Opportunities
    for opp in Opportunity.objects.all():
        if not opp.company_name:
            continue
        c_name = opp.company_name.strip()
        if not c_name:
            continue

        company = Company.objects.filter(name__iexact=c_name).first()
        if not company:
            company = Company.objects.create(
                name=c_name,
                assigned_salesperson=opp.assigned_salesperson,
                lead_source=opp.lead_source
            )
            created_count += 1
        else:
            reused_count += 1

        opp.company = company
        opp.save(update_fields=['company'])
        opps_migrated += 1

    print(f"\n--- DATA MIGRATION RESULTS ---")
    print(f"Company records created: {created_count}")
    print(f"Existing Companies reused: {reused_count}")
    print(f"Contacts migrated: {contacts_migrated}")
    print(f"Opportunities migrated: {opps_migrated}")
    print(f"------------------------------")


def reverse_legacy_data(apps, schema_editor):
    Contact = apps.get_model('contacts', 'Contact')
    Opportunity = apps.get_model('opportunities', 'Opportunity')
    Company = apps.get_model('companies', 'Company')

    Contact.objects.all().update(company=None)
    Opportunity.objects.all().update(company=None)
    Company.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0001_initial'),
        ('contacts', '0003_contact_company'),
        ('opportunities', '0002_opportunity_company'),
    ]

    operations = [
        migrations.RunPython(migrate_legacy_data, reverse_code=reverse_legacy_data),
    ]
