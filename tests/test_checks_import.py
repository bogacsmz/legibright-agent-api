from app.checks.base import Finding, Severity, Verdict
from app.checks.temporal_leakage import TemporalLeakageCheck
from app.checks.target_leakage import TargetLeakageCheck
from app.checks.group_leakage import GroupLeakageCheck
from app.checks.overfit_flags import OverfitFlagsCheck
from app.checks.calibration_bias import CalibrationBiasCheck


def test_severity_members():
    assert {s.value for s in Severity} == {"OK", "WARN", "FAIL"}


def test_temporal_fail_and_ok():
    fail = TemporalLeakageCheck().run(train_ts=[1, 2, 3], test_ts=[2, 3, 4])
    ok = TemporalLeakageCheck().run(train_ts=[1, 2, 3], test_ts=[4, 5, 6])
    assert fail.severity is Severity.FAIL
    assert ok.severity is Severity.OK


def test_overfit_hero_fail():
    f = OverfitFlagsCheck().run(in_sample=0.99, holdout=0.74)
    assert f.severity is Severity.FAIL
