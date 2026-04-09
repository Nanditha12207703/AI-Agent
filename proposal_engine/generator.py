"""
proposal_engine/generator.py
-----------------------------
Converts structured proposal content to a professional PDF using ReportLab.
PDFs are saved to the server's proposal directory and NEVER exposed to clients.
"""

import asyncio
import os
from datetime import date
from pathlib import Path
from typing import Dict, Any, List

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph,
    Spacer, Table, TableStyle, HRFlowable, PageBreak,
    KeepTogether,
)
from loguru import logger

from config.settings import settings

# ── Brand Colors ──────────────────────────────────────────────────────────────
BRAND_DARK = colors.HexColor("#1A237E")       # Deep navy
BRAND_PRIMARY = colors.HexColor("#1565C0")    # Blue
BRAND_ACCENT = colors.HexColor("#0288D1")     # Light blue
BRAND_LIGHT = colors.HexColor("#E3F2FD")      # Very light blue
BRAND_TEXT = colors.HexColor("#212121")       # Near black
BRAND_MUTED = colors.HexColor("#757575")      # Grey
BRAND_SUCCESS = colors.HexColor("#2E7D32")    # Green
WHITE = colors.white


class ProposalPDFGenerator:
    """Generates professional proposal PDFs from structured content dicts."""

    def __init__(self):
        self.output_dir = Path(settings.proposal_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._styles = self._build_styles()

    # ── Public API ────────────────────────────────────────────────────────────

    async def generate(
        self,
        content: Dict[str, Any],
        requirements: Dict[str, Any],
        filename: str,
    ) -> str:
        """
        Generate PDF asynchronously.
        Returns full path to saved PDF.
        """
        loop = asyncio.get_event_loop()
        path = await loop.run_in_executor(
            None, self._build_pdf, content, requirements, filename
        )
        return path

    # ── PDF Construction ──────────────────────────────────────────────────────

    def _build_pdf(
        self,
        content: Dict[str, Any],
        requirements: Dict[str, Any],
        filename: str,
    ) -> str:
        output_path = str(self.output_dir / filename)
        styles = self._styles
        meta = content.get("metadata", {})
        company = meta.get("company_name", "Valued Client")
        version = meta.get("version", 1)
        gen_date = meta.get("generated_date", date.today().isoformat())

        # ── Document setup ────────────────────────────────────────────────────
        doc = BaseDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=2*cm, leftMargin=2*cm,
            topMargin=2.5*cm, bottomMargin=2*cm,
            title=f"Proposal for {company}",
            author="PresalesAI Agent",
        )

        # ── Frame & Page Template ─────────────────────────────────────────────
        frame = Frame(
            doc.leftMargin, doc.bottomMargin,
            doc.width, doc.height,
            id="main_frame",
        )

        def _header_footer(canvas, doc):
            canvas.saveState()
            w, h = A4

            # Header bar
            canvas.setFillColor(BRAND_DARK)
            canvas.rect(0, h - 15*mm, w, 15*mm, fill=1, stroke=0)
            canvas.setFillColor(WHITE)
            canvas.setFont("Helvetica-Bold", 9)
            canvas.drawString(2*cm, h - 10*mm, "CONFIDENTIAL – PRESALES PROPOSAL")
            canvas.drawRightString(w - 2*cm, h - 10*mm, f"v{version} | {gen_date}")

            # Footer bar
            canvas.setFillColor(BRAND_DARK)
            canvas.rect(0, 0, w, 10*mm, fill=1, stroke=0)
            canvas.setFillColor(WHITE)
            canvas.setFont("Helvetica", 8)
            canvas.drawString(2*cm, 3*mm, f"Proposal for {company}")
            canvas.drawCentredString(w / 2, 3*mm, f"Page {doc.page}")
            canvas.drawRightString(w - 2*cm, 3*mm, "Confidential")
            canvas.restoreState()

        page_template = PageTemplate(
            id="main", frames=[frame], onPage=_header_footer
        )
        doc.addPageTemplates([page_template])

        # ── Build story ───────────────────────────────────────────────────────
        story = []
        story += self._cover_page(content, company, version, gen_date)
        story += self._executive_summary_section(content)
        story += self._client_overview_section(content, requirements)
        story += self._proposed_solution_section(content)
        story += self._zoho_ecosystem_section(content)
        story += self._zoho_architecture_section(content)
        story += self._implementation_plan_section(content)
        story += self._api_integrations_section(content)
        story += self._investment_section(content)
        story += self._why_us_section(content)
        story += self._next_steps_section(content)
        story += self._terms_section(content)

        doc.build(story)
        logger.info(f"PDF generated: {output_path}")
        return output_path

    # ── Sections ──────────────────────────────────────────────────────────────

    def _cover_page(self, content, company, version, gen_date) -> list:
        s = self._styles
        story = []
        story.append(Spacer(1, 4*cm))

        # Large company title
        story.append(Paragraph(
            f"ZOHO ECOSYSTEM SOLUTION PROPOSAL",
            s["cover_subtitle"],
        ))
        story.append(Spacer(1, 0.5*cm))
        story.append(Paragraph(f"Prepared for:", s["cover_for"]))
        story.append(Paragraph(company, s["cover_title"]))
        story.append(Spacer(1, 1*cm))

        # Meta table
        meta_data = [
            ["Proposal Version", f"Version {version}"],
            ["Date", gen_date],
            ["Status", "Confidential"],
            ["Validity", content.get("validity", "30 days")],
        ]
        meta_table = Table(meta_data, colWidths=[5*cm, 10*cm])
        meta_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), BRAND_LIGHT),
            ("TEXTCOLOR", (0, 0), (0, -1), BRAND_DARK),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("PADDING", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ]))
        story.append(meta_table)
        story.append(PageBreak())
        return story

    def _executive_summary_section(self, content) -> list:
        s = self._styles
        story = [
            Paragraph("EXECUTIVE SUMMARY", s["section_title"]),
            HRFlowable(width="100%", thickness=2, color=BRAND_PRIMARY),
            Spacer(1, 0.4*cm),
        ]
        summary = content.get("executive_summary", "")
        for para in summary.split("\n"):
            if para.strip():
                story.append(Paragraph(para.strip(), s["body"]))
                story.append(Spacer(1, 0.2*cm))
        story.append(Spacer(1, 0.5*cm))
        return story

    def _client_overview_section(self, content, requirements) -> list:
        s = self._styles
        overview = content.get("client_overview", {})
        story = [
            Paragraph("CLIENT OVERVIEW", s["section_title"]),
            HRFlowable(width="100%", thickness=2, color=BRAND_PRIMARY),
            Spacer(1, 0.4*cm),
        ]
        data = [
            ["Company", overview.get("company", "—")],
            ["Industry", overview.get("industry", requirements.get("industry", "—"))],
            ["Business Challenge", overview.get("challenge", "—")],
            ["Budget", requirements.get("budget", "—")],
            ["Timeline", requirements.get("timeline", "—")],
        ]
        if requirements.get("current_tools"):
            data.append(["Current Tools", ", ".join(requirements["current_tools"])])
        table = Table(data, colWidths=[4.5*cm, 12*cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), BRAND_LIGHT),
            ("TEXTCOLOR", (0, 0), (0, -1), BRAND_DARK),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("PADDING", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.8*cm))
        return story

    def _proposed_solution_section(self, content) -> list:
        s = self._styles
        sol = content.get("proposed_solution", {})
        story = [
            Paragraph("PROPOSED SOLUTION", s["section_title"]),
            HRFlowable(width="100%", thickness=2, color=BRAND_PRIMARY),
            Spacer(1, 0.4*cm),
            Paragraph(sol.get("overview", ""), s["body"]),
            Spacer(1, 0.4*cm),
        ]

        components = sol.get("components", [])
        if components:
            story.append(Paragraph("Solution Components", s["subsection_title"]))
            for comp in components:
                story.append(KeepTogether([
                    Paragraph(f"• {comp.get('name', '')}", s["component_name"]),
                    Paragraph(comp.get("description", ""), s["body_indent"]),
                    Paragraph(f"Benefit: {comp.get('benefit', '')}", s["benefit"]),
                    Spacer(1, 0.3*cm),
                ]))

        if sol.get("differentiators"):
            story.append(Spacer(1, 0.3*cm))
            story.append(Paragraph("Why Our Approach is Different", s["subsection_title"]))
            for d in sol["differentiators"]:
                story.append(Paragraph(f"✓  {d}", s["checkmark"]))

        story.append(Spacer(1, 0.8*cm))
        return story

    def _implementation_plan_section(self, content) -> list:
        s = self._styles
        plan = content.get("implementation_plan", {})
        story = [
            Paragraph("IMPLEMENTATION PLAN", s["section_title"]),
            HRFlowable(width="100%", thickness=2, color=BRAND_PRIMARY),
            Spacer(1, 0.4*cm),
        ]
        phases = plan.get("phases", [])
        if phases:
            headers = [["Phase", "Name", "Duration", "Key Deliverables"]]
            rows = headers + [
                [
                    p.get("phase", ""),
                    p.get("name", ""),
                    p.get("duration", ""),
                    "\n".join(p.get("deliverables", []))[:100],
                ]
                for p in phases
            ]
            table = Table(rows, colWidths=[2*cm, 5*cm, 3*cm, 6.5*cm])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), BRAND_PRIMARY),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("PADDING", (0, 0), (-1, -1), 7),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, BRAND_LIGHT]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(table)
            if plan.get("total_duration"):
                story.append(Spacer(1, 0.3*cm))
                story.append(Paragraph(
                    f"<b>Total Duration:</b> {plan['total_duration']}",
                    s["body"]
                ))
        story.append(Spacer(1, 0.8*cm))
        return story

    def _investment_section(self, content) -> list:
        s = self._styles
        inv = content.get("investment", {})
        story = [
            Paragraph("INVESTMENT", s["section_title"]),
            HRFlowable(width="100%", thickness=2, color=BRAND_PRIMARY),
            Spacer(1, 0.4*cm),
            Paragraph(inv.get("investment_summary", ""), s["body"]),
            Spacer(1, 0.4*cm),
        ]
        tiers = inv.get("tiers", [])
        if tiers:
            for tier in tiers:
                story.append(KeepTogether([
                    Paragraph(tier.get("name", ""), s["subsection_title"]),
                    Paragraph(
                        f"<b>Investment Range:</b> {tier.get('price_range', '')}",
                        s["body"]
                    ),
                    *[Paragraph(f"• {item}", s["body_indent"])
                      for item in tier.get("includes", [])],
                    Spacer(1, 0.3*cm),
                ]))

        if inv.get("roi_statement"):
            story.append(Paragraph(
                f"<b>Return on Investment:</b> {inv['roi_statement']}", s["highlight"]
            ))
        if inv.get("payment_terms"):
            story.append(Spacer(1, 0.2*cm))
            story.append(Paragraph(
                f"<b>Payment Terms:</b> {inv['payment_terms']}", s["body"]
            ))
        story.append(Spacer(1, 0.8*cm))
        return story

    def _why_us_section(self, content) -> list:
        s = self._styles
        why = content.get("why_zoho", content.get("why_us", []))
        if not why:
            return []
        story = [
            Paragraph("WHY CHOOSE US", s["section_title"]),
            HRFlowable(width="100%", thickness=2, color=BRAND_PRIMARY),
            Spacer(1, 0.4*cm),
        ]
        for item in why:
            story.append(Paragraph(f"<b>{item.get('point', '')}</b>", s["body"]))
            story.append(Paragraph(item.get("detail", ""), s["body_indent"]))
            story.append(Spacer(1, 0.2*cm))
        story.append(Spacer(1, 0.8*cm))
        return story

    def _next_steps_section(self, content) -> list:
        s = self._styles
        steps = content.get("next_steps", [])
        story = [
            Paragraph("NEXT STEPS", s["section_title"]),
            HRFlowable(width="100%", thickness=2, color=BRAND_PRIMARY),
            Spacer(1, 0.4*cm),
        ]
        if steps:
            headers = [["Step", "Action", "Owner", "Timeline"]]
            rows = headers + [
                [
                    str(step.get("step", "")),
                    step.get("action", ""),
                    step.get("owner", ""),
                    step.get("timeline", ""),
                ]
                for step in steps
            ]
            table = Table(rows, colWidths=[1.5*cm, 8*cm, 3.5*cm, 3.5*cm])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), BRAND_ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("PADDING", (0, 0), (-1, -1), 7),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, BRAND_LIGHT]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ]))
            story.append(table)
        story.append(Spacer(1, 0.8*cm))
        return story

    def _terms_section(self, content) -> list:
        s = self._styles
        terms = content.get("terms_conditions", "")
        story = [
            Paragraph("TERMS & CONDITIONS", s["section_title"]),
            HRFlowable(width="100%", thickness=2, color=BRAND_PRIMARY),
            Spacer(1, 0.4*cm),
        ]
        if terms:
            story.append(Paragraph(terms, s["muted"]))
        return story

    # ── Styles ────────────────────────────────────────────────────────────────

    def _build_styles(self) -> dict:
        base = getSampleStyleSheet()
        return {
            "cover_title": ParagraphStyle(
                "cover_title", parent=base["Title"],
                fontSize=28, textColor=BRAND_DARK,
                alignment=TA_CENTER, spaceAfter=10,
                fontName="Helvetica-Bold",
            ),
            "cover_subtitle": ParagraphStyle(
                "cover_subtitle", parent=base["Normal"],
                fontSize=14, textColor=BRAND_MUTED,
                alignment=TA_CENTER, spaceAfter=6,
                fontName="Helvetica",
            ),
            "cover_for": ParagraphStyle(
                "cover_for", parent=base["Normal"],
                fontSize=12, textColor=BRAND_MUTED,
                alignment=TA_CENTER, fontName="Helvetica",
            ),
            "section_title": ParagraphStyle(
                "section_title", parent=base["Heading1"],
                fontSize=14, textColor=BRAND_DARK,
                spaceBefore=10, spaceAfter=4,
                fontName="Helvetica-Bold",
            ),
            "subsection_title": ParagraphStyle(
                "subsection_title", parent=base["Heading2"],
                fontSize=11, textColor=BRAND_PRIMARY,
                spaceBefore=8, spaceAfter=4,
                fontName="Helvetica-Bold",
            ),
            "body": ParagraphStyle(
                "body", parent=base["Normal"],
                fontSize=10, textColor=BRAND_TEXT,
                leading=15, alignment=TA_JUSTIFY,
            ),
            "body_indent": ParagraphStyle(
                "body_indent", parent=base["Normal"],
                fontSize=10, textColor=BRAND_TEXT,
                leading=14, leftIndent=20,
            ),
            "component_name": ParagraphStyle(
                "component_name", parent=base["Normal"],
                fontSize=11, textColor=BRAND_PRIMARY,
                fontName="Helvetica-Bold",
            ),
            "benefit": ParagraphStyle(
                "benefit", parent=base["Normal"],
                fontSize=9, textColor=BRAND_SUCCESS,
                leftIndent=20, fontName="Helvetica-Oblique",
            ),
            "checkmark": ParagraphStyle(
                "checkmark", parent=base["Normal"],
                fontSize=10, textColor=BRAND_TEXT,
                leftIndent=10, spaceAfter=4,
            ),
            "highlight": ParagraphStyle(
                "highlight", parent=base["Normal"],
                fontSize=10, textColor=BRAND_SUCCESS,
                fontName="Helvetica-Bold",
            ),
            "muted": ParagraphStyle(
                "muted", parent=base["Normal"],
                fontSize=9, textColor=BRAND_MUTED,
                leading=13,
            ),
        }


    # ── NEW: Zoho Ecosystem Section ───────────────────────────────────────────

    def _zoho_ecosystem_section(self, content) -> list:
        """Renders the Zoho product ecosystem table."""
        s = self._styles
        eco = content.get("zoho_ecosystem", {})
        mapping = content.get("zoho_solution_mapping", {})

        story = [
            Paragraph("ZOHO ECOSYSTEM OVERVIEW", s["section_title"]),
            HRFlowable(width="100%", thickness=2, color=BRAND_PRIMARY),
            Spacer(1, 0.4*cm),
        ]

        # Primary apps
        primary = eco.get("primary_apps", mapping.get("recommended_products", []))
        if primary:
            story.append(Paragraph("Primary Applications", s["subsection_title"]))
            for app in primary:
                story.append(Paragraph(f"✦  {app}", s["checkmark"]))
            story.append(Spacer(1, 0.3*cm))

        # Supporting apps
        supporting = eco.get("supporting_apps", [])
        if supporting:
            story.append(Paragraph("Supporting Applications", s["subsection_title"]))
            for app in supporting:
                story.append(Paragraph(f"◆  {app}", s["body_indent"]))
            story.append(Spacer(1, 0.3*cm))

        # Integration layer
        integration = eco.get("integration_layer", "")
        if integration:
            story.append(Paragraph(
                f"<b>Integration Layer:</b> {integration}", s["highlight"]
            ))
            story.append(Spacer(1, 0.3*cm))

        # Ecosystem category map
        cat_map = mapping.get("zoho_ecosystem_map", {})
        if cat_map:
            story.append(Spacer(1, 0.3*cm))
            story.append(Paragraph("Products by Business Function", s["subsection_title"]))
            rows = [["Business Function", "Zoho Products"]]
            for category, products in cat_map.items():
                rows.append([category, ", ".join(products)])
            table = Table(rows, colWidths=[7*cm, 9.5*cm])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), BRAND_PRIMARY),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("PADDING", (0, 0), (-1, -1), 7),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, BRAND_LIGHT]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(table)

        story.append(Spacer(1, 0.8*cm))
        return story

    def _zoho_architecture_section(self, content) -> list:
        """Renders the Zoho solution architecture diagram."""
        s = self._styles
        mapping = content.get("zoho_solution_mapping", {})
        eco = content.get("zoho_ecosystem", {})

        architecture = (
            mapping.get("solution_architecture")
            or eco.get("architecture_diagram")
            or ""
        )

        if not architecture:
            return []

        story = [
            Paragraph("ZOHO SOLUTION ARCHITECTURE", s["section_title"]),
            HRFlowable(width="100%", thickness=2, color=BRAND_PRIMARY),
            Spacer(1, 0.4*cm),
        ]

        # Render architecture as monospaced text block
        from reportlab.platypus import Preformatted
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_LEFT

        arch_style = ParagraphStyle(
            "architecture",
            fontName="Courier",
            fontSize=8,
            leading=12,
            textColor=BRAND_TEXT,
            backColor=BRAND_LIGHT,
            leftIndent=10,
            rightIndent=10,
            spaceBefore=5,
            spaceAfter=5,
        )
        story.append(Preformatted(architecture, arch_style))

        # Gap solutions
        gap_solutions = mapping.get("gap_solutions", [])
        if gap_solutions:
            story.append(Spacer(1, 0.4*cm))
            story.append(Paragraph("Custom Solutions for Capability Gaps", s["subsection_title"]))
            for gap in gap_solutions:
                story.append(KeepTogether([
                    Paragraph(f"<b>Gap:</b> {gap.get('gap', '')}", s["body"]),
                    Paragraph(
                        f"<b>Solution:</b> {gap.get('solution', '')} — {gap.get('approach', '')}",
                        s["body_indent"]
                    ),
                    Spacer(1, 0.2*cm),
                ]))

        story.append(Spacer(1, 0.8*cm))
        return story

    def _api_integrations_section(self, content) -> list:
        """Renders the Zoho API integration plan."""
        s = self._styles
        api_list = content.get("api_integrations", [])
        mapping = content.get("zoho_solution_mapping", {})
        if not api_list:
            api_list = mapping.get("api_integrations", [])

        if not api_list:
            return []

        story = [
            Paragraph("ZOHO API INTEGRATION PLAN", s["section_title"]),
            HRFlowable(width="100%", thickness=2, color=BRAND_PRIMARY),
            Spacer(1, 0.4*cm),
            Paragraph(
                "The following Zoho REST APIs will be used for system integrations. "
                "Full API documentation is available at https://www.zoho.com/developer/rest-api.html",
                s["body"]
            ),
            Spacer(1, 0.4*cm),
        ]

        rows = [["Zoho Product", "API Usage", "Documentation"]]
        for api in api_list[:12]:  # Cap at 12 rows
            product = api.get("product", api.get("product", ""))
            usage = api.get("api_use", ", ".join(api.get("key_operations", [])))[:80]
            docs = api.get("endpoint", api.get("documentation", "See Zoho Developer Portal"))
            rows.append([product, usage, docs[:50]])

        table = Table(rows, colWidths=[4*cm, 7*cm, 5.5*cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_ACCENT),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("PADDING", (0, 0), (-1, -1), 6),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, BRAND_LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.8*cm))
        return story
