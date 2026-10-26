from django.urls import path
from .views import *
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

class PublicTokenObtainPairView(TokenObtainPairView):
    authentication_classes = []

urlpatterns = [
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', EmailTokenObtainPairView.as_view(), name='login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/me/', UserProfileView.as_view(), name='user_profile'),
    path('auth/change-password/', ChangePasswordView.as_view(), name='change_password'),
    path('auth/test-email/', SendTestEmailView.as_view(), name='test_email'),
    path('keys/', APIKeyListCreateView.as_view(), name='api_keys_list'),
    path('keys/<int:pk>/', APIKeyDetailView.as_view(), name='api_key_detail'),
    path('settlement/', SettlementView.as_view(), name='settlement'),
    path('transactions/', TransactionListView.as_view(), name='transactions'),
    path('payments/stkpush/', InitiatePaymentView.as_view(), name='stkpush'),
    path('v1/payments/stkpush/', APIv1STKPushView.as_view(), name='api_v1_stkpush'),

    # Admin Routes
    path('admin/stats/', AdminPlatformStatsView.as_view(), name='admin_stats'),
    path('admin/merchants/', AdminMerchantListView.as_view(), name='admin_merchants'),
    path('admin/merchants/<int:pk>/toggle/', AdminMerchantToggleView.as_view(), name='admin_merchant_toggle'),
    path('admin/settings/', AdminSettingsView.as_view(), name='admin_settings'),
    path('admin/content/', AdminSiteContentView.as_view(), name='admin_content'),

    # Public Content
    path('public/content/', PublicSiteContentView.as_view(), name='public_content'),
    path('cron/expire/', ExpireTransactionsView.as_view(), name='expire_transactions'),
    path('setup/', ManualSetupView.as_view(), name='manual_setup'),
    path('admin/profile/', AdminProfileView.as_view(), name='admin_profile'),
    path('admin/change-password/', AdminChangePasswordView.as_view(), name='admin_change_password'),
    path('admin/transactions/', AdminTransactionListView.as_view(), name='admin_transactions'),
    path('admin/subscriptions/', AdminSubscriptionStatsView.as_view(), name='admin_subscriptions'),
    path('admin/blog/', AdminBlogListCreateView.as_view(), name='admin_blog_list'),
    path('admin/blog/<int:pk>/', AdminBlogDetailView.as_view(), name='admin_blog_detail'),
    path('public/blog/', PublicBlogListView.as_view(), name='public_blog_list'),
    path('public/blog/<str:slug>/', PublicBlogDetailView.as_view(), name='public_blog_detail'),
    
    path('mpesa/callback/', MpesaCallbackView.as_view(), name='mpesa_callback'),
    path('dashboard/stats/', DashboardStatsView.as_view(), name='dashboard_stats'),
    path('dashboard/chart/', RevenueChartView.as_view(), name='dashboard_chart'),
    path('links/', PaymentLinkListCreateView.as_view(), name='links_list'),
    path('links/<int:pk>/', PaymentLinkDetailView.as_view(), name='link_detail'),
    
    # Public Routes - accepting slug or link_id
    path('public/links/<str:identifier>/', PublicPaymentLinkView.as_view(), name='public_link'),
    path('public/links/<str:identifier>/checkout/', PublicPaymentLinkCheckoutView.as_view(), name='public_link_checkout'),
    path('webhooks/deliveries/', WebhookDeliveryListView.as_view(), name='webhook_deliveries'),
    path('webhooks/deliveries/<int:pk>/retry/', WebhookRetryView.as_view(), name='webhook_retry'),
    path('customers/', CustomerListView.as_view(), name='customers_list'),
    path('invoices/', InvoiceListCreateView.as_view(), name='invoices_list'),
    path('team/', TeamMemberListCreateView.as_view(), name='team_list'),
    path('team/<int:pk>/', TeamMemberDetailView.as_view(), name='team_detail'),
    path('invoices/<int:pk>/', InvoiceDetailView.as_view(), name='invoice_detail'),
    path('invoices/<int:pk>/send/', SendInvoiceSTKPushView.as_view(), name='invoice_send'),
    path('customers/<str:phone_number>/', CustomerDetailView.as_view(), name='customer_detail'),
]
