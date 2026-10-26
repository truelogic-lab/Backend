import base64
import requests
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from .models import PlatformConfig

load_dotenv()

_token_cache = {}

def get_credentials(environment):
    """Returns credentials for the given environment, with fallback to sandbox if live is missing."""
    config = PlatformConfig.objects.filter(id=1).first()
    
    if environment == 'live':
        key = config.live_consumer_key if config else None
        secret = config.live_consumer_secret if config else None
        passkey = config.live_passkey if config else None
        shortcode = config.live_shortcode if config else None
        
        # If live is not configured, fallback to sandbox
        if not key or not secret:
            print("WARNING: Live credentials missing. Falling back to sandbox.")
            environment = 'sandbox'
    
    if environment == 'sandbox':
        key = config.sandbox_consumer_key if config else None
        secret = config.sandbox_consumer_secret if config else None
        passkey = config.sandbox_passkey if config else None
        shortcode = config.sandbox_shortcode if config else None

    callback = config.callback_url if config and config.callback_url else os.getenv("DARAJA_CALLBACK_URL", "https://your-domain.com/api/v1/mpesa/callback/")
    
    return key, secret, passkey, shortcode, callback, environment


def get_mpesa_token(environment):
    """Fetches OAuth token with caching. Returns (token, actual_environment)."""
    key, secret, _, _, _, actual_env = get_credentials(environment)
    
    if not key or not secret:
        print(f"ERROR: Missing {actual_env} Daraja credentials")
        return None, actual_env

    # Cache key is the actual environment
    now = time.time()
    cached = _token_cache.get(actual_env)
    if cached and cached['expires'] > now:
        return cached['token'], actual_env

    url = "https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials" if actual_env == 'live' else "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    
    try:
        response = requests.get(url, auth=(key, secret))
        response.raise_for_status()
        token = response.json().get('access_token')
        
        _token_cache[actual_env] = {'token': token, 'expires': now + 3300}
        return token, actual_env
    except Exception as e:
        print(f"Error getting token ({actual_env}): {e}")
        return None, actual_env


def initiate_stk_push(phone_number, amount, account_reference, description, merchant_shortcode, environment='sandbox', account_type='paybill'):
    token, actual_env = get_mpesa_token(environment)
    
    if not token:
        return {"error": f"Authentication with Safaricom ({actual_env}) failed. Check Admin Settings."}

    config = PlatformConfig.objects.filter(id=1).first()
    is_aggregator = config.aggregator_mode if config else False
    
    _, _, passkey, platform_shortcode, callback, _ = get_credentials(actual_env)
    
    if is_aggregator:
        shortcode_to_use = str(merchant_shortcode)
        transaction_type = "CustomerPayBillOnline" if account_type == 'paybill' else "CustomerBuyGoodsOnline"
    else:
        shortcode_to_use = platform_shortcode
        transaction_type = "CustomerPayBillOnline"

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode((shortcode_to_use + passkey + timestamp).encode()).decode()

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    payload = {
        "BusinessShortCode": shortcode_to_use,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": transaction_type,
        "Amount": amount,
        "PartyA": phone_number,
        "PartyB": shortcode_to_use,
        "PhoneNumber": phone_number,
        "CallBackURL": callback,
        "AccountReference": account_reference,
        "TransactionDesc": description
    }

    api_url = "https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest" if actual_env == 'live' else "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    
    try:
        response = requests.post(api_url, json=payload, headers=headers)
        json_resp = response.json()
        if response.status_code != 200:
            print(f"Safaricom STK Push Error ({actual_env}):", json_resp)
            return {"error": json_resp.get('errorMessage', 'Failed')}
        return json_resp
    except Exception as e:
        return {"error": str(e)}


def query_stk_status(checkout_request_id, environment='sandbox'):
    token, actual_env = get_mpesa_token(environment)
    if not token:
        return None

    _, _, passkey, shortcode, _, _ = get_credentials(actual_env)
    
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode((shortcode + passkey + timestamp).encode()).decode()

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id
    }

    url = "https://api.safaricom.co.ke/mpesa/stkpushquery/v1/query" if actual_env == 'live' else "https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query"
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        return response.json()
    except Exception as e:
        print(f"Error querying STK status: {e}")
        return None
