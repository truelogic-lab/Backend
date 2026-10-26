import requests
import json
import hmac
import hashlib
import time
import threading
from .models import WebhookDelivery

def generate_signature(payload, secret):
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.{payload}"
    signature = hmac.new(
        secret.encode('utf-8'),
        signed_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={signature}"

def send_webhook_async(merchant, event_type, data):
    if not merchant.webhook_url:
        return

    def _send():
        payload_dict = {"event": event_type, "data": data}
        payload_str = json.dumps(payload_dict)
        
        # Log the delivery attempt
        delivery = WebhookDelivery.objects.create(
            merchant=merchant,
            event_type=event_type,
            url=merchant.webhook_url,
            payload=payload_dict,
            attempts=1,
            is_success=False
        )
        
        api_key = merchant.api_keys.first()
        secret = api_key.secret_key if api_key else "whsec_default"
        signature = generate_signature(payload_str, secret)

        headers = {
            "Content-Type": "application/json",
            "X-PayWave-Signature": signature
        }

        try:
            response = requests.post(merchant.webhook_url, data=payload_str, headers=headers, timeout=5)
            
            delivery.status_code = response.status_code
            delivery.response_body = response.text[:500] # Truncate to 500 chars
            delivery.is_success = 200 <= response.status_code < 300
            delivery.save()

            print(f"Webhook sent to {merchant.webhook_url} | Status: {response.status_code}")
        except Exception as e:
            delivery.status_code = 0
            delivery.response_body = str(e)
            delivery.is_success = False
            delivery.save()
            print(f"Webhook failed for {merchant.webhook_url}: {e}")

    threading.Thread(target=_send).start()

def retry_webhook(delivery_id):
    try:
        delivery = WebhookDelivery.objects.get(id=delivery_id)
    except WebhookDelivery.DoesNotExist:
        return False, "Delivery not found"
    
    if delivery.is_success:
        return False, "Already delivered successfully"

    def _retry():
        merchant = delivery.merchant
        payload_str = json.dumps(delivery.payload)
        
        api_key = merchant.api_keys.first()
        secret = api_key.secret_key if api_key else "whsec_default"
        signature = generate_signature(payload_str, secret)

        headers = {
            "Content-Type": "application/json",
            "X-PayWave-Signature": signature
        }

        try:
            response = requests.post(delivery.url, data=payload_str, headers=headers, timeout=5)
            delivery.status_code = response.status_code
            delivery.response_body = response.text[:500]
            delivery.is_success = 200 <= response.status_code < 300
            delivery.attempts += 1
            delivery.save()
        except Exception as e:
            delivery.status_code = 0
            delivery.response_body = str(e)
            delivery.is_success = False
            delivery.attempts += 1
            delivery.save()

    threading.Thread(target=_retry).start()
    return True, "Retry initiated"
