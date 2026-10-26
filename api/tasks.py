from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import Transaction, MerchantProfile

@shared_task
def expire_pending_transactions_task():
    """Marks any pending transaction older than 5 minutes as expired."""
    cutoff = timezone.now() - timedelta(minutes=5)
    expired_count = Transaction.objects.filter(
        status='pending',
        created_at__lt=cutoff
    ).update(status='expired')
    
    if expired_count > 0:
        print(f"[Auto-Expire] Marked {expired_count} transactions as expired.")
    
    return expired_count

@shared_task
def check_subscriptions_task():
    """Sends reminder emails to merchants whose subscription expires in 7 or 2 days."""
    from .notifications import send_subscription_reminder
    
    today = timezone.now().date()
    
    for days_left in [7, 2]:
        target_date = today + timedelta(days=days_left)
        merchants = MerchantProfile.objects.filter(
            is_active=True,
            subscription_expires_at__date=target_date
        )
        
        for merchant in merchants:
            send_subscription_reminder(merchant, days_left)

@shared_task
def send_stk_push_async(transaction_id, phone, amount, reference, description, shortcode, environment, account_type):
    """Sends an STK Push in the background and updates the transaction."""
    from .mpesa_service import initiate_stk_push
    from .models import Transaction
    
    try:
        t = Transaction.objects.get(id=transaction_id)
        
        response = initiate_stk_push(
            phone_number=phone,
            amount=amount,
            account_reference=reference,
            description=description,
            merchant_shortcode=shortcode,
            environment=environment,
            account_type=account_type
        )
        
        if not response or 'error' in response:
            t.status = 'failed'
            t.result_desc = response.get('error', 'STK push failed')
            t.save()
            return f"Failed: {t.result_desc}"
        
        # Save Safaricom references
        t.checkout_request_id = response.get('CheckoutRequestID')
        t.merchant_request_id = response.get('MerchantRequestID')
        t.result_desc = response.get('CustomerMessage', 'STK push sent')
        t.save()
        
        return f"Success: {t.checkout_request_id}"
    except Exception as e:
        return f"Error: {str(e)}"

