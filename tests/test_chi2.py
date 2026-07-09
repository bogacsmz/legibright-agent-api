import math
import pytest
from scipy.stats import chi2  # TEST-ONLY dependency
from app.checks.calibration_bias import _chi2_sf


@pytest.mark.parametrize("df", list(range(1, 13)))
@pytest.mark.parametrize("x", [0.0, 0.1, 0.5, 1.0, 2.0, 3.5, 5.0, 8.0, 12.0, 20.0, 30.0, 40.0])
def test_chi2_sf_matches_scipy(df, x):
    got = _chi2_sf(x, df)
    ref = float(chi2.sf(x, df))
    assert abs(got - ref) <= 1e-9, f"df={df} x={x}: {got} vs {ref}"
    if ref > 1e-12:
        assert abs(got - ref) / ref <= 1e-6


def test_chi2_sf_edges():
    assert _chi2_sf(0.0, 4) == 1.0
    assert _chi2_sf(-1.0, 4) == 1.0
    assert 0.0 < _chi2_sf(50.0, 3) < 1e-8
