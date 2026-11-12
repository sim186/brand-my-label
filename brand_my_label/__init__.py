"""brand-my-label: put your shop logo on shipping labels."""

from .stamp import StampError, StampResult, stamp_pdf
from .vinted import VintedError, fetch_pdf_from_html, is_html

__all__ = ["StampError", "StampResult", "stamp_pdf",
           "VintedError", "fetch_pdf_from_html", "is_html"]
__version__ = "0.1.0"
