from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from api.models import SiteContent

class Command(BaseCommand):
    help = 'Setup superuser and seed content for Render deployment'

    def handle(self, *args, **options):
        # 1. Create superuser if it doesn't exist
        email = 'warrenmusungu3@gmail.com'
        password = 'AdminPassword123!'  # Change this to a strong password!
        
        if not User.objects.filter(email=email).exists():
            User.objects.create_superuser(username=email, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f'✅ Superuser {email} created.'))
        else:
            self.stdout.write(self.style.WARNING(f'Superuser {email} already exists.'))

        # 2. Seed SiteContent if empty
        if not SiteContent.objects.exists():
            defaults = {
                "hero_headline": "The most reliable way to collect M-Pesa payments.",
                "hero_subheadline": "Power your business with a single, developer-first API.",
                "pricing_standard_name": "Standard",
                "pricing_standard_price": "KES 100",
                "pricing_standard_suffix": "/mo",
                "pricing_standard_desc": "For small businesses.",
                "pricing_standard_features": "Unlimited transactions\nDirect to Till\nPayment Links\nEmail support",
                "pricing_premium_name": "Premium",
                "pricing_premium_price": "KES 500",
                "pricing_premium_suffix": "/yr",
                "pricing_premium_desc": "For growing businesses.",
                "pricing_premium_features": "Everything in Standard\nB2C Disbursements\nPriority support\nCustom settlement",
                "pricing_sandbox_name": "Sandbox",
                "pricing_sandbox_price": "Free",
                "pricing_sandbox_desc": "For testing and development.",
                "pricing_sandbox_features": "2 free test transactions\nFull API access\nSandbox environment",
                "contact_email": "support@paywaveke.com",
            }
            for k, v in defaults.items():
                SiteContent.objects.create(key=k, content=v)
            self.stdout.write(self.style.SUCCESS('✅ Site content seeded.'))
        else:
            self.stdout.write(self.style.WARNING('Site content already exists.'))
