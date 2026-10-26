from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth.models import User
from django.db.models import Sum, Count, Max
from django.db import models
from django.shortcuts import get_object_or_404
from datetime import date, timedelta
from django.utils import timezone

from .serializers import (
    RegisterSerializer, UserSerializer, APIKeySerializer, SettlementSerializer, 
    PaymentLinkSerializer, InvoiceSerializer, TeamMemberSerializer, WebhookDeliverySerializer,
    PasswordChangeSerializer, EmailTokenObtainPairSerializer, BlogPostSerializer
)
from .models import APIKey, SettlementAccount, Transaction, PaymentLink, Invoice, TeamMember, WebhookDelivery, MerchantProfile, PlatformConfig, SiteContent, BlogPost
from .mpesa_service import initiate_stk_push, query_stk_status
from django.db import transaction
from .webhooks import send_webhook_async, retry_webhook
from .notifications import send_payment_email
from .permissions import IsPlatformAdmin
from .tasks import expire_pending_transactions_task
from .utils import normalize_phone
from rest_framework_simplejwt.views import TokenObtainPairView

# --- AUTH ---
class EmailTokenObtainPairView(APIView):
    permission_classes = (permissions.AllowAny,)
    authentication_classes = []
    
    def post(self, request):
        serializer = EmailTokenObtainPairSerializer(data=request.data)
        if serializer.is_valid():
            return Response(serializer.validated_data, status=200)
        return Response(serializer.errors, status=401)

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    authentication_classes = [] 
    permission_classes = (permissions.AllowAny,)
    serializer_class = RegisterSerializer

class UserProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = UserSerializer
    def get_object(self): return self.request.user

class ChangePasswordView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Password updated successfully."}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# --- API KEYS ---
class APIKeyListCreateView(generics.ListCreateAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = APIKeySerializer
    def get_queryset(self): return APIKey.objects.filter(merchant=self.request.user.merchant_profile).order_by('-created_at')
    def perform_create(self, serializer):
        if not self.request.user.merchant_profile.is_active:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Account suspended. Cannot create API keys.")
        env = self.request.user.merchant_profile.environment_mode
        serializer.save(merchant=self.request.user.merchant_profile, environment=env)


class APIKeyDetailView(generics.DestroyAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    def get_queryset(self): return APIKey.objects.filter(merchant=self.request.user.merchant_profile)
    
    def destroy(self, request, *args, **kwargs):
        if not request.user.merchant_profile.is_active:
            return Response({"error": "Account suspended. Cannot delete API keys."}, status=403)
        return super().destroy(request, *args, **kwargs)

class SettlementView(generics.RetrieveUpdateAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = SettlementSerializer
    def update(self, request, *args, **kwargs):
        if not request.user.merchant_profile.is_active:
            return Response({"error": "Account suspended."}, status=403)
        return super().update(request, *args, **kwargs)

    def get_object(self):
        settlement, _ = SettlementAccount.objects.get_or_create(merchant=self.request.user.merchant_profile)
        return settlement

# --- TRANSACTIONS ---
class TransactionListView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    def get(self, request):
        # Auto-expire stale pending transactions on every fetch
        expire_pending_transactions_task.delay()
        
        transactions = Transaction.objects.filter(merchant=request.user.merchant_profile).order_by('-created_at')
        search = request.query_params.get('search', None)
        if search:
            transactions = transactions.filter(
                models.Q(account_reference__icontains=search) |
                models.Q(phone_number__icontains=search) |
                models.Q(mpesa_receipt_number__icontains=search)
            )
        status_filter = request.query_params.get('status', None)
        if status_filter and status_filter != 'all':
            transactions = transactions.filter(status=status_filter)
        data = [{"id": str(t.transaction_id), "amount": t.amount, "phone": t.phone_number, "reference": t.account_reference, "status": t.status, "receipt": t.mpesa_receipt_number, "date": t.created_at} for t in transactions]
        return Response(data)

# --- STK PUSH ---

class InitiatePaymentView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    def post(self, request):
        if not request.user.merchant_profile.is_active:
            return Response({"error": "Account suspended. Cannot initiate payments."}, status=403)
        
        phone = request.data.get('phone')
        amount = request.data.get('amount')
        reference = request.data.get('reference', 'Test Payment')
        
        if not phone or not amount: 
            return Response({"error": "Phone and amount are required"}, status=status.HTTP_400_BAD_REQUEST)
        
        settlement = SettlementAccount.objects.filter(merchant=request.user.merchant_profile).first()
        if not settlement or not settlement.shortcode:
            return Response({"error": "Please configure your Settlement Account before receiving payments."}, status=status.HTTP_400_BAD_REQUEST)
        
        phone = normalize_phone(phone)
        
        # Create a pending transaction immediately
        t = Transaction.objects.create(
            merchant=request.user.merchant_profile,
            phone_number=phone,
            amount=amount,
            account_reference=reference,
            status='pending'
        )
        
        # Queue the STK Push as a background task
        from .tasks import send_stk_push_async
        send_stk_push_async.delay(
            transaction_id=t.id,
            phone=phone,
            amount=str(amount),
            reference=reference,
            description="Payment for " + reference,
            shortcode=settlement.shortcode,
            environment=request.user.merchant_profile.environment_mode,
            account_type=settlement.account_type
        )
        
        return Response({
            "message": "STK Push request queued. Customer will receive prompt shortly.",
            "transaction_id": str(t.transaction_id),
            "status": "pending"
        }, status=status.HTTP_202_ACCEPTED)

class APIv1STKPushView(APIView):
    permission_classes = (permissions.IsAuthenticated,) 
    def post(self, request):
        api_key = request.auth 
        if not hasattr(api_key, 'environment'):
            return Response({"error": "Invalid authentication method"}, status=401)
        phone = request.data.get('phone')
        amount = request.data.get('amount')
        reference = request.data.get('reference', 'API Payment')
        if not phone or not amount: return Response({"error": "Phone and amount are required"}, status=400)
        settlement = SettlementAccount.objects.filter(merchant=api_key.merchant).first()
        if not settlement: return Response({"error": "Merchant settlement account not configured"}, status=400)
        response = initiate_stk_push(phone, amount, reference, "API Payment: " + reference, settlement.shortcode, environment=env, account_type=settlement.account_type)
        if not response or 'error' in response: return Response({"error": response.get('error', 'Failed')}, status=400)
        Transaction.objects.create(merchant=api_key.merchant, checkout_request_id=response.get('CheckoutRequestID'), merchant_request_id=response.get('MerchantRequestID'), phone_number=phone, amount=amount, account_reference=reference, status='pending')
        return Response({"message": "STK Push sent successfully", "checkout_request_id": response.get('CheckoutRequestID')})

# --- CALLBACK & WEBHOOKS ---

class MpesaCallbackView(APIView):
    permission_classes = ()
    authentication_classes = []
    
    def post(self, request):
        # 1. Log the raw payload for disputes
        WebhookEvent.objects.create(event_type="mpesa_callback", payload=request.data)
        
        stk_callback = request.data.get('Body', {}).get('stkCallback', {})
        checkout_id = stk_callback.get('CheckoutRequestID')
        
        if not checkout_id:
            return Response({"ResultCode": 0, "ResultDesc": "Success"})

        # 2. Query Safaricom to verify the real status
        query = query_stk_status(checkout_id, environment='sandbox')
        
        # If the query fails or returns an error, we do NOT trust the callback
        if not query:
            return Response({"ResultCode": 1, "ResultDesc": "Verification failed"})
            
        result_code = query.get('ResultCode')
        result_desc = query.get('ResultDesc')
        
        # 3. Lock the transaction row to prevent race conditions
        with transaction.atomic():
            t = Transaction.objects.select_for_update().filter(checkout_request_id=checkout_id).first()
            
            if not t or t.status != 'pending':
                # Already processed (idempotency)
                return Response({"ResultCode": 0, "ResultDesc": "Already processed"})

            t.result_code = result_code
            t.result_desc = result_desc
            
            if str(result_code) == '0':
                t.status = 'success'
                # Extract receipt from callback metadata (still available)
                items = stk_callback.get('CallbackMetadata', {}).get('Item', [])
                for item in items:
                    if item.get('Name') == 'MpesaReceiptNumber':
                        t.mpesa_receipt_number = item.get('Value')
                
                # Mark invoice as paid
                invoice = Invoice.objects.filter(merchant=t.merchant, invoice_number=t.account_reference).first()
                if invoice:
                    invoice.status = 'paid'
                    invoice.save()
            elif str(result_code) == '1032':
                t.status = 'cancelled'
            elif str(result_code) == '1037':
                t.status = 'expired'
            else:
                t.status = 'failed'

            t.save()

            # Send notifications only on success
            if t.status == 'success':
                send_payment_email(t.merchant, t.status, t)
                send_webhook_async(t.merchant, "payment.success", {
                    "transaction_id": str(t.transaction_id),
                    "amount": float(t.amount),
                    "phone_number": t.phone_number,
                    "reference": t.account_reference,
                    "receipt": t.mpesa_receipt_number
                })

        return Response({"ResultCode": 0, "ResultDesc": "Success"})

class WebhookDeliveryListView(generics.ListAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = WebhookDeliverySerializer
    def get_queryset(self): return WebhookDelivery.objects.filter(merchant=self.request.user.merchant_profile).order_by('-created_at')[:50]

class WebhookRetryView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    def post(self, request, pk):
        delivery = WebhookDelivery.objects.filter(id=pk, merchant=request.user.merchant_profile).first()
        if not delivery: return Response({"error": "Not found"}, status=404)
        success, msg = retry_webhook(delivery.id)
        if not success: return Response({"error": msg}, status=400)
        return Response({"message": msg})

# --- DASHBOARD ---
class DashboardStatsView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    def get(self, request):
        merchant = request.user.merchant_profile
        transactions = Transaction.objects.filter(merchant=merchant)
        recent_txs = transactions.order_by('-created_at')[:5]
        return Response({
            "total_revenue": transactions.filter(status='success').aggregate(Sum('amount'))['amount__sum'] or 0,
            "successful_count": transactions.filter(status='success').count(),
            "pending_count": transactions.filter(status='pending').count(),
            "failed_count": transactions.filter(status='failed').count(),
            "recent_transactions": [{"id": str(t.transaction_id), "amount": t.amount, "phone": t.phone_number, "reference": t.account_reference, "status": t.status, "date": t.created_at} for t in recent_txs]
        })

class RevenueChartView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    def get(self, request):
        today = timezone.now().date()
        start_date = today - timedelta(days=6)
        transactions = Transaction.objects.filter(merchant=request.user.merchant_profile, status='success', created_at__date__gte=start_date)
        daily_data = {start_date + timedelta(days=i): 0 for i in range(7)}
        for t in transactions:
            day = t.created_at.date()
            if day in daily_data: daily_data[day] += float(t.amount)
        return Response([{"date": d.strftime('%a'), "full_date": d.strftime('%Y-%m-%d'), "amount": a} for d, a in sorted(daily_data.items())])

# --- LINKS, INVOICES, CUSTOMERS, TEAM ---
class PaymentLinkListCreateView(generics.ListCreateAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = PaymentLinkSerializer
    def get_queryset(self): return PaymentLink.objects.filter(merchant=self.request.user.merchant_profile).order_by('-created_at')
    def perform_create(self, serializer): serializer.save(merchant=self.request.user.merchant_profile)

class PaymentLinkDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = PaymentLinkSerializer
    def get_queryset(self): return PaymentLink.objects.filter(merchant=self.request.user.merchant_profile)

class PublicPaymentLinkView(APIView):
    permission_classes = (permissions.AllowAny,)
    authentication_classes = []
    def get(self, request, identifier):
        link = PaymentLink.objects.filter(is_active=True).filter(models.Q(slug=identifier) | models.Q(link_id=identifier)).first()
        if not link or link.is_expired: return Response({"error": "This payment link is invalid, expired, or inactive."}, status=404)
        return Response(PaymentLinkSerializer(link).data)


class PublicPaymentLinkCheckoutView(APIView):
    permission_classes = (permissions.AllowAny,)
    authentication_classes = []

    def post(self, request, identifier):
        phone = request.data.get('phone')
        if not phone: return Response({"error": "Phone is required"}, status=400)

        link = PaymentLink.objects.filter(is_active=True).filter(models.Q(slug=identifier) | models.Q(link_id=identifier)).first()
        if not link or link.is_expired: 
            return Response({"error": "This payment link is invalid, expired, or inactive."}, status=404)
            
        if not link.merchant.is_active:
            return Response({"error": "This merchant is currently unable to accept payments."}, status=403)

        settlement = SettlementAccount.objects.filter(merchant=link.merchant).first()
        if not settlement or not settlement.shortcode:
            return Response({"error": "Merchant has not configured a settlement account."}, status=400)

        phone = normalize_phone(phone)
        
        t = Transaction.objects.create(
            merchant=link.merchant,
            phone_number=phone,
            amount=link.amount,
            account_reference=link.title,
            status='pending'
        )
        
        from .tasks import send_stk_push_async
        send_stk_push_async.delay(
            transaction_id=t.id,
            phone=phone,
            amount=str(link.amount),
            reference=link.title,
            description="Payment for " + link.title,
            shortcode=settlement.shortcode,
            environment=link.merchant.environment_mode,
            account_type=settlement.account_type
        )
        
        return Response({
            "message": "Payment request queued. Check your phone shortly.",
            "transaction_id": str(t.transaction_id)
        }, status=202)

class InvoiceListCreateView(generics.ListCreateAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = InvoiceSerializer
    def get_queryset(self):
        Invoice.objects.filter(merchant=self.request.user.merchant_profile, status='pending', due_date__lt=date.today()).update(status='overdue')
        return Invoice.objects.filter(merchant=self.request.user.merchant_profile).order_by('-created_at')
    def perform_create(self, serializer): serializer.save(merchant=self.request.user.merchant_profile)

class InvoiceDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = InvoiceSerializer
    def get_queryset(self): return Invoice.objects.filter(merchant=self.request.user.merchant_profile)


class SendInvoiceSTKPushView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    def post(self, request, pk):
        if not request.user.merchant_profile.is_active:
            return Response({"error": "Account suspended."}, status=403)
        invoice = Invoice.objects.filter(id=pk, merchant=request.user.merchant_profile).first()
        if not invoice: return Response({"error": "Invoice not found"}, status=404)
        if invoice.status == 'paid': return Response({"error": "Invoice already paid"}, status=400)
        
        settlement = SettlementAccount.objects.filter(merchant=request.user.merchant_profile).first()
        if not settlement: return Response({"error": "Settlement account not configured"}, status=400)
        
        phone = normalize_phone(invoice.customer_phone)
        
        t = Transaction.objects.create(
            merchant=request.user.merchant_profile,
            phone_number=phone,
            amount=invoice.amount,
            account_reference=invoice.invoice_number,
            status='pending'
        )
        
        from .tasks import send_stk_push_async
        send_stk_push_async.delay(
            transaction_id=t.id,
            phone=phone,
            amount=str(invoice.amount),
            reference=invoice.invoice_number,
            description=f"Invoice {invoice.invoice_number}",
            shortcode=settlement.shortcode,
            environment=request.user.merchant_profile.environment_mode,
            account_type=settlement.account_type
        )
        
        return Response({
            "message": "Invoice STK Push queued.",
            "transaction_id": str(t.transaction_id)
        }, status=202)

class CustomerListView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    def get(self, request):
        customers = Transaction.objects.filter(merchant=request.user.merchant_profile).values('phone_number').annotate(total_spent=Sum('amount', filter=models.Q(status='success')), transaction_count=Count('id'), last_payment_date=Max('created_at')).order_by('-last_payment_date')
        return Response([{"phone_number": c['phone_number'], "total_spent": c['total_spent'] or 0, "transaction_count": c['transaction_count'], "last_payment_date": c['last_payment_date']} for c in customers])

class CustomerDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    def get(self, request, phone_number):
        transactions = Transaction.objects.filter(merchant=request.user.merchant_profile, phone_number=phone_number).order_by('-created_at')
        if not transactions.exists(): return Response({"error": "Customer not found"}, status=404)
        return Response({"phone_number": phone_number, "total_spent": transactions.filter(status='success').aggregate(Sum('amount'))['amount__sum'] or 0, "transactions": [{"id": str(t.transaction_id), "amount": t.amount, "reference": t.account_reference, "status": t.status, "receipt": t.mpesa_receipt_number, "date": t.created_at} for t in transactions]})

class TeamMemberListCreateView(generics.ListCreateAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = TeamMemberSerializer
    def get_queryset(self): return TeamMember.objects.filter(merchant=self.request.user.merchant_profile).order_by('-invited_at')
    def perform_create(self, serializer): serializer.save(merchant=self.request.user.merchant_profile)

class TeamMemberDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = TeamMemberSerializer
    def get_queryset(self): return TeamMember.objects.filter(merchant=self.request.user.merchant_profile)

# --- ADMIN ---
class AdminPlatformStatsView(APIView):
    permission_classes = (permissions.IsAuthenticated, IsPlatformAdmin)
    def get(self, request):
        recent = MerchantProfile.objects.order_by('-created_at')[:5]
        return Response({
            "total_merchants": MerchantProfile.objects.count(),
            "active_merchants": MerchantProfile.objects.filter(is_active=True).count(),
            "total_transactions": Transaction.objects.count(),
            "successful_transactions": Transaction.objects.filter(status='success').count(),
            "total_volume": Transaction.objects.filter(status='success').aggregate(Sum('amount'))['amount__sum'] or 0,
            "recent_merchants": [{"id": m.id, "business_name": m.business_name, "email": m.user.email, "is_active": m.is_active, "created_at": m.created_at} for m in recent]
        })

class AdminMerchantListView(APIView):
    permission_classes = (permissions.IsAuthenticated, IsPlatformAdmin)
    def get(self, request):
        return Response([{"id": m.id, "business_name": m.business_name, "email": m.user.email, "is_active": m.is_active, "environment_mode": m.environment_mode, "created_at": m.created_at} for m in MerchantProfile.objects.all().order_by('-created_at')])


class AdminMerchantToggleView(APIView):
    permission_classes = (permissions.IsAuthenticated, IsPlatformAdmin)
    def post(self, request, pk):
        merchant = MerchantProfile.objects.filter(id=pk).first()
        if not merchant: return Response({"error": "Merchant not found"}, status=404)
        
        if merchant.is_active:
            # Suspend
            merchant.is_active = False
            merchant.save()
            return Response({"message": "Merchant suspended"})
        else:
            # Activate + set subscription for 30 days
            from django.utils import timezone
            from datetime import timedelta
            merchant.is_active = True
            merchant.subscription_expires_at = timezone.now() + timedelta(days=30)
            merchant.save()
            return Response({"message": "Merchant activated with 30-day subscription"})


class AdminSettingsView(APIView):
    permission_classes = (permissions.IsAuthenticated, IsPlatformAdmin)

    def get(self, request):
        config, _ = PlatformConfig.objects.get_or_create(id=1)
        return Response({
            "sandbox_consumer_key": config.sandbox_consumer_key or '',
            "sandbox_consumer_secret": config.sandbox_consumer_secret or '',
            "sandbox_passkey": config.sandbox_passkey or '',
            "sandbox_shortcode": config.sandbox_shortcode or '',
            "live_consumer_key": config.live_consumer_key or '',
            "live_consumer_secret": config.live_consumer_secret or '',
            "live_passkey": config.live_passkey or '',
            "live_shortcode": config.live_shortcode or '',
            "callback_url": config.callback_url or '',
            "aggregator_mode": config.aggregator_mode,
        })

    def put(self, request):
        config, _ = PlatformConfig.objects.get_or_create(id=1)
        data = request.data
        
        config.sandbox_consumer_key = data.get('sandbox_consumer_key', config.sandbox_consumer_key)
        config.sandbox_consumer_secret = data.get('sandbox_consumer_secret', config.sandbox_consumer_secret)
        config.sandbox_passkey = data.get('sandbox_passkey', config.sandbox_passkey)
        config.sandbox_shortcode = data.get('sandbox_shortcode', config.sandbox_shortcode)
        
        config.live_consumer_key = data.get('live_consumer_key', config.live_consumer_key)
        config.live_consumer_secret = data.get('live_consumer_secret', config.live_consumer_secret)
        config.live_passkey = data.get('live_passkey', config.live_passkey)
        config.live_shortcode = data.get('live_shortcode', config.live_shortcode)
        
        config.callback_url = data.get('callback_url', config.callback_url)
        config.aggregator_mode = data.get('aggregator_mode', config.aggregator_mode)
        
        config.save()
        return Response({"message": "Platform settings saved successfully."})

class AdminBlogListCreateView(generics.ListCreateAPIView):
    permission_classes = (permissions.IsAuthenticated, IsPlatformAdmin)
    serializer_class = BlogPostSerializer
    queryset = BlogPost.objects.all().order_by('-published_at')

    def perform_create(self, serializer):
        title = serializer.validated_data.get('title')
        slug = slugify(title)
        # Ensure uniqueness
        if BlogPost.objects.filter(slug=slug).exists():
            import uuid
            slug = f"{slug}-{uuid.uuid4().hex[:4]}"
        serializer.save(slug=slug)

class AdminBlogDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = (permissions.IsAuthenticated, IsPlatformAdmin)
    serializer_class = BlogPostSerializer
    queryset = BlogPost.objects.all()

# --- PUBLIC BLOG VIEWS ---
class PublicBlogListView(generics.ListAPIView):
    permission_classes = (permissions.AllowAny,)
    authentication_classes = []
    serializer_class = BlogPostSerializer
    queryset = BlogPost.objects.filter(is_published=True).order_by('-published_at')

class PublicBlogDetailView(generics.RetrieveAPIView):
    permission_classes = (permissions.AllowAny,)
    authentication_classes = []
    serializer_class = BlogPostSerializer
    lookup_field = 'slug'
    queryset = BlogPost.objects.filter(is_published=True)

class AdminTransactionListView(APIView):
    permission_classes = (permissions.IsAuthenticated, IsPlatformAdmin)

    def get(self, request):
        # Get all transactions across all merchants
        transactions = Transaction.objects.all().order_by('-created_at')[:100] # Last 100
        
        data = [{
            "id": str(t.transaction_id),
            "merchant_name": t.merchant.business_name,
            "amount": t.amount,
            "phone": t.phone_number,
            "reference": t.account_reference,
            "status": t.status,
            "receipt": t.mpesa_receipt_number,
            "date": t.created_at
        } for t in transactions]
        
        return Response(data)

class AdminSubscriptionStatsView(APIView):
    permission_classes = (permissions.IsAuthenticated, IsPlatformAdmin)

    def get(self, request):
        # Example: Count merchants who have active subscriptions
        # (You'd need a Subscription model for real numbers)
        total_merchants = MerchantProfile.objects.count()
        active_merchants = MerchantProfile.objects.filter(is_active=True).count()
        
        return Response({
            "total_merchants": total_merchants,
            "active_merchants": active_merchants,
            "suspended_merchants": total_merchants - active_merchants,
            # Mock subscription revenue (replace with real data)
            "mrr": active_merchants * 100,  # KES 100 per active merchant
            "arr": active_merchants * 100 * 12
        })

from django.core.mail import send_mail

class SendTestEmailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        user = request.user
        profile = user.merchant_profile
        recipient = profile.notify_email or user.email

        try:
            send_mail(
                subject="PayWaveKE Test Email",
                message=f"Hello {profile.business_name},\n\nThis is a test email from PayWaveKE. If you received this, your email notifications are configured correctly!\n\n- The PayWaveKE Team",
                from_email=None,
                recipient_list=[recipient],
                fail_silently=False,
            )
            return Response({"message": f"Test email sent to {recipient}"})
        except Exception as e:
            return Response({"error": str(e)}, status=500)

class AdminProfileView(APIView):
    permission_classes = (permissions.IsAuthenticated, IsPlatformAdmin)

    def get(self, request):
        user = request.user
        return Response({
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
        })

    def put(self, request):
        user = request.user
        data = request.data
        if 'email' in data:
            user.email = data['email']
            user.username = data['email'] # Sync username to email
        if 'first_name' in data:
            user.first_name = data['first_name']
        if 'last_name' in data:
            user.last_name = data['last_name']
        user.save()
        return Response({"message": "Profile updated successfully."})

class AdminChangePasswordView(APIView):
    permission_classes = (permissions.IsAuthenticated, IsPlatformAdmin)

    def post(self, request):
        old_password = request.data.get('old_password')
        new_password = request.data.get('new_password')

        if not old_password or not new_password:
            return Response({"error": "Both passwords are required."}, status=400)
        if len(new_password) < 8:
            return Response({"error": "New password must be at least 8 characters."}, status=400)
        
        user = request.user
        if not user.check_password(old_password):
            return Response({"error": "Current password is incorrect."}, status=400)

        user.set_password(new_password)
        user.save()
        return Response({"message": "Password updated successfully."})

from .serializers import SiteContentSerializer

class AdminSiteContentView(APIView):
    permission_classes = (permissions.IsAuthenticated, IsPlatformAdmin)

    def get(self, request):
        contents = SiteContent.objects.all()
        if not contents.exists():
            defaults = {
                "hero_headline": "The most reliable way to collect M-Pesa payments.",
                "hero_subheadline": "Power your business with a single, developer-first API. Instantly process STK Push requests, generate payment links, and disburse funds directly to your Till.",
                
                "pricing_sandbox_name": "Sandbox",
                "pricing_sandbox_price": "Free",
                "pricing_sandbox_desc": "For testing and development.",
                "pricing_sandbox_features": """2 free test transactions
Full API access
Sandbox environment""",
                
                "pricing_standard_name": "Standard",
                "pricing_standard_price": "KES 100",
                "pricing_standard_suffix": "/mo",
                "pricing_standard_desc": "For small businesses.",
                "pricing_standard_features": """Unlimited transactions
Direct to Till
Payment Links
Email support""",
                
                "pricing_premium_name": "Premium",
                "pricing_premium_price": "KES 500",
                "pricing_premium_suffix": "/yr",
                "pricing_premium_desc": "For growing businesses.",
                "pricing_premium_features": """Everything in Standard
B2C Disbursements
Priority support
Custom settlement""",
                
                "contact_email": "support@paywaveke.com",
            }
            for k, v in defaults.items():
                SiteContent.objects.create(key=k, content=v)
            contents = SiteContent.objects.all()
            
        return Response({c.key: c.content for c in contents})

    def put(self, request):
        data = request.data
        for key, value in data.items():
            SiteContent.objects.update_or_create(key=key, defaults={'content': value})
        return Response({"message": "Site content updated successfully."})
class PublicSiteContentView(APIView):
    permission_classes = (permissions.AllowAny,)
    authentication_classes = []

    def get(self, request):
        contents = SiteContent.objects.all()
        return Response({c.key: c.content for c in contents})


class ExpireTransactionsView(APIView):
    """Public endpoint for cron jobs to trigger expiration."""
    permission_classes = ()
    authentication_classes = []

    def post(self, request):
        # Optional: verify with a secret header
        secret = request.headers.get('X-Expire-Secret')
        if secret != 'paywave-secret-2026':
            return Response({"error": "Unauthorized"}, status=403)
        count = expire_pending_transactions()
        return Response({"expired": count})
