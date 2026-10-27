"""Acceptance tests for T06 (autosolar/demand.py). Written by the orchestrator. No network."""
import math

import numpy as np
import pandas as pd
import pytest

from autosolar.demand import (HIRON_2021_BASE_YEAR, HIRON_2021_DAILY_KWH_STATED, HIRON_2021_GROWTH_FRAC_PER_YR,
                              HIRON_2021_LOAD_KW, HIRON_2021_PEAK_KW_STATED, HIRON_2021_SOURCE, LOCAL_TZ,
                              DemandCase, build_demand_cases, check_daily_profile, daily_profile_to_hourly)

YEAR_2020 = pd.date_range("2020-01-01", periods=8784, freq="1h", tz="UTC")
YEAR_1990 = pd.date_range("1990-01-01", periods=8760, freq="1h", tz="UTC")


def test_constants():
    assert len(HIRON_2021_LOAD_KW) == 24 and isinstance(HIRON_2021_LOAD_KW, tuple)
    assert sum(HIRON_2021_LOAD_KW) == 26214
    assert max(HIRON_2021_LOAD_KW) == 1422 and HIRON_2021_LOAD_KW[19] == 1422
    assert HIRON_2021_LOAD_KW[0] == 1126 and HIRON_2021_LOAD_KW[23] == 1195
    assert HIRON_2021_DAILY_KWH_STATED == 26479.0 and HIRON_2021_PEAK_KW_STATED == 1422.0
    assert HIRON_2021_GROWTH_FRAC_PER_YR == 0.0348 and HIRON_2021_BASE_YEAR == 2022
    assert LOCAL_TZ == "Asia/Jakarta"
    assert "10.3390/en14248311" in HIRON_2021_SOURCE and "Table 6" in HIRON_2021_SOURCE


def test_check_daily_profile_passes_on_paper():
    check_daily_profile(HIRON_2021_LOAD_KW, HIRON_2021_DAILY_KWH_STATED, HIRON_2021_PEAK_KW_STATED)
    check_daily_profile(list(HIRON_2021_LOAD_KW), 26214.0, 1422.0, tol_frac=0.0)


@pytest.mark.parametrize("profile, daily, peak, tol", [
    (HIRON_2021_LOAD_KW, HIRON_2021_DAILY_KWH_STATED, HIRON_2021_PEAK_KW_STATED, 0.005),  # 1.0% off daily
    (HIRON_2021_LOAD_KW, 26214.0, 1500.0, 0.02),  # peak off 5.2%
    (HIRON_2021_LOAD_KW[:23], 26214.0, 1422.0, 0.02),
    (HIRON_2021_LOAD_KW + (1.0,), 26214.0, 1422.0, 0.02),
    ((-1.0,) + HIRON_2021_LOAD_KW[1:], 26214.0, 1422.0, 0.5),
    ((math.nan,) + HIRON_2021_LOAD_KW[1:], 26214.0, 1422.0, 0.5),
    ((True,) + HIRON_2021_LOAD_KW[1:], 26214.0, 1422.0, 0.5),
    (HIRON_2021_LOAD_KW, 0.0, 1422.0, 0.02),
    (HIRON_2021_LOAD_KW, 26214.0, math.inf, 0.02),
    (HIRON_2021_LOAD_KW, 26214.0, 1422.0, 0.6),
])
def test_check_daily_profile_rejects(profile, daily, peak, tol):
    with pytest.raises(ValueError):
        check_daily_profile(profile, daily, peak, tol_frac=tol)


def test_hourly_mapping_uses_local_time():
    s = daily_profile_to_hourly(HIRON_2021_LOAD_KW, YEAR_2020)
    assert isinstance(s, pd.Series) and s.name == "load_kw" and s.dtype == np.float64
    assert s.index.equals(YEAR_2020)
    # 2020-01-01 00:00 UTC is 07:00 WIB, so the value is the 07:00 row (1004 kW)
    assert s.iloc[0] == 1004.0
    # 12:00 UTC is 19:00 WIB: the evening peak
    assert s.loc["2020-06-15 12:00+00:00"] == 1422.0
    # 17:00 UTC is 00:00 WIB of the next local day
    assert s.loc["2020-03-03 17:00+00:00"] == 1126.0
    assert s.sum() == pytest.approx(26214 * 366)
    assert s.max() == 1422.0


def test_hourly_mapping_other_zone_and_index_tz():
    idx = YEAR_1990.tz_convert("Asia/Jakarta")
    s = daily_profile_to_hourly(HIRON_2021_LOAD_KW, idx)
    assert s.index.equals(idx)
    assert s.iloc[0] == 1004.0  # still 07:00 local
    s_utc = daily_profile_to_hourly(HIRON_2021_LOAD_KW, YEAR_1990, local_tz="UTC")
    assert s_utc.iloc[0] == 1126.0


@pytest.mark.parametrize("kind", ["naive", "short", "half_hour_steps", "gap", "half_hour_zone", "list"])
def test_hourly_mapping_rejects(kind):
    idx, tz = YEAR_2020, LOCAL_TZ
    if kind == "naive":
        idx = YEAR_2020.tz_localize(None)
    elif kind == "short":
        idx = YEAR_2020[:23]
    elif kind == "half_hour_steps":
        idx = pd.date_range("2020-01-01", periods=48, freq="30min", tz="UTC")
    elif kind == "gap":
        idx = YEAR_2020.delete(10)
    elif kind == "half_hour_zone":
        tz = "Asia/Kolkata"
    elif kind == "list":
        idx = list(YEAR_2020[:48])
    with pytest.raises(ValueError):
        daily_profile_to_hourly(HIRON_2021_LOAD_KW, idx, local_tz=tz)


def test_build_cases_defaults():
    cases = build_demand_cases(YEAR_2020)
    assert list(cases) == ["paper", "tourist season", "growth"]
    paper, season, growth = cases["paper"], cases["tourist season"], cases["growth"]
    for c in cases.values():
        assert isinstance(c, DemandCase)
        assert c.load_kw.name == "load_kw" and c.load_kw.dtype == np.float64 and c.load_kw.index.equals(YEAR_2020)
        assert c.source == HIRON_2021_SOURCE
        assert c.annual_kwh == pytest.approx(c.load_kw.sum())
        assert c.peak_kw == pytest.approx(c.load_kw.max())
        assert isinstance(c.notes, tuple) and len(c.notes) == 1
    assert paper.label == "paper" and season.label == "assumed scenario" and growth.label == "assumed scenario"
    assert paper.name == "paper" and season.name == "tourist season" and growth.name == "growth"
    assert paper.annual_kwh == pytest.approx(26214 * 366)
    assert paper.notes == ("profile repeated every day; local hour in Asia/Jakarta",)
    factor = 1.0348 ** 5
    assert np.allclose(growth.load_kw.to_numpy(), paper.load_kw.to_numpy() * factor)
    assert growth.notes == ("growth 3.48% per year from 2022 to 2027",)
    assert growth.peak_kw == pytest.approx(1422 * factor)
    local_month = YEAR_2020.tz_convert("Asia/Jakarta").month
    in_season = np.isin(local_month, [6, 7, 8, 12])
    ratio = season.load_kw.to_numpy() / paper.load_kw.to_numpy()
    assert np.allclose(ratio[in_season], 1.15) and np.allclose(ratio[~in_season], 1.0)
    assert season.notes == ("season months [6, 7, 8, 12], uplift 15.0% (assumed)",)
    # 30 Nov 17:00 UTC is 1 Dec 00:00 local (in season); one hour earlier is still 30 Nov local
    assert season.load_kw.loc["2020-11-30 17:00+00:00"] == pytest.approx(1126.0 * 1.15)
    assert season.load_kw.loc["2020-11-30 16:00+00:00"] == pytest.approx(1195.0)


def test_build_cases_custom_inputs():
    cases = build_demand_cases(YEAR_1990, season_months=[12, 1], season_uplift_frac=0.0, growth_frac_per_yr=0.0,
                               base_year=2022, target_year=2022)
    assert np.allclose(cases["tourist season"].load_kw, cases["paper"].load_kw)
    assert np.allclose(cases["growth"].load_kw, cases["paper"].load_kw)
    assert cases["tourist season"].notes == ("season months [12, 1], uplift 0.0% (assumed)",)
    assert cases["growth"].notes == ("growth 0.00% per year from 2022 to 2022",)
    assert cases["paper"].annual_kwh == pytest.approx(26214 * 365)


@pytest.mark.parametrize("kw", [
    {"season_months": ()}, {"season_months": (0,)}, {"season_months": (13,)}, {"season_months": (6, 6)},
    {"season_months": (6.0,)}, {"season_uplift_frac": -0.1}, {"season_uplift_frac": 1.5},
    {"season_uplift_frac": math.nan}, {"growth_frac_per_yr": 0.25}, {"growth_frac_per_yr": -0.01},
    {"base_year": 2028}, {"target_year": 2027.0}, {"base_year": True},
    {"profile_kw": HIRON_2021_LOAD_KW[:12]},
])
def test_build_cases_rejects(kw):
    with pytest.raises(ValueError):
        build_demand_cases(YEAR_2020, **kw)
