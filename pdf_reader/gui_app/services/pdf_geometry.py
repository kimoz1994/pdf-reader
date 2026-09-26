"""Pure page-layout math mirroring QPdfView's calculateDocumentLayout().

No Qt imports — headless-testable. Implements exactly the layout rules from
Qt's qpdfview.cpp (MultiPage mode):

    pageSize (Custom)     = qRound(points * (dpi/72) * zoomFactor)
    pageSize (FitToWidth) = base = qRound(points * (dpi/72))
                            factor = (viewportW - mL - mR) / base.width
                            pageSize = qRound(base * factor)
    totalWidth            = max(pageWidth) + margins.left + margins.right
    pageY                 = margins.top, then += pageHeight + spacing each page
    pageX                 = (max(totalWidth, viewportW) - pageWidth) / 2
    documentHeight        = pageY after last page + margins.bottom

Coordinates:
  - PDF space   = points, top-left origin (pymupdf/QPdfDocument)
  - document     = content laid out as above (ints, matching Qt rounding)
  - widget       = document shifted by scrollbar values into pdf_view coords

Mapping PDF->rendered pixels uses per-axis factors so highlights align
exactly with the rendered page image (which Qt draws at pageGeometry.size()).
"""
from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass
from typing import Sequence, Tuple

Margins = namedtuple("Margins", ["left", "top", "right", "bottom"])
Point = Tuple[float, float]
Size = Tuple[int, int]  # pixels, ints (matches Qt's rounding)
Rect = Tuple[float, float, float, float]  # x0, y0, x1, y1

CUSTOM = "custom"
FIT_TO_WIDTH = "fit_to_width"

DEFAULT_MARGINS = Margins(6, 6, 6, 6)
DEFAULT_SPACING = 3
DEFAULT_DPI = 72.0


def qround_half_up(value: float) -> int:
    """Match Qt's qRound() for positive values (round half away from zero)."""
    return int(value + 0.5)


@dataclass(frozen=True)
class PageLayout:
    """Layout parameters for one rendered view of a document (mirrors Qt)."""

    page_sizes_pts: Sequence[Tuple[float, float]]  # (w, h) per page in points
    zoom: float
    dpi: float = DEFAULT_DPI
    margins: Margins = DEFAULT_MARGINS
    spacing: int = DEFAULT_SPACING
    h_scroll: int = 0
    v_scroll: int = 0
    viewport_width: int = 0
    viewport_height: int = 0
    zoom_mode: str = CUSTOM
    viewport_offset: Point = (0, 0)  # viewport.pos() within pdf_view coords

    def __post_init__(self):
        if not isinstance(self.margins, Margins):
            object.__setattr__(self, "margins", Margins(*self.margins))
        safe_spacing = int(self.spacing)
        object.__setattr__(self, "spacing", safe_spacing)

    @property
    def screen_resolution(self) -> float:
        return self.dpi / 72.0

    def page_pixel_size(self, page_index: int) -> Size:
        """Rendered page size in pixels, rounded exactly like Qt."""
        w_pt, h_pt = self.page_sizes_pts[page_index]
        scr = self.screen_resolution
        if self.zoom_mode == FIT_TO_WIDTH:
            base_w = qround_half_up(w_pt * scr)
            available = self.viewport_width - self.margins.left - self.margins.right
            factor = available / base_w if base_w else 1.0
            return (
                qround_half_up(base_w * factor),
                qround_half_up(qround_half_up(h_pt * scr) * factor),
            )
        # CUSTOM: points * screenResolution * zoomFactor, .toSize()
        return (
            qround_half_up(w_pt * scr * self.zoom),
            qround_half_up(h_pt * scr * self.zoom),
        )

    def max_page_width_px(self) -> int:
        return max(w for w, _ in (self.page_pixel_size(i) for i in range(len(self.page_sizes_pts))))

    def document_width(self) -> int:
        return self.max_page_width_px() + self.margins.left + self.margins.right

    def document_height(self) -> int:
        total = self.margins.top
        for i in range(len(self.page_sizes_pts)):
            _, h = self.page_pixel_size(i)
            total += h
            if i < len(self.page_sizes_pts) - 1:
                total += self.spacing
        return total + self.margins.bottom

    def page_top_left_doc(self, page_index: int) -> Point:
        """Top-left of a page in document space (ints, mirrors Qt)."""
        w, _ = self.page_pixel_size(page_index)
        page_x = (max(self.document_width(), self.viewport_width) - w) // 2
        page_y = self.margins.top
        for i in range(page_index):
            _, h = self.page_pixel_size(i)
            page_y += h + self.spacing
        return (page_x, page_y)

    def page_rect_doc(self, page_index: int) -> Rect:
        x, y = self.page_top_left_doc(page_index)
        w, h = self.page_pixel_size(page_index)
        return (x, y, x + w, y + h)

    # --- mapping helpers -------------------------------------------------

    def _factors(self, page_index: int):
        w_pt, h_pt = self.page_sizes_pts[page_index]
        w, h = self.page_pixel_size(page_index)
        fx = w / w_pt if w_pt else 1.0
        fy = h / h_pt if h_pt else 1.0
        return fx, fy

    def pdf_to_doc(self, page_index: int, rect: Rect) -> Rect:
        """PDF-space rect (points) -> document-space rect (pixels)."""
        px, py = self.page_top_left_doc(page_index)
        x0, y0, x1, y1 = rect
        fx, fy = self._factors(page_index)
        return (px + x0 * fx, py + y0 * fy, px + x1 * fx, py + y1 * fy)

    def doc_to_widget(self, rect: Rect) -> Rect:
        x0, y0, x1, y1 = rect
        ox, oy = self.viewport_offset
        return (
            x0 - self.h_scroll + ox,
            y0 - self.v_scroll + oy,
            x1 - self.h_scroll + ox,
            y1 - self.v_scroll + oy,
        )

    def pdf_to_widget(self, page_index: int, rect: Rect) -> Rect:
        return self.doc_to_widget(self.pdf_to_doc(page_index, rect))

    def widget_to_pdf(self, page_index: int, point: Point) -> Point:
        """Widget-space point -> PDF-space point (points), relative to page."""
        x, y = point
        px, py = self.page_top_left_doc(page_index)
        fx, fy = self._factors(page_index)
        ox, oy = self.viewport_offset
        doc_x = x - ox + self.h_scroll
        doc_y = y - oy + self.v_scroll
        return ((doc_x - px) / fx, (doc_y - py) / fy)

    def widget_point_page_index(self, point: Point) -> int | None:
        """Page under a widget-space point, or None if in a margin/gap."""
        x, y = point
        for i in range(len(self.page_sizes_pts)):
            x0, y0, x1, y1 = self.page_rect_widget(i)
            if x0 <= x <= x1 and y0 <= y <= y1:
                return i
        return None

    def page_rect_widget(self, page_index: int) -> Rect:
        x, y, x1, y1 = self.page_rect_doc(page_index)
        ox, oy = self.viewport_offset
        return (
            x - self.h_scroll + ox,
            y - self.v_scroll + oy,
            x1 - self.h_scroll + ox,
            y1 - self.v_scroll + oy,
        )


def clip_widget_rect_to_page(rect: Rect, page_rect: Rect) -> Rect:
    """Clip a widget-space rect to a page rect (widget space). Returns None-size if disjoint."""
    x0, y0, x1, y1 = rect
    px0, py0, px1, py1 = page_rect
    cx0, cy0 = max(x0, px0), max(y0, py0)
    cx1, cy1 = min(x1, px1), min(y1, py1)
    if cx0 >= cx1 or cy0 >= cy1:
        return (0, 0, 0, 0)
    return (cx0, cy0, cx1, cy1)


def center_v_scroll(layout: "PageLayout", page_index: int, rect: Rect) -> int:
    """Vertical scrollbar value that centres a PDF-space rect in the viewport.

    Used by jump-back: maps the Capture's rect to document space (which
    accounts for page stacking and FitToWidth scaling), targets the rect's
    vertical centre, and clamps to the scrollbar's real range so Qt never
    sees an out-of-range value.
    """
    _, y0, _, y1 = layout.pdf_to_doc(page_index, rect)
    centre = (y0 + y1) / 2.0
    raw = centre - layout.viewport_height / 2.0
    if raw <= 0:
        return 0
    max_scroll = max(0, layout.document_height() - layout.viewport_height)
    return min(qround_half_up(raw), max_scroll)