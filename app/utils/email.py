"""
Email service utilities for authentication
Uses Resend as the primary email provider with SMTP fallback
"""
import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

# Try importing email providers
RESEND_AVAILABLE = False
MAILGUN_AVAILABLE = False

try:
    import resend
    RESEND_AVAILABLE = True
except ImportError:
    pass

try:
    import requests
    MAILGUN_AVAILABLE = True
except ImportError:
    pass

logger = logging.getLogger(__name__)

def get_email_client():
    """
    Get available email client based on configuration
    
    Tries providers in order: Resend > Mailgun > SMTP
    Returns (client_type, client) tuple or (None, None) if none available
    """
    # Try Resend first
    if RESEND_AVAILABLE:
        api_key = os.getenv("RESEND_API_KEY")
        logger.info(f"RESEND_AVAILABLE: {RESEND_AVAILABLE}, API_KEY exists: {bool(api_key)}")
        if api_key:
            try:
                resend.api_key = api_key
                logger.info("✅ Using Resend email service - SUCCESSFULLY CONFIGURED")
                return ("resend", None)
            except Exception as e:
                logger.error(f"❌ Resend initialization failed: {e}")
        else:
            logger.warning("❌ RESEND_API_KEY not found in environment variables")
    else:
        logger.warning("❌ Resend module not available (import failed)")
    
    # Try Mailgun
    if MAILGUN_AVAILABLE:
        api_key = os.getenv("MAILGUN_API_KEY")
        domain = os.getenv("MAILGUN_DOMAIN")
        if api_key and domain:
            logger.info("Using Mailgun email service")
            return ("mailgun", {"api_key": api_key, "domain": domain})
    
    # Try SMTP
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT", "587")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    
    if smtp_host and smtp_user and smtp_pass:
        logger.info("Using SMTP email service")
        return ("smtp", {
            "host": smtp_host,
            "port": int(smtp_port),
            "username": smtp_user,
            "password": smtp_pass
        })
    
    logger.warning("No email service configured. Using fallback logging.")
    logger.warning(f"Checked: RESEND_AVAILABLE={RESEND_AVAILABLE}, MAILGUN_AVAILABLE={MAILGUN_AVAILABLE}")
    logger.warning(f"RESEND_API_KEY exists: {bool(os.getenv('RESEND_API_KEY'))}")
    return (None, None)

def _send_email_with_provider(provider: str, client, from_email: str, to_email: str, to_name: str, 
                             subject: str, plain_text: str, html_content: str) -> bool:
    """
    Send email using the specified provider
    
    Args:
        provider: Email provider type (resend, mailgun, smtp)
        client: Provider-specific client object
        from_email: Sender email address
        to_email: Recipient email address
        to_name: Recipient name
        subject: Email subject
        plain_text: Plain text content
        html_content: HTML content
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        if provider == "resend":
            return _send_resend_email(client, from_email, to_email, to_name, subject, plain_text, html_content)
        elif provider == "mailgun":
            return _send_mailgun_email(client, from_email, to_email, to_name, subject, plain_text, html_content)
        elif provider == "smtp":
            return _send_smtp_email(client, from_email, to_email, to_name, subject, plain_text, html_content)
        else:
            logger.error(f"Unknown email provider: {provider}")
            return False
    except Exception as e:
        logger.error(f"Error sending email with {provider}: {e}")
        return False

def _send_resend_email(client, from_email: str, to_email: str, to_name: str, 
                      subject: str, plain_text: str, html_content: str) -> bool:
    """Send email using Resend"""
    try:
        # Use the correct Resend Python SDK syntax
        # Handle case where to_name might be empty or None
        if to_name and to_name.strip():
            to_address = f"{to_name} <{to_email}>"
        else:
            to_address = to_email
            
        params = {
            "from": f"Multivio <{from_email}>",
            "to": [to_address],
            "subject": subject,
            "html": html_content,
            "text": plain_text,
        }
        
        # Use the correct Resend API call
        email = resend.Emails.send(params)
        
        if email and email.get("id"):
            logger.info(f"Resend email sent successfully to {to_email} (ID: {email['id']})")
            return True
        else:
            logger.error(f"Resend failed to send email to {to_email}")
            return False
    except Exception as e:
        logger.error(f"Resend error: {e}")
        return False

def _send_mailgun_email(client, from_email: str, to_email: str, to_name: str, 
                       subject: str, plain_text: str, html_content: str) -> bool:
    """Send email using Mailgun"""
    try:
        url = f"https://api.mailgun.net/v3/{client['domain']}/messages"
        
        data = {
            "from": f"Multivio <{from_email}>",
            "to": f"{to_name} <{to_email}>",
            "subject": subject,
            "text": plain_text,
            "html": html_content
        }
        
        response = requests.post(
            url,
            auth=("api", client["api_key"]),
            data=data
        )
        
        if response.status_code == 200:
            logger.info(f"Mailgun email sent successfully to {to_email}")
            return True
        else:
            logger.error(f"Mailgun failed to send email to {to_email}. Status: {response.status_code}, Response: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Mailgun error: {e}")
        return False

def _send_smtp_email(client, from_email: str, to_email: str, to_name: str, 
                    subject: str, plain_text: str, html_content: str) -> bool:
    """Send email using SMTP"""
    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"Multivio <{from_email}>"
        msg['To'] = f"{to_name} <{to_email}>"
        
        # Add text and HTML parts
        part1 = MIMEText(plain_text, 'plain')
        part2 = MIMEText(html_content, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email
        server = smtplib.SMTP(client["host"], client["port"])
        server.starttls()
        server.login(client["username"], client["password"])
        server.send_message(msg)
        server.quit()
        
        logger.info(f"SMTP email sent successfully to {to_email}")
        return True
    except Exception as e:
        logger.error(f"SMTP error: {e}")
        return False

def send_verification_email(email: str, name: str, verification_url: str) -> bool:
    """
    Send email verification email to user
    
    Args:
        email: User's email address
        name: User's full name
        verification_url: URL for email verification
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        provider, client = get_email_client()
        if not provider:
            # Fallback: Log verification URL for development
            logger.info(f"Email verification URL for {email}: {verification_url}")
            return True
        
        # Get email configuration
        from_email = os.getenv("EMAIL_FROM", "noreply@multivio.com")
        
        # Create email content
        subject = "Verify your Multivio account"
        
        plain_text = f"""
Hi {name},

Welcome to Multivio! Please verify your email address to complete your registration.

Click the link below to verify your email:
{verification_url}

This link will expire in 24 hours.

If you didn't create this account, you can safely ignore this email.

Thanks,
The Multivio Team
        """.strip()
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Verify your Multivio account</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="text-align: center; margin-bottom: 30px;">
            <div style="font-size: 24px; font-weight: bold; color: #2563eb;">Multivio</div>
        </div>
        
        <div style="background: #f9fafb; padding: 30px; border-radius: 8px; margin: 20px 0;">
            <h2 style="margin-top: 0;">Verify your email address</h2>
            <p>Hi {name},</p>
            <p>Welcome to Multivio! Please verify your email address to complete your registration and start managing your social media accounts.</p>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="{verification_url}" style="display: inline-block; background: #2563eb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: 500;">Verify Email Address</a>
            </div>
            
            <p style="font-size: 14px; color: #6b7280;">
                This link will expire in 24 hours. If you didn't create this account, you can safely ignore this email.
            </p>
        </div>
        
        <div style="text-align: center; color: #6b7280; font-size: 14px; margin-top: 30px;">
            <p>© 2025 Multivio. All rights reserved.</p>
            <p>If you're having trouble with the button above, copy and paste this URL into your browser:</p>
            <p style="word-break: break-all; color: #2563eb;">{verification_url}</p>
        </div>
    </div>
</body>
</html>
        """.strip()
        
        # Send email using the appropriate provider
        return _send_email_with_provider(provider, client, from_email, email, name, subject, plain_text, html_content)
            
    except Exception as e:
        logger.error(f"Error sending verification email to {email}: {e}")
        return False

def send_password_reset_email(email: str, name: str, reset_url: str) -> bool:
    """
    Send password reset email to user
    
    Args:
        email: User's email address
        name: User's full name
        reset_url: URL for password reset
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        provider, client = get_email_client()
        if not provider:
            # Fallback: Log reset URL for development
            logger.info(f"Password reset URL for {email}: {reset_url}")
            return True
        
        # Get email configuration
        from_email = os.getenv("EMAIL_FROM", "noreply@multivio.com")
        
        # Create email content
        subject = "Reset your Multivio password"
        
        plain_text = f"""
Hi {name},

We received a request to reset your password for your Multivio account.

Click the link below to reset your password:
{reset_url}

This link will expire in 1 hour.

If you didn't request a password reset, you can safely ignore this email.

Thanks,
The Multivio Team
        """.strip()
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reset your Multivio password</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="text-align: center; margin-bottom: 30px;">
            <div style="font-size: 24px; font-weight: bold; color: #2563eb;">Multivio</div>
        </div>
        
        <div style="background: #f9fafb; padding: 30px; border-radius: 8px; margin: 20px 0;">
            <h2 style="margin-top: 0;">Reset your password</h2>
            <p>Hi {name},</p>
            <p>We received a request to reset your password for your Multivio account.</p>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="{reset_url}" style="display: inline-block; background: #dc2626; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: 500;">Reset Password</a>
            </div>
            
            <p style="font-size: 14px; color: #6b7280;">
                This link will expire in 1 hour. If you didn't request a password reset, you can safely ignore this email.
            </p>
        </div>
        
        <div style="text-align: center; color: #6b7280; font-size: 14px; margin-top: 30px;">
            <p>© 2025 Multivio. All rights reserved.</p>
            <p>If you're having trouble with the button above, copy and paste this URL into your browser:</p>
            <p style="word-break: break-all; color: #dc2626;">{reset_url}</p>
        </div>
    </div>
</body>
</html>
        """.strip()
        
        # Send email using the appropriate provider
        return _send_email_with_provider(provider, client, from_email, email, name, subject, plain_text, html_content)
            
    except Exception as e:
        logger.error(f"Error sending password reset email to {email}: {e}")
        return False

def send_welcome_email(email: str, name: str) -> bool:
    """
    Send welcome email to newly verified user
    
    Args:
        email: User's email address
        name: User's full name
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        provider, client = get_email_client()
        if not provider:
            logger.info(f"Welcome email would be sent to {email}")
            return True
        
        # Get email configuration
        from_email = os.getenv("EMAIL_FROM", "noreply@multivio.com")
        
        # Create email content
        subject = "Welcome to Multivio!"
        
        plain_text = f"""
Hi {name},

Welcome to Multivio! Your email has been verified and your account is ready to use.

Here's what you can do next:
• Connect your social media accounts
• Create and schedule your first posts
• Explore our analytics dashboard
• Set up your profile in settings

Get started: https://multivio.com/dashboard

If you have any questions, our help center is available at https://multivio.com/help

Thanks for joining us!
The Multivio Team
        """.strip()
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Welcome to Multivio!</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="text-align: center; margin-bottom: 30px;">
            <div style="font-size: 24px; font-weight: bold; color: #2563eb;">Multivio</div>
        </div>
        
        <div style="background: #f9fafb; padding: 30px; border-radius: 8px; margin: 20px 0;">
            <h2 style="margin-top: 0;">Welcome to Multivio! 🎉</h2>
            <p>Hi {name},</p>
            <p>Welcome to Multivio! Your email has been verified and your account is ready to use. We're excited to help you manage your social media presence more effectively.</p>
            
            <h3>Here's what you can do next:</h3>
            
            <div style="margin: 15px 0; padding: 15px; background: white; border-radius: 6px;">
                <strong>🔗 Connect your accounts</strong><br>
                Link your social media accounts to start managing them all in one place.
            </div>
            
            <div style="margin: 15px 0; padding: 15px; background: white; border-radius: 6px;">
                <strong>📝 Create content</strong><br>
                Use our content creation tools to craft engaging posts for multiple platforms.
            </div>
            
            <div style="margin: 15px 0; padding: 15px; background: white; border-radius: 6px;">
                <strong>📊 Track performance</strong><br>
                Monitor your social media analytics and engagement metrics.
            </div>
            
            <div style="margin: 15px 0; padding: 15px; background: white; border-radius: 6px;">
                <strong>⚙️ Customize settings</strong><br>
                Set up your profile and preferences in the settings page.
            </div>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="https://multivio.com/dashboard" style="display: inline-block; background: #10b981; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: 500; margin: 5px;">Get Started</a>
                <a href="https://multivio.com/help" style="display: inline-block; background: #6b7280; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: 500; margin: 5px;">Help Center</a>
            </div>
        </div>
        
        <div style="text-align: center; color: #6b7280; font-size: 14px; margin-top: 30px;">
            <p>© 2025 Multivio. All rights reserved.</p>
            <p>Need help? Visit our <a href="https://multivio.com/help" style="color: #2563eb;">help center</a> or contact support.</p>
        </div>
    </div>
</body>
</html>
        """.strip()
        
        # Send email using the appropriate provider
        return _send_email_with_provider(provider, client, from_email, email, name, subject, plain_text, html_content)
            
    except Exception as e:
        logger.error(f"Error sending welcome email to {email}: {e}")
        return False