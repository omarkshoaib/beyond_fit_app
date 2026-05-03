import os
import smtplib
import logging
from email.message import EmailMessage

class EmailService:
    @staticmethod
    def send_plan(recipient_email: str, pdf_bytes: bytes, client_name: str = "Client"):
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_email = os.getenv("SMTP_EMAIL")
        smtp_pwd = os.getenv("SMTP_PASSWORD")
        
        if not smtp_email or not smtp_pwd:
            logging.error("Missing SMTP credentials in .env! Cannot send email.")
            return False

        msg = EmailMessage()
        msg['Subject'] = "Your Custom Training Program from Coach Shoaib 🏋️"
        msg['From'] = smtp_email
        msg['To'] = recipient_email
        
        body = f"Hello {client_name},\n\nAttached is your custom training protocol constructed by the Deterministic Coaching Engine.\n\nGood luck,\nCoach Shoaib"
        
        msg.set_content(body)
        
        # Attach PDF
        msg.add_attachment(
            pdf_bytes,
            maintype='application',
            subtype='pdf',
            filename='workout_plan.pdf'
        )
        
        # Send
        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                server.login(smtp_email, smtp_pwd)
                server.send_message(msg)
            logging.info(f"Email successfully dispatched to {recipient_email}")
            return True
        except (smtplib.SMTPException, OSError, ValueError) as e:
            logging.error(f"Failed to send email to {recipient_email}: {e}", exc_info=True)
            return False

    @staticmethod
    def send_verification(recipient_email: str, verify_token: str, client_name: str = "Athlete") -> bool:
        """Send an email verification link to a freshly registered user."""
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_email = os.getenv("SMTP_EMAIL") or os.getenv("SMTP_USER")
        smtp_pwd = os.getenv("SMTP_PASSWORD")
        app_base_url = os.getenv("APP_BASE_URL", "https://beyondfit.app")

        if not smtp_email or not smtp_pwd:
            logging.error("Missing SMTP credentials — cannot send verify email")
            return False

        verify_url = f"{app_base_url}/verify?token={verify_token}"

        msg = EmailMessage()
        msg["Subject"] = "Beyond Fit — verify your email"
        msg["From"] = smtp_email
        msg["To"] = recipient_email
        msg.set_content(
            f"Hi {client_name},\n\n"
            f"Welcome to Beyond Fit. Confirm your email address within 48 hours:\n\n"
            f"{verify_url}\n\n"
            f"If you didn't create an account, you can ignore this email.\n\n"
            f"— Beyond Fit"
        )

        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                server.login(smtp_email, smtp_pwd)
                server.send_message(msg)
            logging.info(f"Verification email sent to {recipient_email}")
            return True
        except (smtplib.SMTPException, OSError, ValueError) as e:
            logging.error(f"Failed to send verify email to {recipient_email}: {e}", exc_info=True)
            return False

    @staticmethod
    def send_password_reset(recipient_email: str, reset_token: str, client_name: str = "Athlete") -> bool:
        """Send a password-reset email with a deep-link to the mobile app."""
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_email = os.getenv("SMTP_EMAIL") or os.getenv("SMTP_USER")
        smtp_pwd = os.getenv("SMTP_PASSWORD")
        app_base_url = os.getenv("APP_BASE_URL", "https://beyondfit.app")

        if not smtp_email or not smtp_pwd:
            logging.error("Missing SMTP credentials — cannot send reset email")
            return False

        reset_url = f"{app_base_url}/reset?token={reset_token}"

        msg = EmailMessage()
        msg["Subject"] = "Beyond Fit — reset your password"
        msg["From"] = smtp_email
        msg["To"] = recipient_email
        msg.set_content(
            f"Hi {client_name},\n\n"
            f"Use this link within 30 minutes to set a new password:\n\n"
            f"{reset_url}\n\n"
            f"If you didn't request this, ignore the email and your password stays the same.\n\n"
            f"— Beyond Fit"
        )

        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                server.login(smtp_email, smtp_pwd)
                server.send_message(msg)
            logging.info(f"Password reset email sent to {recipient_email}")
            return True
        except (smtplib.SMTPException, OSError, ValueError) as e:
            logging.error(f"Failed to send reset email to {recipient_email}: {e}", exc_info=True)
            return False
