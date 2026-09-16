from django.core.management.base import BaseCommand
from accounts.models import Organization
from billing.services import DunningService


class Command(BaseCommand):
    help = "Executes durable dunning retry attempts (Day 3, 7, 14) for all PAST_DUE subscriptions."

    def add_arguments(self, parser):
        parser.add_argument(
            '--organization-id',
            type=int,
            default=None,
            help='Optional organization ID to limit dunning retry processing.'
        )

    def handle(self, *args, **options):
        org_id = options.get('organization_id')
        org = None

        if org_id:
            try:
                org = Organization.objects.get(id=org_id)
                self.stdout.write(self.style.NOTICE(f"Processing dunning retries for Organization ID {org_id}..."))
            except Organization.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"Organization with ID {org_id} does not exist."))
                return
        else:
            self.stdout.write(self.style.NOTICE("Processing dunning retries for all tenant organizations..."))

        results = DunningService.process_dunning_retries(organization=org)

        self.stdout.write(
            self.style.SUCCESS(
                f"Dunning processing complete. Processed: {results['processed']}, Succeeded: {results['succeeded']}, Failed: {results['failed']}, Exhausted (UNPAID): {results['exhausted']}."
            )
        )
