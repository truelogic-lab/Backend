from django.core.management.base import BaseCommand
from api.tasks import expire_pending_transactions

class Command(BaseCommand):
    help = 'Marks stale pending transactions as expired.'

    def handle(self, *args, **options):
        count = expire_pending_transactions()
        self.stdout.write(self.style.SUCCESS(f'Expired {count} transactions.'))
