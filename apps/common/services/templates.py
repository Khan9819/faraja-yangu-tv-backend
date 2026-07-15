from enum import Enum
from pathlib import Path


class EmailTemplateType(Enum):
    """Enum for available email template types."""
    OTP = "otp"
    PASSWORD_RESET = "password_reset"
    PASSWORD_CHANGED = "password_changed"
    WELCOME = "welcome"
    EMAIL_VERIFICATION = "email_verification"
    INVITATION = "invitation"
    ACCOUNT_DEACTIVATED = "account_deactivated"
    LOGIN_ALERT = "login_alert"


class EmailTemplates:
    """Service for loading and rendering email templates without Django templating."""
    
    BASE_TEMPLATE = "base_email.html"
    TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
    
    # Map template types to their file names
    TEMPLATE_FILES = {
        EmailTemplateType.OTP: "otp_email_raw.html",
        EmailTemplateType.PASSWORD_RESET: "password_reset_email_raw.html",
        EmailTemplateType.PASSWORD_CHANGED: "password_has_been_changed.html",
        EmailTemplateType.WELCOME: "welcome.html",
        EmailTemplateType.EMAIL_VERIFICATION: "email_verification.html",
        EmailTemplateType.INVITATION: "youve_been_invited.html",
        EmailTemplateType.ACCOUNT_DEACTIVATED: "account_deactivated.html",
        EmailTemplateType.LOGIN_ALERT: "login_alert.html",
    }
    
    def get_template(self, template_type: EmailTemplateType, **kwargs) -> str:
        """
        Load and render an email template with the given context.
        
        Args:
            template_type: The type of email template to load
            **kwargs: Key-value pairs to replace in the template (e.g., first_name="John", otp_code=123456)
        
        Returns:
            Fully rendered HTML email as a string
        """
        
        # Get the template file name for this type
        template_file = self.TEMPLATE_FILES.get(template_type)
        if not template_file:
            raise ValueError(f"No template file mapped for {template_type}")
        
        # Build full path to the template
        base_template_path = self.TEMPLATES_DIR / 'base_email.html'
        template_path = self.TEMPLATES_DIR / template_file
        
        if not base_template_path.exists():
            raise FileNotFoundError(f"Base Template file not found: {base_template_path}")
        
        if not template_path.exists():
            raise FileNotFoundError(f"Template file not found: {template_path}")
        
        # Read the base template content
        with open(base_template_path, 'r', encoding='utf-8') as file:
            base_content = file.read()
        
        # Read the template content
        with open(template_path, 'r', encoding='utf-8') as file:
            content = file.read()
        
        # Replace placeholders with actual values
        # Support both {key} and {{key}} style placeholders
        for key, value in kwargs.items():
            content = content.replace(f"{{{key}}}", str(value))
            content = content.replace(f"{{{{{key}}}}}", str(value))
            
        content = base_content.replace('--content--', content)
        
        with open('test_email.html', 'w+') as file:
            file.write(content)
        
        return content