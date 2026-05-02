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
