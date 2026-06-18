"""
edgr — fit probability calibration from the season backtest.

Runs the leak-free walk-forward backtest, then fits Platt scaling so the
model's stated probabilities match reality, and saves the result for the live
model to use. Prints a before/after reliability table so you can see the fix.

RUN:  python -m scripts.calibrate
"""

from datetime import date, timedelta

import numpy as np
from scipy.stats import poisson
from sklearn.linear_model import LogisticRegression

from scripts.backtest_pitcher import fetch_games, collect_predictions
from models.calibration import save_params, _logit, _sigmoid


def _reliability(probs, outcomes, label) -> None:
    print(f"\n{label}")
    print(f"   {'Predicted':<12}{'Games':<8}{'Actual win%'}")
    for lo in [round(x * 0.1, 1) for x in range(0, 10)]:
        idx = [(lo <= p < lo + 0.1) for p in probs]
        n = sum(idx)
        if n >= 20:
            wins = sum(o for o, keep in zip(outcomes, idx) if keep)
            print(f"   {lo*100:>3.0f}-{(lo+0.1)*100:>3.0f}%   {n:<8}{wins/n*100:>6.1f}%")


def main() -> None:
    start = date(date.today().year, 3, 1)
    end = date.today() - timedelta(days=1)
    print(f"Backtesting {start} → {end} to fit calibration...")
    games = fetch_games(start, end)
    preds, _ = collect_predictions(games)

    def fit(name, probs, outcomes):
        """Fit + save one Platt curve, return calibrated probabilities."""
        x = np.array([_logit(p) for p in probs]).reshape(-1, 1)
        lr = LogisticRegression().fit(x, np.array(outcomes))
        a, b = float(lr.coef_[0][0]), float(lr.intercept_[0])
        save_params(name, a, b)
        print(f"\n✅ {name}: A={a:.3f}, B={b:.3f}  (A<1 = was overconfident)")
        return np.array([_sigmoid(a * _logit(p) + b) for p in probs])

    # 1) Moneyline.
    ml_raw = [p["p_home"] for p in preds]
    ml_y = [int(p["home_won"]) for p in preds]
    ml_cal = fit("moneyline", ml_raw, ml_y)
    _reliability(ml_raw, ml_y, "  BEFORE moneyline:")
    _reliability(ml_cal, ml_y, "  AFTER moneyline:")

    # 2) Run line — home covers -1.5 (won by 2+).
    rm_raw = [p["q_minus"] for p in preds]
    rm_y = [int(p["home_margin"] >= 2) for p in preds]
    rm_cal = fit("runline_minus", rm_raw, rm_y)
    _reliability(rm_raw, rm_y, "  BEFORE run line -1.5:")
    _reliability(rm_cal, rm_y, "  AFTER run line -1.5:")

    # 3) Run line — home covers +1.5 (lost by 1 or won).
    rp_raw = [p["q_plus"] for p in preds]
    rp_y = [int(p["home_margin"] >= -1) for p in preds]
    fit("runline_plus", rp_raw, rp_y)

    # 4) Totals — over probability, pooled across a range of lines per game so
    #    we get a spread of probabilities to calibrate (no market lines needed).
    tot_probs, tot_y = [], []
    for p in preds:
        lam, actual = p["proj_total"], p["actual_total"]
        for line in (6.5, 7.5, 8.5, 9.5, 10.5, 11.5):
            tot_probs.append(float(1 - poisson.cdf(int(line), lam)))
            tot_y.append(int(actual > line))
    tot_cal = fit("total_over", tot_probs, tot_y)
    _reliability(tot_probs, tot_y, "  BEFORE totals (over):")
    _reliability(tot_cal, tot_y, "  AFTER totals (over):")

    print("\nAll calibration curves saved to models/calibration.json.")


if __name__ == "__main__":
    main()
