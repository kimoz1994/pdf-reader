import pytest

from services.pdf_geometry import (
    FIT_TO_WIDTH,
    PageLayout,
    center_v_scroll,
    clip_widget_rect_to_page,
    qround_half_up,
)


PAGES_PTS = [(600.0, 800.0), (600.0, 800.0)]  # 2 equal letter-size pages


# ------------------- rounding -------------------

def test_qround_half_up_matches_qt():
    assert qround_half_up(1.4) == 1
    assert qround_half_up(1.5) == 2
    assert qround_half_up(2.5) == 3


# ------------------- page sizes -------------------

def test_page_pixel_size_custom_scales_by_dpi_and_zoom():
    layout = PageLayout(PAGES_PTS, zoom=1.0, dpi=96.0)
    # 600*4/3 = 800, 800*4/3 = 1066.66 -> 1067
    assert layout.page_pixel_size(0) == (800, 1067)


def test_page_pixel_size_rounds_like_qsize_to_size():
    layout = PageLayout([(595.0, 842.0)], zoom=1.0, dpi=96.0)
    # 595*4/3 = 793.33 -> 793 ; 842*4/3 = 1122.66 -> 1123
    assert layout.page_pixel_size(0) == (793, 1123)


# ------------------- stacking -------------------

def test_pages_stack_vertically_with_spacing():
    layout = PageLayout(
        PAGES_PTS, zoom=1.0, dpi=96.0, margins=(6, 6, 6, 6), spacing=12
    )
    _, y0, _, _ = layout.page_rect_doc(0)
    _, y1, _, _ = layout.page_rect_doc(1)
    assert y0 == 6.0
    _, h0 = layout.page_pixel_size(0)
    assert y1 == pytest.approx(y0 + h0 + 12)


def test_pages_centered_on_widest_page():
    pages = [(400.0, 800.0), (600.0, 800.0)]
    layout = PageLayout(pages, zoom=1.0, dpi=72.0, margins=(6, 6, 6, 6), viewport_width=0)
    x0, _, x1, _ = layout.page_rect_doc(0)
    cx0, _, cx1, _ = layout.page_rect_doc(1)
    assert cx0 == 6.0
    # narrow page centered relative to widest page start
    assert x0 == pytest.approx(6 + (600 - 400) / 2.0)
    assert (x0 + x1) == pytest.approx(cx0 + cx1)


def test_page_centered_in_viewport_when_viewport_wider_than_document():
    # document width = 400 + 12 = 412; viewport 800 wide
    layout = PageLayout(
        [(400.0, 800.0)], zoom=1.0, dpi=72.0, margins=(6, 6, 6, 6), viewport_width=800
    )
    x0, _, x1, _ = layout.page_rect_doc(0)
    # pageX = (max(412, 800) - 400)/2 = 200 ; page width 400
    assert x0 == pytest.approx(200.0)
    assert x1 == pytest.approx(600.0)


def test_document_height_sums_pages_margins_spacing():
    layout = PageLayout(
        PAGES_PTS, zoom=1.0, dpi=96.0, margins=(6, 6, 6, 6), spacing=12
    )
    _, h0 = layout.page_pixel_size(0)
    _, h1 = layout.page_pixel_size(1)
    assert layout.document_height() == pytest.approx(6 + h0 + 12 + h1 + 6)


def test_document_width_is_max_page_plus_margins():
    layout = PageLayout(
        [(400.0, 800.0), (600.0, 800.0)], zoom=1.0, dpi=72.0, margins=(6, 6, 6, 6)
    )
    assert layout.document_width() == 600 + 12


# ------------------- FitToWidth -------------------

def test_fit_to_width_makes_page_fill_available_width():
    layout = PageLayout(
        PAGES_PTS,
        zoom=1.0,
        dpi=96.0,
        margins=(6, 6, 6, 6),
        spacing=12,
        viewport_width=800,
        zoom_mode=FIT_TO_WIDTH,
    )
    w, _ = layout.page_pixel_size(0)
    assert w == pytest.approx(800 - 12)


# ------------------- mapping -------------------

def test_pdf_to_doc_scales_and_offsets():
    layout = PageLayout(PAGES_PTS, zoom=1.0, dpi=96.0, margins=(6, 6, 6, 6), spacing=12)
    x0, y0, x1, y1 = layout.pdf_to_doc(0, (10.0, 20.0, 110.0, 40.0))
    fx = 800 / 600.0  # page pixel width / point width
    fy = 1067 / 800.0
    assert x0 == pytest.approx(6 + 10 * fx)
    assert y0 == pytest.approx(6 + 20 * fy)
    assert x1 == pytest.approx(6 + 110 * fx)
    assert y1 == pytest.approx(6 + 40 * fy)


def test_doc_to_widget_applies_scroll_and_viewport_offset():
    layout = PageLayout(
        PAGES_PTS,
        zoom=1.0,
        dpi=96.0,
        margins=(6, 6, 6, 6),
        spacing=12,
        h_scroll=10,
        v_scroll=200,
        viewport_offset=(1, 1),
    )
    x0, y0, x1, y1 = layout.doc_to_widget((100.0, 300.0, 200.0, 320.0))
    assert x0 == 90.0 + 1
    assert y0 == 100.0 + 1
    assert x1 == 190.0 + 1
    assert y1 == 120.0 + 1


def test_pdf_to_widget_roundtrip():
    layout = PageLayout(
        PAGES_PTS,
        zoom=2.0,
        dpi=96.0,
        margins=(6, 6, 6, 6),
        spacing=12,
        h_scroll=30,
        v_scroll=50,
        viewport_offset=(2, 3),
    )
    pdf_rect = (10.0, 20.0, 110.0, 40.0)
    widget = layout.pdf_to_widget(0, pdf_rect)
    wx0, wy0, _, _ = widget
    back_x, back_y = layout.widget_to_pdf(0, (wx0, wy0))
    assert back_x == pytest.approx(10.0)
    assert back_y == pytest.approx(20.0)


def test_widget_point_page_index_hits_page():
    layout = PageLayout(
        PAGES_PTS,
        zoom=1.0,
        dpi=72.0,
        margins=(0, 0, 0, 0),
        spacing=12,
        viewport_offset=(0, 0),
    )
    assert layout.widget_point_page_index((100, 400)) == 0
    assert layout.widget_point_page_index((100, 900)) == 1
    assert layout.widget_point_page_index((100, 805)) is None  # in the gap


def test_widget_to_pdf_uses_scroll():
    layout = PageLayout(
        PAGES_PTS,
        zoom=1.0,
        dpi=72.0,
        margins=(0, 0, 0, 0),
        spacing=12,
        h_scroll=20,
        v_scroll=10,
        viewport_offset=(0, 0),
    )
    x, y = layout.widget_to_pdf(0, (120.0, 210.0))
    assert x == 140.0
    assert y == 220.0


def test_pages_mapped_onto_report_oriented_probe():
    # Reproduce the Qt probe: 884x684 viewport, page 595.44x841.69 pts, dpi 96, zoom 1
    layout = PageLayout(
        [(595.444, 841.691)],
        zoom=1.0,
        dpi=96.0,
        margins=(6, 6, 6, 6),
        spacing=12,
        viewport_width=884,
        viewport_height=684,
        viewport_offset=(0, 0),
    )
    x0, y0, x1, y1 = layout.page_rect_widget(0)
    # page pixel width = qround(595.444*4/3) = 794 ; pageX = (max(806,884)-794)/2 = 45
    assert x0 == pytest.approx(45.0)
    assert y0 == 6.0
    assert x1 - x0 == pytest.approx(794.0)


# ------------------- centre-scroll (jump-back) -------------------

def test_center_v_scroll_centres_mid_page_rect():
    layout = PageLayout(
        PAGES_PTS, zoom=1.0, dpi=72.0, margins=(6, 6, 6, 6), spacing=3,
        viewport_height=400,
    )
    # page0 top=6; rect y 300..500 -> doc 306..506 -> center 406
    # raw = 406 - 200 = 206 ; max = 1615 - 400 = 1215 -> 206
    assert center_v_scroll(layout, 0, (100.0, 300.0, 500.0, 500.0)) == 206


def test_center_v_scroll_clamps_to_zero_near_top():
    layout = PageLayout(
        PAGES_PTS, zoom=1.0, dpi=72.0, margins=(6, 6, 6, 6), spacing=3,
        viewport_height=400,
    )
    # center = 6 + 20 = 26 ; raw = 26 - 200 < 0 -> 0
    assert center_v_scroll(layout, 0, (100.0, 0.0, 500.0, 40.0)) == 0


def test_center_v_scroll_clamps_to_document_end_near_bottom():
    layout = PageLayout(
        PAGES_PTS, zoom=1.0, dpi=72.0, margins=(6, 6, 6, 6), spacing=3,
        viewport_height=1400,
    )
    # document_height = 6+800+3+800+6 = 1615 -> max = 1615-1400 = 215
    # page1 top = 809 ; rect y 760..800 -> doc 1569..1609 -> center 1589
    # raw = 1589 - 700 = 889 > 215 -> clamped to 215
    assert center_v_scroll(layout, 1, (100.0, 760.0, 500.0, 800.0)) == 215


def test_center_v_scroll_uses_page_stacking_for_later_pages():
    layout = PageLayout(
        PAGES_PTS, zoom=1.0, dpi=72.0, margins=(6, 6, 6, 6), spacing=3,
        viewport_height=400,
    )
    # page1 top = 6+800+3 = 809 ; rect y 100..300 -> doc 909..1109
    # center 1009 ; raw = 1009 - 200 = 809 ; max = 1215 -> 809
    # (if stacking were ignored the answer would be ~6, so this pins the bug)
    assert center_v_scroll(layout, 1, (100.0, 100.0, 500.0, 300.0)) == 809


# ------------------- misc -------------------

def test_clip_widget_rect_to_page_clips_outside_region():
    rect = (-50.0, -50.0, 50.0, 50.0)
    page = (0.0, 0.0, 100.0, 100.0)
    clipped = clip_widget_rect_to_page(rect, page)
    assert clipped == (0.0, 0.0, 50.0, 50.0)


def test_clip_widget_rect_to_page_disjoint_returns_zero_rect():
    rect = (200.0, 200.0, 300.0, 300.0)
    page = (0.0, 0.0, 100.0, 100.0)
    assert clip_widget_rect_to_page(rect, page) == (0.0, 0.0, 0.0, 0.0)


# ------------------- #87 index cache: golden tests vs the naive loops -------------------
# PageLayout precomputes per-page sizes and document offsets in __post_init__
# (scroll-path hot loop). These reference functions are verbatim copies of the
# pre-#87 algorithms; the index must agree with them for every input shape.

def _naive_page_pixel_size(layout, i):
    w_pt, h_pt = layout.page_sizes_pts[i]
    scr = layout.screen_resolution
    if layout.zoom_mode == FIT_TO_WIDTH:
        base_w = qround_half_up(w_pt * scr)
        available = layout.viewport_width - layout.margins.left - layout.margins.right
        factor = available / base_w if base_w else 1.0
        return (
            qround_half_up(base_w * factor),
            qround_half_up(qround_half_up(h_pt * scr) * factor),
        )
    return (
        qround_half_up(w_pt * scr * layout.zoom),
        qround_half_up(h_pt * scr * layout.zoom),
    )


def _naive_document_width(layout):
    widths = [
        _naive_page_pixel_size(layout, i)[0]
        for i in range(len(layout.page_sizes_pts))
    ]
    return max(widths) + layout.margins.left + layout.margins.right


def _naive_document_height(layout):
    total = layout.margins.top
    for i in range(len(layout.page_sizes_pts)):
        _, h = _naive_page_pixel_size(layout, i)
        total += h
        if i < len(layout.page_sizes_pts) - 1:
            total += layout.spacing
    return total + layout.margins.bottom


def _naive_page_top_left_doc(layout, i):
    w, _ = _naive_page_pixel_size(layout, i)
    page_x = (max(_naive_document_width(layout), layout.viewport_width) - w) // 2
    page_y = layout.margins.top
    for j in range(i):
        _, h = _naive_page_pixel_size(layout, j)
        page_y += h + layout.spacing
    return (page_x, page_y)


def _naive_widget_point_page_index(layout, point):
    x, y = point
    for i in range(len(layout.page_sizes_pts)):
        px0, py0, px1, py1 = layout.page_rect_doc(i)
        px0 -= layout.h_scroll - layout.viewport_offset[0]
        py0 -= layout.v_scroll - layout.viewport_offset[1]
        px1 -= layout.h_scroll - layout.viewport_offset[0]
        py1 -= layout.v_scroll - layout.viewport_offset[1]
        if px0 <= x <= px1 and py0 <= y <= py1:
            return i
    return None


_GOLDEN_CASES = [
    # portrait letters, custom zoom
    dict(page_sizes_pts=PAGES_PTS, zoom=1.0, dpi=96.0),
    dict(page_sizes_pts=PAGES_PTS, zoom=2.5, dpi=72.0),
    # mixed portrait/landscape + wide/short pages
    dict(
        page_sizes_pts=[(612.0, 792.0), (792.0, 612.0), (100.0, 2000.0), (595.0, 842.0)],
        zoom=1.25,
        dpi=120.0,
        margins=(6, 6, 6, 6),
        spacing=12,
        viewport_width=1440,
        viewport_height=900,
        h_scroll=13,
        v_scroll=9876,
        viewport_offset=(2, 5),
    ),
    # FitToWidth
    dict(
        page_sizes_pts=[(612.0, 792.0), (792.0, 612.0), (500.0, 500.0)],
        zoom=1.0,
        dpi=96.0,
        margins=(6, 6, 6, 6),
        spacing=12,
        viewport_width=1440,
        viewport_height=900,
        zoom_mode=FIT_TO_WIDTH,
        h_scroll=7,
        v_scroll=12345,
        viewport_offset=(1, 1),
    ),
    # FitToWidth with a zero-width page (degenerate factor guard)
    dict(
        page_sizes_pts=[(0.0, 792.0), (612.0, 792.0)],
        zoom=1.0,
        dpi=96.0,
        viewport_width=800,
        zoom_mode=FIT_TO_WIDTH,
    ),
    # viewport wider than the document (page centred in viewport)
    dict(
        page_sizes_pts=[(400.0, 800.0)],
        zoom=1.0,
        dpi=72.0,
        viewport_width=800,
        margins=(6, 6, 6, 6),
    ),
]


@pytest.mark.parametrize("kwargs", _GOLDEN_CASES)
def test_indexed_layout_matches_naive_reference(kwargs):
    layout = PageLayout(**kwargs)
    n = len(layout.page_sizes_pts)
    for i in range(n):
        assert layout.page_pixel_size(i) == _naive_page_pixel_size(layout, i)
        assert layout.page_top_left_doc(i) == _naive_page_top_left_doc(layout, i)
    assert layout.document_width() == _naive_document_width(layout)
    assert layout.document_height() == _naive_document_height(layout)
    for point in [
        (0, 0),
        (100, 500),
        (45, 6),
        (100000, 400),
        (30, 100000),
        (-5, -5),
    ]:
        assert (
            layout.widget_point_page_index(point)
            == _naive_widget_point_page_index(layout, point)
        ), f"point={point} kwargs={kwargs}"


def test_center_v_scroll_matches_naive_through_index():
    layout = PageLayout(
        [(612.0, 792.0), (792.0, 612.0)],
        zoom=1.0,
        dpi=96.0,
        margins=(6, 6, 6, 6),
        spacing=12,
        viewport_width=1440,
        viewport_height=700,
        zoom_mode=FIT_TO_WIDTH,
    )
    rect = (100.0, 300.0, 500.0, 700.0)
    got = center_v_scroll(layout, 1, rect)
    # naive: rebuild the height sums by hand
    _, h0 = _naive_page_pixel_size(layout, 0)
    _, h1 = _naive_page_pixel_size(layout, 1)
    doc_w = _naive_document_width(layout)
    w1, _ = _naive_page_pixel_size(layout, 1)
    fx = w1 / 792.0
    fy = h1 / 612.0
    py = 6 + h0 + 12
    y0 = py + 300 * fy
    y1 = py + 700 * fy
    centre = (y0 + y1) / 2.0
    raw = centre - 700 / 2.0
    max_scroll = max(0, (6 + h0 + 12 + h1 + 6) - 700)
    assert got == min(qround_half_up(max(0.0, raw)), max_scroll)
    assert doc_w > 0