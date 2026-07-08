"""Plant health analysis — health score, trend detection, adaptive baseline, event logging."""
import json as _json
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path


class AnalysisEngine:
    """Computes plant health metrics from sensor data streams."""

    # Ideal ranges: (min, optimal, max)
    IDEAL = {
        "t": (18, 23, 28),          # °C
        "h": (50, 65, 80),          # %
        "light": (200, 500, 800),   # lux
        "soil": (1000, 1750, 2500), # raw ADC
    }

    TREND_WINDOW = 300  # seconds of sliding window for trend detection

    def __init__(self):
        self._window: deque[tuple[float, dict]] = deque()  # (timestamp, data)
        self._scores: deque[int] = deque(maxlen=100)

    def health_score(self, data: dict) -> int:
        """Compute plant health score 0-100 from sensor data. Each sensor contributes up to 25 points."""
        # Per-sensor formulas from spec
        formulas = {
            "t":     (23,   2.5),
            "h":     (65,   1.7),
            "light": (500,  0.05),
            "soil":  (1750, 0.017),
        }
        total = 0.0
        for key, (opt, slope) in formulas.items():
            val = data.get(key)
            if val is not None:
                total += max(0.0, 25.0 - abs(val - opt) * slope)
        return int(min(100.0, total))

    def feed(self, data: dict) -> None:
        """Ingest one sensor reading for trend analysis."""
        now = time.perf_counter()
        self._window.append((now, dict(data)))

        # Purge old entries beyond TREND_WINDOW
        cutoff = now - self.TREND_WINDOW
        while self._window and self._window[0][0] < cutoff:
            self._window.popleft()

        score = self.health_score(data)
        self._scores.append(score)

    def trends(self) -> dict[str, float]:
        """Return per-sensor rate of change over the window (units/second)."""
        if len(self._window) < 2:
            return {}

        first_ts, first_data = self._window[0]
        last_ts, last_data = self._window[-1]
        dt = last_ts - first_ts
        if dt <= 0:
            return {}

        trends = {}
        for key in ["t", "h", "light", "soil", "gas"]:
            v1 = first_data.get(key)
            v2 = last_data.get(key)
            if v1 is not None and v2 is not None:
                trends[key] = (v2 - v1) / dt
        return trends

    def get_summary(self) -> dict:
        """Return analysis summary: health score, trends, and alerts."""
        current_score = self._scores[-1] if self._scores else 0
        trend_data = self.trends()
        alerts = []

        # Health-based alerts
        if current_score < 40:
            alerts.append("\U0001f534 植物健康严重恶化")
        elif current_score < 60:
            alerts.append("\U0001f7e1 植物健康偏低，请注意")

        # Trend-based alerts
        t_rate = trend_data.get("t", 0) * 300  # scale to per-5min
        if t_rate > 3:
            alerts.append(f"\U0001f321 温度快速上升 +{t_rate:.1f}°C/5min")
        elif t_rate < -3:
            alerts.append(f"\U0001f321 温度快速下降 {t_rate:.1f}°C/5min")

        soil_rate = trend_data.get("soil", 0) * 300
        if soil_rate > 200:
            alerts.append("\U0001f3dc 土壤正在快速变干")

        return {
            "health": current_score,
            "trends": {k: v * 300 for k, v in trend_data.items()},  # per-5min rates
            "alerts": alerts,
        }

    def get_recent_data(self, max_count: int = 60) -> list[dict]:
        """Return the most recent sensor readings (data portion of the sliding window)."""
        entries = list(self._window)
        if max_count and len(entries) > max_count:
            entries = entries[-max_count:]
        return [data for _ts, data in entries]


class AdaptiveBaseline:
    """Learn normal sensor ranges over a time window and detect anomalies."""

    def __init__(self, window_hours: int = 24):
        self._window_hours = window_hours
        self._history: deque[tuple[float, dict]] = deque()
        self._min_samples = 30

    def feed(self, data: dict) -> None:
        """Ingest a reading for baseline learning."""
        now = datetime.now().timestamp()
        self._history.append((now, {k: v for k, v in data.items() if v is not None}))
        cutoff = now - self._window_hours * 3600
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

    def check(self, data: dict) -> dict[str, dict]:
        """Compare current values against learned baseline. Returns per-key status."""
        if len(self._history) < self._min_samples:
            return {k: {"status": "unknown", "value": v} for k, v in data.items() if v is not None}

        # Compute mean and std for each key from history
        stats = defaultdict(list)
        for _, hist_data in self._history:
            for k, v in hist_data.items():
                stats[k].append(v)

        baselines = {}
        for k, values in stats.items():
            mean = sum(values) / len(values)
            variance = sum((x - mean) ** 2 for x in values) / len(values)
            std = variance ** 0.5 if variance > 0 else 0.01
            # Enforce a minimum std so that sensors with zero-variance training
            # data (e.g. identical values in tests) don't flag tiny fluctuations.
            if std < 0.5:
                std = 0.5

            current = data.get(k)
            if current is None:
                baselines[k] = {"status": "unknown", "value": None}
            elif abs(current - mean) > 2 * std:
                baselines[k] = {
                    "status": "anomaly",
                    "value": current,
                    "mean": round(mean, 1),
                    "std": round(std, 1),
                }
            else:
                baselines[k] = {
                    "status": "normal",
                    "value": current,
                    "mean": round(mean, 1),
                    "std": round(std, 1),
                }
        return baselines


class DecisionLogger:
    """Ring buffer of control decisions, flushable to JSON file."""

    def __init__(self, max_entries: int = 100, flush_path: str | None = None):
        self._entries: deque[dict] = deque(maxlen=max_entries)
        self._flush_path = Path(flush_path) if flush_path else None

    def log(self, action: str, trigger: str) -> None:
        """Record a control decision."""
        self._entries.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "trigger": trigger,
        })

    def get_recent(self, n: int = 10) -> list[dict]:
        """Get most recent N entries."""
        entries = list(self._entries)
        return entries[-n:] if n < len(entries) else entries

    def flush(self) -> None:
        """Write all entries to JSON file."""
        if self._flush_path:
            self._flush_path.parent.mkdir(parents=True, exist_ok=True)
            self._flush_path.write_text(_json.dumps(list(self._entries), ensure_ascii=False, indent=2), encoding="utf-8")
