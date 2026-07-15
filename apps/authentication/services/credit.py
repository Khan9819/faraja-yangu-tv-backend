from django.db.models import F
from django.db import transaction

from apps.authentication.models import User


class UserCreditService:
    
    DEDUCT_FROM_DOWNLOAD = 30
    GAIN_FROM_AD = 10
    GAIN_FROM_INITIAL_REGISTRATION = 90
    MAXIMUM_VIDEO_DOWNLOADS = 5
    
    
    def __init__(self, user: User):
        self.user = user
        self.profile = user.profile
        
    def get_credit(self):
        self.profile.refresh_from_db(fields=['credit_accumulation'])
        return self.profile.credit_accumulation
    
    def add_credit(self, amount):
        with transaction.atomic():
            from apps.authentication.models import Profile
            Profile.objects.select_for_update().filter(pk=self.profile.pk).update(
                credit_accumulation=F('credit_accumulation') + amount
            )
            self.profile.refresh_from_db(fields=['credit_accumulation'])
        
    def remove_credit(self, amount):
        with transaction.atomic():
            from apps.authentication.models import Profile
            Profile.objects.select_for_update().filter(pk=self.profile.pk).update(
                credit_accumulation=F('credit_accumulation') - amount
            )
            self.profile.refresh_from_db(fields=['credit_accumulation'])
        
    def reset_credit(self) -> bool:
        with transaction.atomic():
            from apps.authentication.models import Profile
            Profile.objects.select_for_update().filter(pk=self.profile.pk).update(credit_accumulation=0)
            self.profile.refresh_from_db(fields=['credit_accumulation'])
        return True
        
    def is_credit_sufficient(self, amount) -> bool:
        self.profile.refresh_from_db(fields=['credit_accumulation'])
        return self.profile.credit_accumulation >= amount
    
    def gain_from_ad(self) -> int:
        # This method returns amount of credits gained from watching an ad
        self.add_credit(self.GAIN_FROM_AD)
        return self.GAIN_FROM_AD
        
    def gain_from_initial_registration(self) -> int:
        # This method returns amount of credits gained from initial registration
        self.add_credit(self.GAIN_FROM_INITIAL_REGISTRATION)
        return self.GAIN_FROM_INITIAL_REGISTRATION
        
    def deduct_from_download(self) -> int:
        # This method returns amount of credits deducted from downloading a video
        self.remove_credit(self.DEDUCT_FROM_DOWNLOAD)
        return self.DEDUCT_FROM_DOWNLOAD
    
    def get_balance(self) -> int:
        """Return the current credit balance after refreshing from DB."""
        self.profile.refresh_from_db(fields=['credit_accumulation'])
        return self.profile.credit_accumulation