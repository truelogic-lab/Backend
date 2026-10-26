from django.contrib import admin
from .models import MerchantProfile, APIKey, SettlementAccount, Transaction

@admin.register(MerchantProfile)
class MerchantProfileAdmin(admin.ModelAdmin):
    list_display = ('business_name', 'user', 'is_active', 'created_at')
    search_fields = ('business_name', 'user__email')

@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ('name', 'merchant', 'public_key', 'environment', 'is_active')
    search_fields = ('public_key', 'merchant__business_name')

@admin.register(SettlementAccount)
class SettlementAccountAdmin(admin.ModelAdmin):
    list_display = ('merchant', 'account_type', 'shortcode')
    search_fields = ('shortcode',)

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_id', 'merchant', 'amount', 'phone_number', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('mpesa_receipt_number', 'account_reference', 'phone_number')
