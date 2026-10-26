from rest_framework import authentication, exceptions
from .models import APIKey

class APIKeyAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return None # Let other authenticators (like JWT) handle it

        # Check if it's an API Key header (e.g., "Bearer sk_test_...")
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return None

        secret_key = parts[1]
        
        # If it's a JWT token, skip this authenticator
        if not secret_key.startswith('sk_'):
            return None

        try:
            api_key = APIKey.objects.get(secret_key=secret_key, is_active=True)
            return (api_key.merchant.user, api_key)
        except APIKey.DoesNotExist:
            raise exceptions.AuthenticationFailed('Invalid or revoked API Key.')
