"""
edgr — probability calibration (Platt scaling), one curve per market.

The backtest showed edgr's probabilities are overconfident: it says "80%"
when the real rate is ~56%. Calibration corrects that with a simple, well-
known transform fit to the backtest data:

    calibrated_p = sigmoid(A * logit(raw_p) + B)

`logit` and `sigmoid` are inverses; the A and B (learned from history) gently
squeeze over-extreme probabilities back toward what actually happens. A=1, B=0
means "no change" (the safe default before a curve is fit).

Different bet types need their own curve, so we store a named set of (A, B)
pairs in models/calibration.json, e.g. "moneyline", "runline_minus" (covering
-1.5) and "runline_plus" (covering +1.5).
"""

import json
import math

from config.settings import MODELS_DIR

CAL_PATH = MODELS_DIR / "calibration.json"
_cache: dict | None = None


def _logit(p: float) -> float:
    p = min(1 - 1e-6, max(1e-6, p))
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _load_all() -> dict:
    global _cache
    if _cache is None:
        try:
            data = json.loads(CAL_PATH.read_text())
        except (FileNotFoundError, ValueError):
            data = {}
        # Back-compat: an old flat {"A":..,"B":..} file is the moneyline curve.
        if "A" in data and "moneyline" not in data:
            data = {"moneyline": {"A": data["A"], "B": data["B"]}}
        _cache = data
    return _cache


def load_params(name: str = "moneyline") -> tuple[float, float]:
    """Return (A, B) for a named curve; identity (1, 0) if not fit yet."""
    entry = _load_all().get(name)
    if not entry:
        return 1.0, 0.0
    return entry["A"], entry["B"]


def save_params(name: str, a: float, b: float) -> None:
    data = _load_all()
    data[name] = {"A": a, "B": b}
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    CAL_PATH.write_text(json.dumps(data, indent=2))


def calibrate(p: float, name: str = "moneyline") -> float:
    """Map a raw model probability to a calibrated one using a named curve."""
    a, b = load_params(name)
    if a == 1.0 and b == 0.0:
        return p            # not fit yet -> unchanged
    return _sigmoid(a * _logit(p) + b)
