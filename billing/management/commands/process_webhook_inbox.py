from django.core.management.base import BaseCommand
from billing.models import WebhookInbox
from billing.services import WebhookInboxProcessor


class Command(BaseCommand):
    help = "Processes PENDING WebhookInbox events for asynchronous, durable processing."

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Maximum number of pending webhook inbox events to process in one execution run.'
        )

    def handle(self, *args, **options):
        limit = options['limit']
        pending_items = WebhookInbox.objects.filter(status='PENDING').order_by('created_at')[:limit]

        processed_count = 0
        failed_count = 0

        self.stdout.write(self.style.NOTICE(f"Found {len(pending_items)} pending WebhookInbox item(s) to process (limit={limit})."))

        for item in pending_items:
            success = WebhookInboxProcessor.process_inbox_item(item)
            if success:
                processed_count += 1
            else:
                failed_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"WebhookInbox processing complete. Processed successfully: {processed_count}, Failed: {failed_count}."
            )
        )
