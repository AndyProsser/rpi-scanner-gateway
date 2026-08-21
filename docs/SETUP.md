# Setup Guide — Uncle's Scan Pipeline

One-time setup, in order. Budget ~2 hours including OCR test runs.

## 1. Raspberry Pi OS base

Flash **64-bit** Raspberry Pi OS (Bookworm or later), not 32-bit. `pikepdf`,
`Pillow`, and `PyMuPDF` only publish prebuilt wheels for aarch64 — on 32-bit
armv7l, pip falls back to building them from source (pikepdf alone needs a
Rust toolchain and qpdf headers), which is slow and often fails outright on
a Pi 3B. The Pi 3B has a 64-bit-capable CPU, so this is just an OS image
choice.

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y python3-venv python3-pip samba tesseract-ocr \
    ghostscript jbig2enc git
```

`jbig2enc` isn't always packaged for ARM on Raspberry Pi OS — if `apt install jbig2enc`
fails, ocrmypdf will silently skip `--jbig2-lossy` and fall back to standard
compression. Not a blocker, just slightly bigger files.

## 2. Create the service user and directories

```bash
sudo useradd -r -s /usr/sbin/nologin scanpipeline
sudo mkdir -p /srv/scans/{inbox,processing,archive,failed,thumbnails}
sudo chown -R scanpipeline:scanpipeline /srv/scans
```

## 3. Deploy the code

```bash
sudo mkdir -p /opt/scan-pipeline
sudo chown $USER:$USER /opt/scan-pipeline
git clone <your-repo-or-copy-files-here> /opt/scan-pipeline
cd /opt/scan-pipeline
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env
# edit .env — you'll fill in the email provider values in step 6
sudo chown -R scanpipeline:scanpipeline /opt/scan-pipeline
```

## 4. Samba share (the Brother's scan target)

```bash
sudo tee -a /etc/samba/smb.conf < scripts/samba-scan-share.conf
sudo smbpasswd -a scanner        # pick a password, note it down
sudo systemctl restart smbd
```

Test from your Mac/PC before touching the Brother:
`smb://<pi-ip-or-tailscale-name>/scans` — connect as user `scanner`, confirm
you can drop a test PDF in.

## 5. Brother panel — Scan to Network Folder shortcut

On the MFP touchscreen (menu wording varies slightly by model):

1. **Settings → Network → Scan to Network Folder** (or via the web-based
   management page at the printer's IP, under Scan → Scan to FTP/Network)
2. Add a new profile:
   - **Network Folder Path:** `\\<pi-ip>\scans` (or `//<pi-ip>/scans` depending on model UI)
   - **Username:** `scanner`
   - **Password:** the one from step 4
   - **File name:** something predictable, e.g. `Scan`
   - **File type:** PDF
   - **Resolution:** 300 dpi (600dpi roughly doubles OCR time and file size for
     no real quality benefit on text documents)
   - **Color:** Black & White or Grey for contracts/disclosures — smaller
     files, faster OCR. Only use Color if he's scanning something with
     color content that matters.
3. Assign it to a **Shortcut button** on the home screen, name it something
   your uncle will recognize — "Scan to Andy" or similar.
4. Test: scan a page, confirm it lands in `/srv/scans/inbox` on the Pi.

## 6. Email provider setup

Pick one and set `EMAIL_PROVIDER` accordingly in `.env`.

### Option A — SMTP (`EMAIL_PROVIDER=smtp`)

Works for cPanel-hosted email, Gmail, Microsoft Live (personal), and Apple
iCloud Mail — same protocol, different host/port/credentials:

| Provider | SMTP_HOST | SMTP_PORT | SMTP_USERNAME |
|---|---|---|---|
| cPanel | usually `mail.yourdomain.com`, or check your host's docs/cPanel's "Email Accounts" page | `587` (STARTTLS) or `465` (SSL) — cPanel shows both | full email address |
| Gmail | `smtp.gmail.com` | `587` | full email address (needs an [app password](https://myaccount.google.com/apppasswords), not your regular password) |
| Microsoft Live (personal, not M365 tenant) | `smtp.office365.com` or `smtp-mail.outlook.com` — check your account type | `587` | full email address |
| Apple iCloud Mail | `smtp.mail.me.com` | `587` | full iCloud email + an [app-specific password](https://support.apple.com/en-us/102654) |

`SMTP_FROM_ADDRESS` is usually the same as `SMTP_USERNAME`. `RECIPIENT_EMAIL`
is whoever should get the "scan ready" notification.

Confirm the exact host/port with your provider's current documentation —
these change occasionally and the table above may drift.

### Option B — Microsoft Graph (`EMAIL_PROVIDER=graph`)

For M365 tenants with Global Admin access, using certificate auth (no
client secret to rotate/leak):

```bash
openssl req -x509 -newkey rsa:2048 -keyout graph-app.key -out graph-app.crt \
    -days 730 -nodes -subj "/CN=rpi-scanner-gateway"
openssl x509 -in graph-app.crt -noout -fingerprint -sha1
```

1. **Entra admin center → App registrations → New registration**
   - Name: e.g. `Scanner Gateway`
   - Supported account types: single tenant
2. **Certificates & secrets → Certificates → Upload certificate** — upload
   `graph-app.crt`. The `-fingerprint -sha1` output from above, with the
   colons removed, is `GRAPH_CERT_THUMBPRINT`.
3. **API permissions → Add a permission → Microsoft Graph → Application
   permissions:** `Mail.Send`, then **Grant admin consent**.
4. Copy **Application (client) ID** → `GRAPH_CLIENT_ID`, and **Directory
   (tenant) ID** → `GRAPH_TENANT_ID`.
5. Put `graph-app.key` on the Pi at the path in `GRAPH_CERT_PATH`
   (default `/opt/scan-pipeline/certs/graph-app.key`), `chmod 600`, owned
   by `scanpipeline`. **Never commit it** — it's covered by `.gitignore`.

### Lock down Mail.Send (important, Option B only)

App-only `Mail.Send` without scoping lets this app send as *any* mailbox in
the tenant. Restrict it to just the sending mailbox via Exchange Online
PowerShell:

```powershell
Connect-ExchangeOnline
New-ApplicationAccessPolicy -AppId "<GRAPH_CLIENT_ID>" `
    -PolicyScopeGroupId "scanner@yourtenant.com" `
    -AccessRight RestrictAccess `
    -Description "Scan pipeline - restrict to scanner mailbox only"
```

Set `SEND_FROM_MAILBOX` to that same mailbox.

### OneDrive backup (optional, independent of the above)

Still uses the client-secret Graph flow. If you want the local archive
copy also mirrored to OneDrive, follow the app registration steps above
but also add a client secret (**Certificates & secrets → New client
secret**) for `GRAPH_CLIENT_SECRET`, grant `Files.ReadWrite.All`, and set
`UNCLE_EMAIL` to whose OneDrive receives the upload. This will move onto
the same certificate as email sending in a future update.

## 7. Tailscale

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Authenticate against your tailnet (the one shared with your uncle and,
later, your dad's server). Note the MagicDNS name it's assigned
(e.g. `scanner-pi`) — that's what you'll use to reach the dashboard:
`http://scanner-pi:5000`.

If you want your uncle to check the simple view himself, install Tailscale
on his Mac too and share the Pi node with his account (node sharing is
included free — see Tailscale's Personal plan). Otherwise this stays
just for you.

## 8. Install and start the services

```bash
cd /opt/scan-pipeline
sudo cp systemd/*.service systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now scan-watcher.service
sudo systemctl enable --now scan-dashboard.service
sudo systemctl enable --now retention-cleanup.timer
```

Check it's alive:
```bash
sudo systemctl status scan-watcher
sudo journalctl -u scan-watcher -f     # tail logs live while testing
```

## 9. End-to-end test

1. Scan a multi-page test document (include a deliberately blank page)
   from the Brother using the shortcut button.
2. Watch `journalctl -u scan-watcher -f` — you should see it move through
   received → OCR → uploading → done.
3. Check the dashboard at `http://scanner-pi:5000`.
4. Confirm the email arrived, the attachment opens and is searchable
   (Cmd+F for a word you know is in the doc), and the OneDrive link works.
5. Check `/srv/scans/archive` has the local backup copy.

## Ongoing maintenance

- Logs: `journalctl -u scan-watcher` / `-u scan-dashboard`
- If a scan fails, it's visible on `/details` with the error message, and
  the original is preserved in `/srv/scans/failed` for reprocessing.
- Client secret expiry: Entra secrets typically max out at 24 months —
  put a reminder in your own calendar, not his.
