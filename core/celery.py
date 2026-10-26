import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

app = Celery('paywaveke')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Scheduled tasks (Celery Beat)
app.conf.beat_schedule = {
    'expire-pending-transactions': {
        'task': 'api.tasks.expire_pending_transactions_task',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
    'check-subscriptions': {
        'task': 'api.tasks.check_subscriptions_task',
        'schedule': crontab(hour=0, minute=0),  # Daily at midnight
    },
}
