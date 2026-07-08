"""Tests for AnalysisEngine."""
import json
import pytest
from sensor_listener.analysis import AnalysisEngine, AdaptiveBaseline, DecisionLogger


def make_data(**overrides):
    defaults = {"t": 26.3, "h": 54.8, "light": 320.5, "eco2": 450, "tvoc": 12, "gas": 0.85, "soil": 2200, "ts": 1000}
    defaults.update(overrides)
    return defaults


class TestHealthScore:
    def test_perfect_score(self):
        engine = AnalysisEngine()
        data = make_data(t=23.0, h=65.0, light=500, soil=1750)
        score = engine.health_score(data)
        assert score >= 90  # All in ideal range

    def test_poor_score(self):
        engine = AnalysisEngine()
        data = make_data(t=45.0, h=10.0, light=0, soil=4000)
        score = engine.health_score(data)
        assert score < 40

    def test_null_fields_excluded(self):
        engine = AnalysisEngine()
        data = make_data(t=None, h=None)
        data.pop("eco2", None)
        data.pop("tvoc", None)
        score = engine.health_score(data)
        assert 0 <= score <= 100  # Should not crash


class TestTrendDetection:
    def test_rising_temperature(self):
        engine = AnalysisEngine()
        # Feed 5 minutes of rising temperature
        for i in range(300):
            engine.feed(make_data(t=20.0 + i * 0.02, ts=i * 1000))
        trends = engine.trends()
        assert trends["t"] > 0  # Positive trend

    def test_stable_humidity(self):
        engine = AnalysisEngine()
        for i in range(300):
            engine.feed(make_data(h=55.0, ts=i * 1000))
        trends = engine.trends()
        assert abs(trends["h"]) < 0.5  # Near zero trend

    def test_trend_with_gaps(self):
        engine = AnalysisEngine()
        # Feed only 10 data points with gaps
        for i in range(10):
            engine.feed(make_data(ts=i * 5000))
        trends = engine.trends()
        assert isinstance(trends, dict)  # Should handle sparse data

    def test_get_summary(self):
        engine = AnalysisEngine()
        engine.feed(make_data())
        summary = engine.get_summary()
        assert "health" in summary
        assert "trends" in summary
        assert "alerts" in summary


class TestAdaptiveBaseline:
    def test_baseline_initial_empty(self):
        base = AdaptiveBaseline(window_hours=24)
        result = base.check({"t": 26.3})
        assert result["t"]["status"] == "unknown"  # Not enough data yet

    def test_baseline_detects_anomaly(self):
        base = AdaptiveBaseline(window_hours=24)
        # Feed "normal" data
        for _ in range(100):
            base.feed(make_data(t=24.0, h=60.0, soil=1800))
        result = base.check(make_data(t=35.0, h=60.0, soil=1800))
        assert result["t"]["status"] == "anomaly"

    def test_baseline_normal(self):
        base = AdaptiveBaseline(window_hours=24)
        for _ in range(100):
            base.feed(make_data(t=24.0, h=60.0, soil=1800))
        result = base.check(make_data(t=24.5, h=59.0, soil=1780))
        assert result["t"]["status"] == "normal"


class TestDecisionLogger:
    def test_log_and_flush(self, tmp_path):
        logger = DecisionLogger(max_entries=10, flush_path=str(tmp_path / "decisions.json"))
        logger.log("开风扇 80%", "温度 31.2°C > 阈值 30°C")
        logger.log("开水泵 30%", "土壤 3100 > 阈值 2500, LLM确认")

        entries = logger.get_recent(5)
        assert len(entries) == 2
        assert "风扇" in entries[0]["action"]

        logger.flush()
        saved = json.loads((tmp_path / "decisions.json").read_text(encoding="utf-8"))
        assert len(saved) == 2

    def test_ring_buffer_wraps(self, tmp_path):
        logger = DecisionLogger(max_entries=3, flush_path=str(tmp_path / "decisions.json"))
        for i in range(5):
            logger.log(f"action_{i}", f"trigger_{i}")
        entries = logger.get_recent(10)
        assert len(entries) == 3
        assert entries[0]["action"] == "action_2"  # Oldest kept
        assert entries[-1]["action"] == "action_4"  # Newest
