import random
from pathlib import Path

from apps.authentication.models import User
from core.services.azure.email import AzureEmailService
from apps.common.services.templates import EmailTemplates, EmailTemplateType


class OTPService:
    """Service for handling OTP (One-Time Password) operations."""
    
    otp_length = 6
    otp_expiry_minutes = 10

    def __init__(self, otp_length: int = 6, otp_expiry_minutes: int = 10) -> None:
        self.otp_length = otp_length
        self.otp_expiry_minutes = otp_expiry_minutes

    def _generate_otp(self, length: int | None = None) -> int:
        """Generate a numeric OTP of the configured length."""

        if length is None:
            length = self.otp_length

        if length <= 0:
            raise ValueError("OTP length must be a positive integer")

        lower_bound = 10 ** (length - 1)
        upper_bound = (10 ** length) - 1
        return random.randint(lower_bound, upper_bound)

    def send_otp_email(self, user: User) -> int:
        """Generate an OTP, send it to the user's email, and return the OTP.

        Persistence and verification of the OTP should be handled by the caller
        (e.g., storing it in a model or cache with an expiry based on
        ``self.otp_expiry_minutes``).
        """

        otp_code = self._generate_otp()

        # Use EmailTemplates service to load and render the template
        email_templates = EmailTemplates()
        html_content = email_templates.get_template(
            EmailTemplateType.OTP,
            first_name=getattr(user, "first_name", ""),
            otp_code=otp_code,
            otp_expiry_minutes=self.otp_expiry_minutes,
        )

        azure = AzureEmailService(is_no_reply=True)
        azure.send_email(
            recipient_email=user.email,
            subject="FarajaYanguTv OTP",
            content=html_content,
        )

        return otp_code