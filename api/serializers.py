from rest_framework import serializers
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.text import slugify
from rest_framework_simplejwt.tokens import RefreshToken
from .models import MerchantProfile, APIKey, SettlementAccount, Transaction, PaymentLink, Invoice, TeamMember, WebhookDelivery
import uuid

class EmailTokenObtainPairSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError({"detail": "No account found with this email."})

        if not user.check_password(password):
            raise serializers.ValidationError({"detail": "Incorrect password."})

        if not user.is_active:
            raise serializers.ValidationError({"detail": "This account is inactive."})

        refresh = RefreshToken.for_user(user)
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }

class RegisterSerializer(serializers.ModelSerializer):
    business_name = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True, min_length=8)
    class Meta:
        model = User
        fields = ('email', 'password', 'business_name')
    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A merchant with this email already exists.")
        return value
    def create(self, validated_data):
        business_name = validated_data.pop('business_name')
        user = User.objects.create_user(username=validated_data['email'], email=validated_data['email'], password=validated_data['password'])
        MerchantProfile.objects.create(user=user, business_name=business_name)
        APIKey.objects.create(merchant=user.merchant_profile, name="Default Key", environment="sandbox")
        return user



class UserSerializer(serializers.ModelSerializer):
    business_name = serializers.SerializerMethodField()
    webhook_url = serializers.SerializerMethodField()
    environment_mode = serializers.SerializerMethodField()
    notify_on_success = serializers.SerializerMethodField()
    notify_on_failure = serializers.SerializerMethodField()
    notify_email = serializers.SerializerMethodField()
    is_staff = serializers.BooleanField(read_only=True)
    is_active = serializers.SerializerMethodField()
    subscription_days_left = serializers.SerializerMethodField()
    subscription_expires_at = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ('id', 'email', 'business_name', 'webhook_url', 'environment_mode', 'notify_on_success', 'notify_on_failure', 'notify_email', 'is_staff', 'is_active', 'subscription_days_left', 'subscription_expires_at')

    def _profile(self, obj):
        return getattr(obj, 'merchant_profile', None)

    def get_business_name(self, obj):
        p = self._profile(obj)
        return p.business_name if p else "PayWaveKE Admin"

    def get_webhook_url(self, obj):
        p = self._profile(obj)
        return p.webhook_url if p else None

    def get_environment_mode(self, obj):
        p = self._profile(obj)
        return p.environment_mode if p else 'sandbox'

    def get_notify_on_success(self, obj):
        p = self._profile(obj)
        return p.notify_on_success if p else True

    def get_notify_on_failure(self, obj):
        p = self._profile(obj)
        return p.notify_on_failure if p else True

    def get_notify_email(self, obj):
        p = self._profile(obj)
        return p.notify_email if p else None

    def get_is_active(self, obj):
        p = self._profile(obj)
        return p.is_active if p else True

    def get_subscription_days_left(self, obj):
        from django.utils import timezone
        p = self._profile(obj)
        if not p or not p.subscription_expires_at:
            return None
        delta = (p.subscription_expires_at - timezone.now()).days
        return max(0, delta)

    def get_subscription_expires_at(self, obj):
        p = self._profile(obj)
        return p.subscription_expires_at if p else None

    def update(self, instance, validated_data):
        profile = getattr(instance, 'merchant_profile', None)
        if not profile:
            return super().update(instance, validated_data)
            
        # Manually handle profile fields since they are SerializerMethodFields now
        request = self.context.get('request')
        data = request.data if request else {}
        
        if 'business_name' in data: profile.business_name = data['business_name']
        if 'webhook_url' in data: profile.webhook_url = data['webhook_url']
        if 'environment_mode' in data: profile.environment_mode = data['environment_mode']
        if 'notify_on_success' in data: profile.notify_on_success = data['notify_on_success']
        if 'notify_on_failure' in data: profile.notify_on_failure = data['notify_on_failure']
        if 'notify_email' in data: profile.notify_email = data['notify_email']
        
        profile.save()
        return instance

class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)
    def validate_old_password(self, value):
        if not self.context['request'].user.check_password(value):
            raise serializers.ValidationError("Your current password is incorrect.")
        return value
    def save(self, **kwargs):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user

class APIKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = APIKey
        fields = ('id', 'name', 'public_key', 'secret_key', 'environment', 'is_active', 'created_at')

class SettlementSerializer(serializers.ModelSerializer):
    class Meta:
        model = SettlementAccount
        fields = ('id', 'account_type', 'shortcode', 'account_number', 'created_at')
    def validate_shortcode(self, value):
        if not value.isdigit(): raise serializers.ValidationError("Shortcode must contain only numbers.")
        return value

class PaymentLinkSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, coerce_to_string=False)
    is_expired = serializers.BooleanField(read_only=True)
    class Meta:
        model = PaymentLink
        fields = ('id', 'link_id', 'slug', 'title', 'amount', 'description', 'is_active', 'is_expired', 'expires_at', 'created_at')
        read_only_fields = ('id', 'link_id', 'slug', 'created_at')
    def create(self, validated_data):
        merchant = validated_data['merchant']
        base_slug = slugify(f"{merchant.business_name}-{validated_data['title']}")
        validated_data['slug'] = f"{base_slug}-{uuid.uuid4().hex[:4]}"
        validated_data['link_id'] = str(uuid.uuid4())[:8]
        return super().create(validated_data)

class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ('id', 'invoice_number', 'customer_name', 'customer_phone', 'amount', 'description', 'status', 'due_date', 'created_at')
        read_only_fields = ('id', 'invoice_number', 'created_at')
    def create(self, validated_data):
        merchant = validated_data['merchant']
        last_invoice = Invoice.objects.filter(merchant=merchant).order_by('-id').first()
        next_number = (last_invoice.id + 1) if last_invoice else 1
        validated_data['invoice_number'] = f"INV-{timezone.now().year}-{next_number:03d}"
        return super().create(validated_data)

class TeamMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamMember
        fields = ('id', 'name', 'email', 'role', 'is_active', 'invited_at')
        read_only_fields = ('id', 'invited_at')
    def validate_email(self, value):
        merchant = self.context['request'].user.merchant_profile
        if TeamMember.objects.filter(merchant=merchant, email=value).exists():
            raise serializers.ValidationError("This email has already been invited.")
        return value

class WebhookDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookDelivery
        fields = ('id', 'event_type', 'url', 'payload', 'status_code', 'response_body', 'is_success', 'attempts', 'created_at')

from .models import BlogPost

class BlogPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogPost
        fields = ('id', 'title', 'slug', 'category', 'excerpt', 'content', 'cover_image', 'is_published', 'published_at', 'updated_at')
        read_only_fields = ('id', 'slug', 'published_at', 'updated_at')

from .models import SiteContent

class SiteContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteContent
        fields = ('id', 'key', 'content')
