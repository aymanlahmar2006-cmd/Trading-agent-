import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crypto_agent import ichimoku as ichi
from crypto_agent.schema import parse_bar, parse_snapshot
from crypto_agent.signal import analyse
from tests.helpers import CONFIG, bars_from_path, make_snapshot
from tests.test_signal import BULLISH_PULLBACK, build


def _bars(payloads):
    return [parse_bar(p, i) for i, p in enumerate(payloads)]


def test_not_enough_history_returns_nothing_rather_than_a_partial_cloud():
    assert ichi.compute(_bars(bars_from_path([100, 110], steps=5))) is None
    assert ichi.minimum_bars() == 78


def test_the_cloud_is_displaced_not_read_from_todays_spans():
    """The mistake most implementations make.

    Senkou A and B are plotted 26 bars forward, so the cloud under today's
    candle was computed 26 bars ago. A rising market makes today's raw spans
    higher than the displayed ones, so the two readings differ -- and only the
    displaced one is on the chart.
    """
    bars = _bars(bars_from_path([100, 200], steps=100))
    reading = ichi.compute(bars)
    assert reading is not None

    last = len(bars) - 1
    todays_b = ichi._midpoint(bars, ichi.SENKOU_B_PERIOD, last)
    displaced_b = ichi._midpoint(bars, ichi.SENKOU_B_PERIOD, last - ichi.DISPLACEMENT)

    assert reading.senkou_b == pytest.approx(displaced_b)
    assert reading.senkou_b != pytest.approx(todays_b), \
        "the cloud must come from the displaced bar, not the current one"


def test_price_position_reads_above_inside_and_below():
    reading = ichi.Ichimoku(tenkan=105, kijun=100, senkou_a=98, senkou_b=92,
                            chikou_above_past_price=True)
    assert reading.cloud_top == 98 and reading.cloud_bottom == 92
    assert reading.price_position(110) == ichi.ABOVE
    assert reading.price_position(95) == ichi.INSIDE
    assert reading.price_position(80) == ichi.BELOW


def test_cloud_colour_and_tk_cross():
    bullish = ichi.Ichimoku(tenkan=105, kijun=100, senkou_a=98, senkou_b=92,
                            chikou_above_past_price=None)
    bearish = ichi.Ichimoku(tenkan=95, kijun=100, senkou_a=92, senkou_b=98,
                            chikou_above_past_price=None)
    assert bullish.cloud_is_bullish and bullish.tk_bullish
    assert not bearish.cloud_is_bullish and not bearish.tk_bullish


def test_chart_values_are_preferred_over_computed_ones():
    studies = {"tenkan": 1.0, "kijun": 2.0, "senkou_a": 3.0, "senkou_b": 4.0}
    reading = ichi.from_studies(studies)
    assert reading is not None and reading.kijun == 2.0
    # A partial set is not usable.
    assert ichi.from_studies({"tenkan": 1.0, "kijun": 2.0}) is None


def test_levels_are_split_by_side_of_price():
    reading = ichi.Ichimoku(tenkan=105, kijun=100, senkou_a=98, senkou_b=92,
                            chikou_above_past_price=None)
    assert sorted(ichi.support_levels(reading, 110)) == [92, 98, 100, 105]
    assert ichi.support_levels(reading, 95) == [92]
    assert sorted(ichi.resistance_levels(reading, 95)) == [98, 100, 105]


def test_a_long_above_the_cloud_is_allowed():
    result = analyse(build(BULLISH_PULLBACK,
                           {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7},
                           pine_lines=[126.0], steps=14), CONFIG)
    assert result.cloud_position == ichi.ABOVE
    assert result.plan is not None


def test_price_below_the_cloud_vetoes_the_long_even_when_everything_else_agrees():
    """The gap this module exists to close.

    Every other input reads bullish, but the chart the user looks at has price
    under the cloud. The engine must stand aside rather than issue advice the
    chart contradicts.
    """
    bars = bars_from_path(BULLISH_PULLBACK, steps=14)
    price = bars[-1]["close"]
    payload = make_snapshot(bars, price, {
        "RSI": 60.0, "MACD": 2.0, "Signal": 1.0,
        # Chart-reported cloud sitting well above price.
        "Conversion Line": price + 10, "Base Line": price + 12,
        "Leading Span A": price + 20, "Leading Span B": price + 30,
    }, [price + 50])
    result = analyse(parse_snapshot(payload), CONFIG)

    assert result.cloud_position == ichi.BELOW
    assert result.plan is None
    assert result.actionable is False
    assert "cloud" in result.rejected_reason.lower()


def test_price_inside_the_cloud_also_vetoes():
    bars = bars_from_path(BULLISH_PULLBACK, steps=14)
    price = bars[-1]["close"]
    payload = make_snapshot(bars, price, {
        "RSI": 60.0, "MACD": 2.0, "Signal": 1.0,
        "Conversion Line": price, "Base Line": price,
        "Leading Span A": price + 5, "Leading Span B": price - 5,
    }, [price + 50])
    result = analyse(parse_snapshot(payload), CONFIG)

    assert result.cloud_position == ichi.INSIDE
    assert result.plan is None


def test_the_veto_can_be_switched_off():
    config = {**CONFIG, "filters": {**CONFIG["filters"], "ichimoku_veto": False}}
    bars = bars_from_path(BULLISH_PULLBACK, steps=14)
    price = bars[-1]["close"]
    payload = make_snapshot(bars, price, {
        "RSI": 60.0, "MACD": 2.0, "Signal": 1.0,
        "Conversion Line": price + 10, "Base Line": price + 12,
        "Leading Span A": price + 20, "Leading Span B": price + 30,
    }, [price + 50])
    result = analyse(parse_snapshot(payload), config)

    # Without the veto the cloud is still a heavily weighted bearish vote, so
    # the trend read should turn against the long rather than silently allow it.
    assert result.cloud_position == ichi.BELOW
    assert result.plan is None or result.trend != "bullish"


def test_cloud_votes_carry_the_numbers_they_came_from():
    result = analyse(build(BULLISH_PULLBACK,
                           {"RSI": 56.0, "MACD": 1.2, "Signal": 0.7},
                           pine_lines=[126.0], steps=14), CONFIG)
    kinds = {v.name for v in result.votes}
    assert {"ichimoku_cloud", "ichimoku_tk", "ichimoku_cloud_colour"} <= kinds
    cloud_vote = next(v for v in result.votes if v.name == "ichimoku_cloud")
    assert "cloud" in cloud_vote.detail
