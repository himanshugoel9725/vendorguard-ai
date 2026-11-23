"""Render composed pages as a byte-reproducible PDF (core Helvetica, fixed date and file ID)."""

from fpdf import FPDF

from vendorguard.config_models.core import SamplesSettings
from vendorguard.errors import ConfigError
from vendorguard.eval.sample_gen.layout import wrap_lines
from vendorguard.eval.sample_gen.models import Block
from vendorguard.utils.hashing import sha256_text

FILE_ID_CHARS = 32
FOOTER_OFFSET_MM = -15
FOOTER_SIZE_PT = 8
FOOTER_HEIGHT_MM = 5
CREATOR = "VendorGuard sample generator"


class _Pdf(FPDF):
    def __init__(self, vendor: str, file_id: str) -> None:
        super().__init__(format="A4", unit="mm")
        self._vendor = vendor
        self._file_id = file_id

    def file_id(self) -> str:
        """A fixed ``<hex><hex>`` ID (the format the PDF spec wants)."""
        return f"<{self._file_id}><{self._file_id}>"

    def footer(self) -> None:
        """Vendor name and page number, centred at the bottom of every page."""
        self.set_y(FOOTER_OFFSET_MM)
        self.set_font("Helvetica", size=FOOTER_SIZE_PT)
        self.cell(
            0, FOOTER_HEIGHT_MM, f"{self._vendor} - Page {self.page_no()} of {{nb}}", align="C"
        )


def render_pdf(
    stem: str, vendor: str, pages: list[list[Block]], settings: SamplesSettings
) -> bytes:
    """Return the PDF bytes; identical inputs always give identical bytes."""
    pdf = _Pdf(vendor, sha256_text(stem)[:FILE_ID_CHARS])
    pdf.set_creation_date(settings.creation_date)
    pdf.set_compression(False)
    pdf.set_auto_page_break(False)
    pdf.set_margins(settings.margin_mm, settings.margin_mm, settings.margin_mm)
    pdf.set_title(f"{vendor} - Security & Trust Overview")
    pdf.set_author(vendor)
    pdf.set_creator(CREATOR)
    pdf.set_producer(CREATOR)
    pdf.alias_nb_pages()
    line = settings.line_height_mm
    for page in pages:
        pdf.add_page()
        for block in page:
            if block.kind == "title":
                pdf.set_font("Helvetica", style="B", size=settings.title_font_size_pt)
                pdf.cell(0, 2 * line, block.text, new_x="LMARGIN", new_y="NEXT")
            elif block.kind in ("subtitle", "heading"):
                pdf.set_font("Helvetica", style="B", size=settings.heading_font_size_pt)
                pdf.cell(0, line, block.text, new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.set_font("Helvetica", size=settings.font_size_pt)
                for text in wrap_lines(block.text, settings.wrap_chars):
                    if pdf.get_string_width(text) > pdf.epw:
                        raise ConfigError(f"line too wide for the page: {text[:40]!r}")
                    pdf.cell(0, line, text, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(line)
    return bytes(pdf.output())


__all__ = ["render_pdf"]
