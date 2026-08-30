"""Alert delivery.

The delivery receipt matters as much as the alert. In a dispute the question is
not only "was the site over 95" but "was the supervisor told, when, and by what
channel". Every send returns a receipt that gets written into the ledger entry.
"""
import logging
from datetime import datetime, timezone

import httpx

from app import config

log = logging.getLogger("scorched.notify")


async def send(site, subject: str, body: str, severity: str = "action") -> dict:
    channels = []

    if config.NOTIFY_CONSOLE:
        log.warning("[%s] %s | %s", severity.upper(), subject, body)
        channels.append({"channel": "console", "status": "delivered"})

    if config.SLACK_WEBHOOK_URL:
        emoji = {"advisory": ":large_blue_circle:", "action": ":large_yellow_circle:",
                 "high_heat": ":red_circle:", "extreme": ":rotating_light:"}.get(severity, ":white_circle:")
        text = f"{emoji} *{subject}*\n{body}"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(config.SLACK_WEBHOOK_URL, json={"text": text})
            channels.append(
                {
                    "channel": "slack",
                    "status": "delivered" if r.status_code < 300 else "failed",
                    "http_status": r.status_code,
                }
            )
        except Exception as exc:  # a failed notice is itself evidence
            channels.append({"channel": "slack", "status": "failed", "error": str(exc)})

    return {
        "sent_utc": datetime.now(timezone.utc).isoformat(),
        "recipient": site.supervisor,
        "subject": subject,
        "severity": severity,
        "channels": channels,
    }
