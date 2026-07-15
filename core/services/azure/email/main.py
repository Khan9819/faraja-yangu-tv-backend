from azure.communication.email import EmailClient
from django.conf import settings

class AzureEmailService:
    def __init__(self, is_no_reply: bool = True):
        try:
            self.endpoint = settings.AZURE_EMAIL_ENDPOINT
            self.key = settings.AZURE_EMAIL_KEY
            self.sender_address = settings.NO_REPLY_SENDER_EMAIL
            self.client = EmailClient(self.endpoint, self.key)
        except Exception as e:
            raise

    def send_email(self, recipient_email, subject, content, attachments=None):
        
        """
        Send an email using Azure Communication Services
        
        Args:
            recipient_email (str): Email address of the recipient
            subject (str): Subject of the email
            content (str): HTML content of the email
            attachments (list, optional): List of attachment objects with name and content
        
        Returns:
            dict: Response containing success status and message
        """
        
        try:
            message = {
                "senderAddress": self.sender_address,
                "recipients": {
                    "to": [{"address": recipient_email}]
                },
                "content": {
                    "subject": subject,
                    "html": content
                }
            }

            # Add attachments if provided
            if attachments:
                message["attachments"] = []
                for attachment in attachments:
                    message["attachments"].append({
                        "name": attachment.get("name"),
                        "contentType": "application/octet-stream",
                        "contentInBase64": attachment.get("content")
                    })

            # Send the email
            poller = self.client.begin_send(message)
            result = poller.result()

            return {
                "success": True,
                "message": "Email sent successfully",
                "message_id": result.get('id', None)
            }

        except Exception as e:
            error_message = f"Failed to send email to {recipient_email}: {str(e)}"
            return {
                "success": False,
                "message": error_message
            }

    def send_bulk_email(self, recipients, subject, content, attachments=None):
        """
        Send bulk emails using Azure Communication Services
        
        Args:
            recipients (list): List of recipient email addresses
            subject (str): Subject of the email
            content (str): HTML content of the email
            attachments (list, optional): List of attachment objects with name and content
        
        Returns:
            dict: Response containing success status and results for each recipient
        """
        results = []
        for recipient in recipients:
            result = self.send_email(recipient, subject, content, attachments)
            results.append({
                "recipient": recipient,
                "success": result["success"],
                "message": result["message"]
            })

        return {
            "success": True,
            "results": results
        }

    def send_template_email(self, recipient_email, template_id, template_data, attachments=None):
        """
        Send a templated email using Azure Communication Services
        
        Args:
            recipient_email (str): Email address of the recipient
            template_id (str): ID of the email template
            template_data (dict): Data to populate the template
            attachments (list, optional): List of attachment objects with name and content
        
        Returns:
            dict: Response containing success status and message
        """
        try:
            # Get template from database or settings
            template = self._get_template(template_id)
            if not template:
                raise ValueError(f"Template with ID {template_id} not found")

            # Replace template variables with actual data
            content = template["content"]
            for key, value in template_data.items():
                content = content.replace(f"{{{key}}}", str(value))

            return self.send_email(
                recipient_email=recipient_email,
                subject=template["subject"],
                content=content,
                attachments=attachments
            )

        except Exception as e:
            error_message = f"Failed to send template email to {recipient_email}: {str(e)}"
            return {
                "success": False,
                "message": error_message
            }

    def _get_template(self, template_id):
        """
        Get email template from database or settings
        
        Args:
            template_id (str): ID of the template to retrieve
        
        Returns:
            dict: Template data containing subject and content
        """
        try:
            # Implementation depends on where templates are stored
            # This is a placeholder - implement based on your storage solution
            from campaign.models import EmailTemplate
            template = EmailTemplate.objects.filter(id=template_id).values().first()
            if template:
                return {
                    "subject": template["subject"],
                    "content": template["content"]
                }
            return None
        except Exception as e:
            return None

# Create a singleton instance
email_service = AzureEmailService()

def send_email(to_email, subject, content, attachments=None):
    """
    Wrapper function to send an email using Azure Communication Services
    
    Args:
        to_email (str): Recipient email address
        subject (str): Email subject
        content (str): HTML content of the email
        attachments (list, optional): List of attachment objects
    
    Returns:
        dict: Response containing success status and message
    """
    return email_service.send_email(to_email, subject, content, attachments)

def send_bulk_email(recipients, subject, content, attachments=None):
    """
    Wrapper function to send bulk emails
    
    Args:
        recipients (list): List of recipient email addresses
        subject (str): Email subject
        content (str): HTML content of the email
        attachments (list, optional): List of attachment objects
    
    Returns:
        dict: Response containing success status and results for each recipient
    """
    return email_service.send_bulk_email(recipients, subject, content, attachments)

def send_template_email(to_email, template_id, template_data, attachments=None):
    """
    Wrapper function to send a templated email
    
    Args:
        to_email (str): Recipient email address
        template_id (str): ID of the email template
        template_data (dict): Data to populate the template
        attachments (list, optional): List of attachment objects
    
    Returns:
        dict: Response containing success status and message
    """
    return email_service.send_template_email(to_email, template_id, template_data, attachments)