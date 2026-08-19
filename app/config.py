"""
Central configuration, loaded from environment variables (.env file).
Copy .env.example to .env and fill in before first run.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _req(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}. Check your .env file.")
    return val


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


class Config:
    # --- Filesystem paths ---
    SCAN_INBOX = Path(os.getenv("SCAN_INBOX", "/srv/scans/inbox"))
    SCAN_PROCESSING = Path(os.getenv("SCAN_PROCESSING", "/srv/scans/processing"))
    SCAN_ARCHIVE = Path(os.getenv("SCAN_ARCHIVE", "/srv/scans/archive"))  # 30-day local backup
    SCAN_FAILED = Path(os.getenv("SCAN_FAILED", "/srv/scans/failed"))
    THUMBNAIL_DIR = Path(os.getenv("THUMBNAIL_DIR", "/srv/scans/thumbnails"))
    DB_PATH = Path(os.getenv("DB_PATH", "/srv/scans/dashboard.db"))

    # --- Retention ---
    RETENTION_DAYS = _int("RETENTION_DAYS", 30)

    # --- OCR / pipeline tuning ---
    OCR_JOBS = _int("OCR_JOBS", 4)  # Pi 3B has 4 cores
    OCR_LANGUAGE = os.getenv("OCR_LANGUAGE", "eng")
    BLANK_PAGE_THRESHOLD = float(os.getenv("BLANK_PAGE_THRESHOLD", "0.995"))  # % white pixels

    # --- Microsoft Graph (app registration, client credentials or delegated) ---
    GRAPH_TENANT_ID = os.getenv("GRAPH_TENANT_ID", "")
    GRAPH_CLIENT_ID = os.getenv("GRAPH_CLIENT_ID", "")
    GRAPH_CLIENT_SECRET = os.getenv("GRAPH_CLIENT_SECRET", "")
    # Delegated flow needs a refresh token cached via MSAL token cache file
    GRAPH_TOKEN_CACHE_PATH = Path(os.getenv("GRAPH_TOKEN_CACHE_PATH", "/srv/scans/msal_token_cache.json"))
    GRAPH_SCOPES = os.getenv("GRAPH_SCOPES", "Mail.Send Files.ReadWrite").split()

    # --- Email ---
    UNCLE_EMAIL = os.getenv("UNCLE_EMAIL", "")
    SEND_FROM_MAILBOX = os.getenv("SEND_FROM_MAILBOX", "")  # UPN of the mailbox sending the email

    # --- OneDrive ---
    ONEDRIVE_FOLDER_PATH = os.getenv("ONEDRIVE_FOLDER_PATH", "/Scanned Documents")

    # --- Dashboard ---
    DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    DASHBOARD_PORT = _int("DASHBOARD_PORT", 5000)

    @classmethod
    def ensure_dirs(cls):
        for d in [cls.SCAN_INBOX, cls.SCAN_PROCESSING, cls.SCAN_ARCHIVE,
                  cls.SCAN_FAILED, cls.THUMBNAIL_DIR, cls.DB_PATH.parent]:
            d.mkdir(parents=True, exist_ok=True)


config = Config()
