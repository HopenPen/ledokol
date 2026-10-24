"""SMTP-адаптер. Учётные данные и ссылки подтверждения не записываются в лог."""
import logging
import smtplib
import ssl
from email.message import EmailMessage
from html import escape

from app.core.config import get_settings
from app.services.registration import EmailDeliveryError

log = logging.getLogger("cashflow.email")


class SmtpVerificationMailer:
    def send_verification(self, recipient: str, link: str, ttl_minutes: int) -> None:
        settings = get_settings()
        if not settings.smtp_host or settings.smtp_from.endswith("@example.invalid"):
            raise EmailDeliveryError
        message = EmailMessage()
        message["Subject"] = "Подтвердите email — Деньги вперёд"
        message["From"], message["To"] = settings.smtp_from, recipient
        message.set_content(f"Подтвердите email для входа в приложение «Деньги вперёд»:\n\n{link}\n\n"
                            f"Ссылка действует {ttl_minutes} мин. Если вы не регистрировались, проигнорируйте письмо.")
        message.add_alternative(f'<h1>Подтвердите email</h1><p>Вы создали аккаунт в приложении «Деньги вперёд».</p>'
                                f'<p><a href="{escape(link, quote=True)}">Подтвердить email</a></p>'
                                f'<p>Ссылка действует {ttl_minutes} мин. Если вы не регистрировались, проигнорируйте письмо.</p>',
                                subtype="html")
        context = ssl.create_default_context()
        try:
            client = (smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10, context=context)
                      if settings.smtp_security == "ssl" else smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10))
            with client:
                if settings.smtp_security == "starttls":
                    client.starttls(context=context)
                if settings.smtp_user:
                    client.login(settings.smtp_user, settings.smtp_password.get_secret_value() if settings.smtp_password else "")
                client.send_message(message)
        except (smtplib.SMTPException, OSError, ValueError) as exc:
            log.warning("verification_delivery_failed: %s", type(exc).__name__)
            raise EmailDeliveryError from None
