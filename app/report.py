"""PDF compliance record.

The artefact an HSE manager hands to a claims adjuster, or a union rep hands to
a lawyer. Deliberately plain: what the temperature was, what the rule required,
who was told, and whether the record has been altered since it was written.
"""
from datetime import datetime, timedelta, timezone
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app import config, ledger
from app.rules import engine
from app.sites import require_site

INK = colors.HexColor("#171A1C")
BLUE = colors.HexColor("#23456B")
RED = colors.HexColor("#A6271F")
AMBER = colors.HexColor("#9A6600")
RULE = colors.HexColor("#C8C6BD")
MUTED = colors.HexColor("#5E625F")

SEVERITY_COLOR = {
    "extreme": RED,
    "high_heat": RED,
    "action": AMBER,
    "advisory": BLUE,
    "baseline": MUTED,
}


def _styles():
    ss = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=ss["Title"], fontName="Helvetica-Bold",
                                fontSize=17, textColor=INK, alignment=TA_LEFT, spaceAfter=2),
        "sub": ParagraphStyle("s", parent=ss["Normal"], fontName="Helvetica",
                              fontSize=9.5, textColor=MUTED, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                             fontSize=10.5, textColor=INK, spaceBefore=14, spaceAfter=5),
        "body": ParagraphStyle("b", parent=ss["Normal"], fontName="Helvetica",
                               fontSize=9, textColor=INK, leading=12.5),
        "small": ParagraphStyle("sm", parent=ss["Normal"], fontName="Helvetica",
                                fontSize=7.6, textColor=MUTED, leading=10),
        "mono": ParagraphStyle("m", parent=ss["Normal"], fontName="Courier",
                               fontSize=7.2, textColor=MUTED, leading=9.5),
        "banner": ParagraphStyle("ban", parent=ss["Normal"], fontName="Helvetica-Bold",
                                 fontSize=9, textColor=colors.white, leading=13),
    }


def _kv_table(rows, widths=(1.5 * inch, 4.9 * inch)):
    t = Table(rows, colWidths=list(widths))
    t.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 8.5),
                ("FONT", (1, 0), (1, -1), "Helvetica", 8.5),
                ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
                ("TEXTCOLOR", (1, 0), (1, -1), INK),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return t


def build_report(site_id: str, days: int = 7) -> BytesIO:
    site = require_site(site_id)
    pack = engine.load_pack(site.jurisdiction)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    entries = ledger.entries_between(site.id, start.isoformat(), end.isoformat())
    chain = ledger.verify()
    st = _styles()

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        title=f"Heat compliance record - {site.name}",
    )
    story = []

    story.append(Paragraph("Heat-safety compliance record", st["title"]))
    story.append(
        Paragraph(
            f"{site.name} &nbsp;|&nbsp; {site.operator} &nbsp;|&nbsp; "
            f"{start:%d %b %Y} to {end:%d %b %Y} (UTC)",
            st["sub"],
        )
    )

    if config.is_replay():
        banner = Table(
            [[Paragraph(
                "REPLAY MODE. Every temperature in this document is synthetic and was generated "
                "offline for demonstration. This is not a record of any real worksite.", st["banner"])]],
            colWidths=[6.4 * inch],
        )
        banner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), RED),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story += [banner, Spacer(1, 12)]

    story.append(Paragraph("Site and applicable standard", st["h2"]))
    story.append(_kv_table([
        ["Worksite", f"{site.name}"],
        ["Coordinates", f"{site.lat:.4f}, {site.lng:.4f}"],
        ["Operator", site.operator],
        ["Industry", site.industry.replace("_", " ")],
        ["Required clothing", site.clothing.replace("_", " ")],
        ["Shift", f"{site.shift_start} to {site.shift_end} local ({site.timezone})"],
        ["Jurisdiction", pack["name"]],
        ["Standard", pack.get("citation", "")],
        ["Triggering metric", pack.get("metric", "temp_f")],
        ["Temperature source", "FortyGuard Temperature API, 2 m above ground, worksite polygon"
            if not config.is_replay() else "Synthetic replay generator (no live data)"],
    ]))

    story.append(Paragraph("Record integrity", st["h2"]))
    verdict = ("Chain intact. Every entry hashes to its recorded value and links to its predecessor."
               if chain["ok"] else
               f"CHAIN BROKEN at entry {chain['broken_at_seq']}. {chain['reason']}")
    story.append(_kv_table([
        ["Entries in chain", str(chain["entries"])],
        ["Verification", verdict],
        ["Chain head", chain["head"]["hash"]],
        ["Generated", f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC"],
    ]))

    story.append(Paragraph(f"Logged events, {days} day window", st["h2"]))
    if not entries:
        story.append(Paragraph(
            "No entries in this window. If the monitor was running, this means no threshold "
            "state changed and no heartbeat was due. If the monitor was not running, the "
            "absence of entries is not evidence of compliance.", st["body"]))
    else:
        data = [["Seq", "Time (UTC)", "Event", "Temp", "Detail"]]
        rowcolors = []
        for e in entries:
            p = e["payload"]
            temp = p.get("temp_f") or p.get("current_f") or p.get("observed_temp_f") or ""
            detail = ""
            if e["kind"] == "STATUS_CHANGE":
                detail = f"{p.get('from')} to {p.get('to')}"
                reqs = p.get("requirements_now_in_force") or []
                if reqs:
                    detail += ". Required: " + reqs[0]
            elif e["kind"] == "PRE_BREACH":
                f = p.get("forecast", {})
                detail = (f"{f.get('name')} forecast at {f.get('forecast_f')}F, "
                          f"{int(f.get('lead_minutes', 0) / 60)}h lead, trigger {f.get('trigger_f')}F")
            elif e["kind"] == "NOTICE_SENT":
                r = p.get("receipt", {})
                chans = ", ".join(f"{c['channel']}:{c['status']}" for c in r.get("channels", []))
                detail = f"to {r.get('recipient')} via {chans}"
            elif e["kind"] == "COVERAGE_GAP":
                detail = f"needs {p.get('missing_input')}, not derivable from temperature alone"
            elif e["kind"] == "READING":
                detail = f"status {p.get('status')}"
            data.append([
                str(e["seq"]),
                e["ts_utc"][:19].replace("T", " "),
                e["kind"].replace("_", " ").title(),
                f"{temp}F" if temp != "" else "",
                Paragraph(detail, st["small"]),
            ])
            rowcolors.append(SEVERITY_COLOR.get(e.get("severity") or "", MUTED))

        t = Table(data, colWidths=[0.4 * inch, 1.15 * inch, 1.0 * inch, 0.5 * inch, 3.35 * inch],
                  repeatRows=1)
        style = [
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.6),
            ("FONT", (0, 1), (-1, -1), "Helvetica", 7.6),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, 0), (-1, 0), INK),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        for i, c in enumerate(rowcolors, start=1):
            style.append(("TEXTCOLOR", (2, i), (2, i), c))
        t.setStyle(TableStyle(style))
        story.append(t)

    story.append(PageBreak())
    story.append(Paragraph("Hash chain", st["h2"]))
    story.append(Paragraph(
        "Each entry commits to the one before it. Altering or removing any entry changes its hash "
        "and breaks every link after it, which verification reports by sequence number.", st["body"]))
    story.append(Spacer(1, 6))
    for e in entries[:40]:
        story.append(Paragraph(
            f"#{e['seq']} {e['kind']}<br/>prev {e['prev_hash'][:32]}...<br/>this {e['entry_hash'][:32]}...",
            st["mono"]))
        story.append(Spacer(1, 3))

    story.append(Paragraph("Scope and limits of this document", st["h2"]))
    story.append(Paragraph(
        "This is contemporaneous, independently generated documentation of measured worksite "
        "temperature against the cited standard, together with a record of the notices issued at "
        "the time. It is not a legal opinion, not a certification of compliance, and not a "
        "determination that any requirement was or was not met in practice. It records what the "
        "temperature was and what was communicated. Whether shade was actually erected, whether "
        "breaks were actually taken, and whether the standard was met remain questions of fact "
        "for the parties and any competent authority. Storage is a local hash-chained ledger, "
        "which is tamper-evident rather than tamper-proof: it detects modification of an entry, "
        "it does not prevent replacement of the whole file. Anchoring the chain head to an "
        "external timestamping service would close that gap.", st["small"]))

    if config.is_replay():
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            "This particular document was produced in replay mode from synthetic data and has no "
            "evidentiary value whatsoever.", st["small"]))

    doc.build(story)
    buf.seek(0)
    return buf
