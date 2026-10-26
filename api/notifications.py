from django.core.mail import send_mail
from django.conf import settings

def send_payment_email(merchant, status, transaction):
    # Respect merchant preferences
    if status == 'success' and not merchant.notify_on_success:
        return
    if status == 'failed' and not merchant.notify_on_failure:
        return

    recipient = merchant.notify_email or merchant.user.email
    if not recipient:
        return

    subject = f"Payment {status.upper()} - {transaction.account_reference}"
    message = f"""
Hello {merchant.business_name},

A payment has been {status}.

Details:
- Amount: KES {transaction.amount}
- Phone: {transaction.phone_number}
- Reference: {transaction.account_reference}
- Receipt: {transaction.mpesa_receipt_number or 'N/A'}

Log into your dashboard for more details.

- PayWaveKE
    """
    
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=True,
        )
        print(f"Email notification sent to {recipient}")
    except Exception as e:
        print(f"Email error: {e}")

def send_subscription_reminder(merchant, days_left):
    recipient = merchant.notify_email or merchant.user.email
    if not recipient:
        return

    subject = f"Your PayWaveKE subscription expires in {days_left} days"
    message = f"""
Hello {merchant.business_name},

Your PayWaveKE subscription will expire in {days_left} days.

To keep accepting payments without interruption, please renew your plan.

Contact us: billing@paywaveke.com

- The PayWaveKE Team
    """
    
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [recipient], fail_silently=True)
        print(f"Reminder sent to {recipient}")
    except Exception as e:
        print(f"Reminder error: {e}")
