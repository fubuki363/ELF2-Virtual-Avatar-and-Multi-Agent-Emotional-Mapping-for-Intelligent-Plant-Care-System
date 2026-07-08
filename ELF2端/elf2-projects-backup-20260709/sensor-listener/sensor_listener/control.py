"""Auto-control engine — local rules + K230 UDP command dispatch."""
import time


# ── Safety limits (hard caps, LLM cannot override) ─────
SAFETY_LIMITS = {
    "pump": 50,
    "heater": 80,
    "humidifier": 80,
    "fan": 100,
    "led_brightness": 200,
}

# ── Local rules ─────────────────────────────────────────
# (condition_key, threshold, operator, device, value_fn)
LOCAL_RULES = [
    # Priority 0: safety
    {"key": "t", "threshold": 35, "op": ">", "device": "fan", "value": 100, "priority": 0,
     "reason": "过热保护: 温度 {val}°C > 35°C"},
    # Priority 1: high
    {"key": "t", "threshold": 30, "op": ">", "device": "fan", "value": lambda v: min(100, 50 + int((v - 30) * 10)),
     "priority": 1, "reason": "散热: 温度 {val}°C > 30°C"},
    {"key": "soil", "threshold": 2500, "op": ">", "device": "pump", "value": 30, "priority": 1,
     "reason": "土壤偏干: {val} > 2500"},
    # Priority 2: medium
    {"key": "light", "threshold": 50, "op": "<", "device": "led",
     "value": {"mode": "white", "brightness": 150}, "priority": 2,
     "reason": "补光: 光照 {val} lux < 50 lux"},
    {"key": "h", "threshold": 45, "op": "<", "device": "humidifier", "value": 50, "priority": 2,
     "reason": "空气偏干: 湿度 {val}% < 45%"},
    # Priority 3: low
    {"key": "soil", "threshold": 800, "op": "<", "device": "pump", "value": 0, "priority": 3,
     "reason": "土壤已湿: {val} < 800, 停止浇水"},
]

ANTI_FLUTTER_SECONDS = 30


class ControlEngine:
    """Evaluates sensor data against local rules, produces K230 UDP commands."""

    def __init__(self, k230_addr: tuple | None = None):
        self._k230_addr = k230_addr
        self._last_cmd_time: dict[str, float] = {}   # device → last command timestamp
        self._device_state: dict[str, object] = {}    # device → current value
        self._llm_override: list[dict] | None = None  # LLM-injected commands
        self._llm_advisor = None                      # LLMAdvisor instance
        self._last_reasons: list[str] = []

    def update_k230_addr(self, addr: tuple) -> None:
        self._k230_addr = addr

    def set_llm_advisor(self, advisor) -> None:
        """Wire in an LLMAdvisor for intelligent decision-making."""
        self._llm_advisor = advisor

    def set_llm_override(self, commands: list[dict]) -> None:
        """LLM advisor injects decision commands. Cleared after one evaluate() call."""
        self._llm_override = commands

    def evaluate(self, data: dict, analysis_summary: dict) -> list[dict]:
        """Evaluate sensor data and return list of K230 command dicts to send."""

        # If LLM override is active, use it (with safety filtering)
        if self._llm_override is not None:
            cmds = self._apply_safety(self._llm_override)
            self._llm_override = None
            self._last_reasons = ["LLM 建议"]
            for c in cmds:
                self._device_state[c.get("d", c.get("device", "unknown"))] = c.get("v", c.get("brightness", "?"))
                self._last_cmd_time[c.get("d", c.get("device", ""))] = time.time()
            return cmds

        commands = []
        reasons = []

        for rule in sorted(LOCAL_RULES, key=lambda r: r["priority"]):
            key = rule["key"]
            val = data.get(key)
            if val is None:
                continue

            threshold = rule["threshold"]
            triggered = False
            if rule["op"] == ">" and val > threshold:
                triggered = True
            elif rule["op"] == "<" and val < threshold:
                triggered = True

            if not triggered:
                continue

            # Anti-flutter check (skip for P0)
            if rule["priority"] > 0:
                last = self._last_cmd_time.get(rule["device"], 0)
                if time.time() - last < ANTI_FLUTTER_SECONDS:
                    continue

            # Compute value
            value = rule["value"]
            if callable(value):
                value = value(val)

            commands.append({"device": rule["device"], "value": value})
            reason = rule["reason"].format(val=val)
            reasons.append(reason)
            self._last_cmd_time[rule["device"]] = time.time()

        # Update state tracking
        for c in commands:
            dev = c["device"]
            val = c["value"]
            if isinstance(val, dict):
                self._device_state[dev] = val.get("brightness", val)
            else:
                self._device_state[dev] = val

        self._last_reasons = reasons
        return self._to_k230_format(commands)

    def _apply_safety(self, commands: list[dict]) -> list[dict]:
        """Apply hard safety limits to commands."""
        safe = []
        for c in commands:
            d = c.get("d", "")
            if d in SAFETY_LIMITS and "v" in c:
                c = dict(c)
                c["v"] = min(c["v"], SAFETY_LIMITS[d])
            # LED brightness cap
            if d == "led" and "brightness" in c:
                c = dict(c)
                c["brightness"] = min(c["brightness"], SAFETY_LIMITS["led_brightness"])
            safe.append(c)
        return safe

    def _to_k230_format(self, commands: list[dict]) -> list[dict]:
        """Convert internal commands to K230 JSON format."""
        result = []
        for c in commands:
            dev = c["device"]
            val = c["value"]
            if dev == "led" and isinstance(val, dict):
                result.append({"d": "led", **val})
            else:
                result.append({"d": dev, "v": val})
        return result

    def get_status(self) -> dict:
        """Return current device states for display."""
        return dict(self._device_state)

    def get_last_reasons(self) -> list[str]:
        return list(self._last_reasons)
