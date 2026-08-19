"""
Microsoft Graph integration — app-only (client credentials) auth.

Why app-only instead of delegated: this runs unattended on a Pi with no
browser and no one around to re-consent when a refresh token expires.
Client credentials + a secret (or cert) just works indefinitely with zero
babysitting.

Required Entra app registration:
  - Application permissions (admin-consented): Mail.Send, Files.ReadWrite.All
  - IMPORTANT: scope Mail.Send down with an Exchange "Application Access
    Policy" so this app can only send as SEND_FROM_MAILBOX, not any mailbox
    in the tenant. See docs/SETUP.md.
  - For OneDrive, upload goes to /users/{UNCLE_EMAIL}/drive/... — Files.ReadWrite.All
    grants access tenant-wide, so restrict via the same kind of policy if your
    tenant supports it, or accept the broader grant for a single-user tenant.
"""
import logging
import msal
import requests
from pathlib import Path
from app.config import config

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class GraphError(Exception):
    pass


def _get_token() -> str:
    app = msal.ConfidentialClientApplication(
        client_id=config.GRAPH_CLIENT_ID,
        client_credential=config.GRAPH_CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{config.GRAPH_TENANT_ID}",
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise GraphError(f"Token acquisition failed: {result.get('error_description', result)}")
    return result["access_token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}"}


def upload_to_onedrive(local_path: str, filename: str) -> str:
    """
    Uploads to config.ONEDRIVE_FOLDER_PATH in the uncle's OneDrive.
    Uses a simple PUT for files under 4MB, resumable upload session above that
    (scanned PDFs after compression are usually well under 4MB, but 15-20 page
    docs with images can exceed it).
    Returns a webUrl link to the uploaded file.
    """
    file_size = Path(local_path).stat().st_size
    remote_path = f"{config.ONEDRIVE_FOLDER_PATH.strip('/')}/{filename}"
    user = config.UNCLE_EMAIL

    if file_size <= 4 * 1024 * 1024:
        url = f"{GRAPH_BASE}/users/{user}/drive/root:/{remote_path}:/content"
        with open(local_path, "rb") as f:
            resp = requests.put(url, headers=_headers(), data=f.read())
        if resp.status_code not in (200, 201):
            raise GraphError(f"OneDrive upload failed ({resp.status_code}): {resp.text}")
        return resp.json().get("webUrl", "")

    # Resumable upload for larger files
    session_url = f"{GRAPH_BASE}/users/{user}/drive/root:/{remote_path}:/createUploadSession"
    resp = requests.post(session_url, headers=_headers(), json={
        "item": {"@microsoft.graph.conflictBehavior": "replace"}
    })
    if resp.status_code not in (200, 201):
        raise GraphError(f"Could not create upload session ({resp.status_code}): {resp.text}")
    upload_url = resp.json()["uploadUrl"]

    chunk_size = 320 * 1024 * 10  # ~3.2MB chunks, must be multiple of 320 KiB
    with open(local_path, "rb") as f:
        offset = 0
        while offset < file_size:
            chunk = f.read(chunk_size)
            chunk_end = offset + len(chunk) - 1
            headers = {
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {offset}-{chunk_end}/{file_size}",
            }
            put_resp = requests.put(upload_url, headers=headers, data=chunk)
            if put_resp.status_code not in (200, 201, 202):
                raise GraphError(f"Chunk upload failed ({put_resp.status_code}): {put_resp.text}")
            offset += len(chunk)

    return put_resp.json().get("webUrl", "")


def send_email(subject: str, body_html: str, attachment_path: str | None = None):
    """
    Sends from config.SEND_FROM_MAILBOX to config.UNCLE_EMAIL.
    Attaches the PDF directly if under 3MB (Graph inline attachment limit
    is technically higher, but we keep a safety margin); otherwise the
    OneDrive link in the email body is the delivery method.
    """
    message = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": [{"emailAddress": {"address": config.UNCLE_EMAIL}}],
        },
        "saveToSentItems": "true",
    }

    if attachment_path and Path(attachment_path).stat().st_size <= 3 * 1024 * 1024:
        import base64
        with open(attachment_path, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode()
        message["message"]["attachments"] = [{
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": Path(attachment_path).name,
            "contentBytes": content_b64,
        }]

    url = f"{GRAPH_BASE}/users/{config.SEND_FROM_MAILBOX}/sendMail"
    resp = requests.post(url, headers=_headers(), json=message)
    if resp.status_code != 202:
        raise GraphError(f"sendMail failed ({resp.status_code}): {resp.text}")
