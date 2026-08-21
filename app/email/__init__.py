from app.config import config
from app.email.base import EmailError, EmailSender

__all__ = ["get_email_sender", "EmailSender", "EmailError"]


def get_email_sender() -> EmailSender:
    provider = config.EMAIL_PROVIDER
    if provider == "smtp":
        from app.email.smtp_sender import SmtpSender
        return SmtpSender()
    if provider == "graph":
        from app.email.graph_sender import GraphSender
        return GraphSender()
    raise EmailError(f"Unknown EMAIL_PROVIDER: {provider!r} (expected 'smtp' or 'graph')")
