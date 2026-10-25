"""Spacing and alignment on the tiles, checked on the drawing calls, so a regression fails in CI and not on paper.

Rules (docs/design/conformance.md, section 2):
- the lines of a multi-line title sit close together, so the title groups
- a metric's value and its unit sit close together, and the values of one row share a line
- the rows of a table share one label column, so their dot leaders line up, and rows have a little air
- chart labels line up with the plot's edges, and the plot keeps a margin before the axis labels
"""

from app.render import strips
from app.render.canvas import Canvas, solid_width
from app.render.strips import AXIS_CAP, CHART_INSET, ROW, ROW_GAP, TITLE_LEAD, Block, render_strip


def record(monkeypatch, name):
    calls = []
    original = getattr(Canvas, name)

    def wrapper(self, *args, **kwargs):
        calls.append(args)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Canvas, name, wrapper)
    return calls


def card_canvas():
    c = Canvas()
    c.y = 0
    return c, strips.Card(c, "neutral")


def test_title_lines_sit_close_together(monkeypatch):
    texts = record(monkeypatch, "text")
    c, _ = card_canvas()
    strips._heading(c, 15, "GOOD MORNING ALEX", 200)
    ys = sorted({args[1] for args in texts})
    scale = texts[0][3]
    assert len(ys) >= 2, "the title must wrap to check its leading"
    assert ys[1] - ys[0] == 7 * scale + TITLE_LEAD
    assert TITLE_LEAD <= 3


def test_metric_values_in_a_row_share_one_line(monkeypatch):
    solids = record(monkeypatch, "solid")
    render_strip([
        Block("metric", {"label": "Body battery", "value": "72", "unit": "%"}),
        Block("metric", {"label": "Steps", "value": "6,120"}),
    ])
    lines = {args[2]: args[1] for args in solids if args[2] in ("72", "6,120")}
    assert set(lines) == {"72", "6,120"}
    assert len(set(lines.values())) == 1, lines


def test_unit_sits_close_to_its_number(monkeypatch):
    solids = record(monkeypatch, "solid")
    render_strip([Block("metric", {"label": "Body battery", "value": "72", "unit": "%"})])
    value = next(args for args in solids if args[2] == "72")
    unit = next(args for args in solids if args[2] == "%")
    gap = unit[0] - (value[0] + solid_width("72", value[3]))
    assert 0 <= gap <= 4, gap


def test_table_leaders_start_on_one_column(monkeypatch):
    rects = record(monkeypatch, "fill_rect")
    c, card = card_canvas()
    strips._metric_rows(card, {"rows": [
        {"label": "ENERGY NOW", "value": "0.079", "unit": "GBP/kWh"},
        {"label": "INSIDE / OUT", "value": "19.5 / 12 C"},
    ]}, 15, 497)
    bands: dict[int, list[int]] = {}
    for x, y, w, h in rects:
        if w == 2 and h == 2:
            bands.setdefault(y, []).append(x)
    assert len(bands) == 2
    starts = {min(xs) for xs in bands.values()}
    assert len(starts) == 1, starts
    first, second = sorted(bands)
    assert second - first == ROW + ROW_GAP


def test_chart_labels_line_up_with_the_plot(monkeypatch):
    solids = record(monkeypatch, "solid")
    c, card = card_canvas()
    strips._graph(card, {"title": "Outside 24 h", "series": [8.0, 11.1, 14.2, 12.0, 9.0], "unit": "C"}, 15, 497)
    high = next(args for args in solids if args[2].startswith("HIGH"))
    low = next(args for args in solids if args[2].startswith("LOW"))
    axis = next(args for args in solids if args[2] == "24H")
    now = next(args for args in solids if args[2] == "NOW")
    assert high[0] == 15 + CHART_INSET
    assert low[0] + solid_width(low[2], AXIS_CAP) == 497 - CHART_INSET
    assert axis[0] == 15 + CHART_INSET
    assert now[0] + solid_width("NOW", AXIS_CAP) == 497 - CHART_INSET
    # the scale labels clear the title, and the axis labels clear the plot
    plot_top = high[1] + AXIS_CAP + 8
    assert axis[1] == plot_top + card.plot_h + 8


def test_graph_and_table_titles_use_the_solid_label_size(monkeypatch):
    texts = record(monkeypatch, "text")
    solids = record(monkeypatch, "solid")
    c, card = card_canvas()
    strips._graph(card, {"title": "Home temperature", "series": [16.8, 20.5, 18.0], "unit": "C"}, 15, 497)
    title = next(args for args in solids if args[2] == "HOME TEMPERATURE")
    assert title[3] == 21  # the metric label size, as STEPS and STRESS
    assert not any(args[0] == 15 and args[1] == 0 for args in texts)  # no dot-matrix title at the top
    strips._metric_rows(card, {"title": "Energy and house", "rows": [{"label": "ENERGY NOW", "value": "0.079"}]}, 15, 497)
    rows_title = next(args for args in solids if args[2] == "ENERGY AND HOUSE")
    assert rows_title[3] == 21
