import uuid
from django.db import models
from django.contrib.auth.models import User
import secrets





class MerchantProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='merchant_profile')
    business_name = models.CharField(max_length=255)
    webhook_url = models.URLField(blank=True, null=True)
    
    ENVIRONMENT_CHOICES = (('sandbox', 'Sandbox'), ('live', 'Live'))
    environment_mode = models.CharField(max_length=10, choices=ENVIRONMENT_CHOICES, default='sandbox')
    
    notify_on_success = models.BooleanField(default=True)
    notify_on_failure = models.BooleanField(default=True)
    notify_email = models.EmailField(blank=True, null=True)

    subscription_expires_at = models.DateTimeField(null=True, blank=True) # NEW

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.business_name

class APIKey(models.Model):
    ENVIRONMENT_CHOICES = (('test', 'Test/Sandbox'), ('live', 'Live'))
    merchant = models.ForeignKey(MerchantProfile, on_delete=models.CASCADE, related_name='api_keys')
    name = models.CharField(max_length=100, default="Default Key")
    public_key = models.CharField(max_length=100, unique=True, blank=True)
    secret_key = models.CharField(max_length=100, unique=True, blank=True)
    environment = models.CharField(max_length=10, choices=ENVIRONMENT_CHOICES, default='test')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.public_key: self.public_key = f"pk_{self.environment}_{secrets.token_hex(16)}"
        if not self.secret_key: self.secret_key = f"sk_{self.environment}_{secrets.token_hex(24)}"
        super().save(*args, **kwargs)
    def __str__(self): return f"{self.name} ({self.public_key})"

class SettlementAccount(models.Model):
    TYPE_CHOICES = (('till', 'Buy Goods (Till)'), ('paybill', 'Paybill'))
    merchant = models.OneToOneField(MerchantProfile, on_delete=models.CASCADE, related_name='settlement')
    account_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='till')
    shortcode = models.CharField(max_length=10) 
    account_number = models.CharField(max_length=50, blank=True, null=True) 
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return f"{self.account_type.upper()}: {self.shortcode}"



class Transaction(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
    )
    merchant = models.ForeignKey(MerchantProfile, on_delete=models.CASCADE, related_name='transactions')
    transaction_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    merchant_request_id = models.CharField(max_length=100, blank=True, null=True)
    checkout_request_id = models.CharField(max_length=100, blank=True, null=True)
    phone_number = models.CharField(max_length=15)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    account_reference = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    result_code = models.IntegerField(blank=True, null=True)
    result_desc = models.TextField(blank=True, null=True)
    mpesa_receipt_number = models.CharField(max_length=50, blank=True, null=True, unique=True) 
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self): return f"{self.account_reference} - KES {self.amount} - {self.status}"

class PaymentLink(models.Model):
    merchant = models.ForeignKey(MerchantProfile, on_delete=models.CASCADE, related_name='payment_links')
    link_id = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True, null=True)
    title = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(blank=True, null=True) # NEW: If null, it never expires
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} - KES {self.amount}"

    @property
    def is_expired(self):
        if self.expires_at is None:
            return False
        from django.utils import timezone
        return timezone.now() > self.expires_at


class WebhookDelivery(models.Model):
    merchant = models.ForeignKey(MerchantProfile, on_delete=models.CASCADE, related_name='webhook_deliveries')
    event_type = models.CharField(max_length=100)
    url = models.URLField()
    payload = models.JSONField()
    status_code = models.IntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True, null=True)
    is_success = models.BooleanField(default=False)
    attempts = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.event_type} - {self.url} ({'OK' if self.is_success else 'FAILED'})"

class Invoice(models.Model):
    STATUS_CHOICES = (('pending', 'Pending'), ('paid', 'Paid'), ('overdue', 'Overdue'))
    merchant = models.ForeignKey(MerchantProfile, on_delete=models.CASCADE, related_name='invoices')
    invoice_number = models.CharField(max_length=50, unique=True)
    customer_name = models.CharField(max_length=255)
    customer_phone = models.CharField(max_length=15)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    due_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.invoice_number} - {self.customer_name} - KES {self.amount}"

class TeamMember(models.Model):
    ROLE_CHOICES = (
        ('admin', 'Admin'),
        ('finance', 'Finance'),
        ('developer', 'Developer'),
        ('viewer', 'Viewer'),
    )
    merchant = models.ForeignKey(MerchantProfile, on_delete=models.CASCADE, related_name='team_members')
    name = models.CharField(max_length=255)
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='viewer')
    is_active = models.BooleanField(default=True)
    invited_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('merchant', 'email')

    def __str__(self):
        return f"{self.email} ({self.role})"

class PlatformConfig(models.Model):
    # A singleton model (only one row exists)
    sandbox_consumer_key = models.CharField(max_length=255, blank=True, null=True)
    sandbox_consumer_secret = models.CharField(max_length=255, blank=True, null=True)
    sandbox_passkey = models.CharField(max_length=255, blank=True, null=True)
    sandbox_shortcode = models.CharField(max_length=50, blank=True, null=True)
    
    live_consumer_key = models.CharField(max_length=255, blank=True, null=True)
    live_consumer_secret = models.CharField(max_length=255, blank=True, null=True)
    live_passkey = models.CharField(max_length=255, blank=True, null=True)
    live_shortcode = models.CharField(max_length=50, blank=True, null=True)
    
    callback_url = models.URLField(blank=True, null=True)
    aggregator_mode = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Ensure only one instance exists
        self.id = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return "Platform Configuration"

class BlogPost(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=True, null=True)
    category = models.CharField(max_length=100, default='Article')
    excerpt = models.TextField(blank=True, null=True)
    content = models.TextField(help_text="HTML or Markdown content")
    cover_image = models.URLField(blank=True, null=True)
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

class SiteContent(models.Model):
    # We use a simple key-value store for flexible landing page text
    key = models.CharField(max_length=100, unique=True)
    content = models.TextField()
    
    def __str__(self):
        return self.key

class WebhookEvent(models.Model):
    event_type = models.CharField(max_length=50) # e.g., 'mpesa_callback'
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.event_type} - {self.received_at}"
