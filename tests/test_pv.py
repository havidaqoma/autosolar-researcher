"""Acceptance tests for T04 (autosolar/pv.py). Written by the orchestrator. No network."""
import math

import numpy as np
import pandas as pd
import pytest
from pvlib import location, solarposition

from autosolar.pv import PVDesign, PVResult, simulate_pv

LAT, LON = -5.85, 110.43
COLS = ["zenith_deg", "dni_w_m2", "dhi_w_m2", "poa_global_w_m2", "temp_cell_degc", "dc_kw", "ac_kw", "ac_kwh"]


def clear_weather(lat=LAT, lon=LON, n=8760, start="2021-01-01", tz="UTC", temp=27.0, wind=2.0):
    """Clear sky (haurwitz) GHI at the middle of each hour. Index = start of each hour."""
    idx = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    mid = idx + pd.Timedelta(minutes=30)
    ghi = location.Location(lat, lon).get_clearsky(mid, model="haurwitz")["ghi"].to_numpy()
    w = pd.DataFrame({"ghi_w_m2": ghi, "temp_air_degc": temp, "wind_speed_m_s": wind}, index=idx)
    return w.tz_convert(tz) if tz != "UTC" else w


@pytest.fixture(scope="module")
def year():
    return clear_weather()


@pytest.fixture(scope="module")
def base(year):
    return simulate_pv(year, LAT, LON)


def test_result_shape_and_columns(year, base):
    assert isinstance(base, PVResult)
    assert list(base.hourly.columns) == COLS
    assert base.hourly.index.equals(year.index)
    assert all(base.hourly[c].dtype == np.float64 for c in COLS)
    assert base.n_hours == 8760 and base.is_full_year
    assert base.pdc0_kw == 1.0 and base.pac0_kw == pytest.approx(1.0 / 1.2)


def test_clear_sky_year_pinned_values(base):
    # Measured by the orchestrator with the spec steps (see Library facts).
    assert base.specific_yield_kwh_kwp == pytest.approx(2013.1, rel=1e-3)
    assert base.performance_ratio_frac == pytest.approx(0.7529, abs=0.001)


def test_totals_are_consistent(year, base):
    h = base.hourly
    assert base.energy_ac_kwh == pytest.approx(h["ac_kwh"].sum())
    assert base.specific_yield_kwh_kwp == pytest.approx(base.energy_ac_kwh / 1.0)
    assert base.insolation_ghi_kwh_m2 == pytest.approx(year["ghi_w_m2"].sum() / 1000)
    assert base.insolation_poa_kwh_m2 == pytest.approx(h["poa_global_w_m2"].sum() / 1000)
    assert base.performance_ratio_frac == pytest.approx(base.specific_yield_kwh_kwp / base.insolation_poa_kwh_m2)
    assert (h["ac_kwh"] == h["ac_kw"]).all()


def test_azimuth_defaults_to_equator():
    w = clear_weather(n=48)
    assert PVDesign().azimuth_deg is None
    assert simulate_pv(w, LAT, LON).azimuth_deg == 0.0
    assert simulate_pv(w, 5.0, LON).azimuth_deg == 180.0
    assert simulate_pv(w, 0.0, LON).azimuth_deg == 180.0
    assert simulate_pv(w, LAT, LON, PVDesign(azimuth_deg=90.0)).azimuth_deg == 90.0


def test_north_facing_collects_more_south_of_equator(year, base):
    south = simulate_pv(year, LAT, LON, PVDesign(azimuth_deg=180.0))
    assert base.insolation_poa_kwh_m2 > south.insolation_poa_kwh_m2


def test_zenith_is_at_middle_of_hour(year, base):
    sp = solarposition.get_solarposition(year.index.tz_convert("UTC") + pd.Timedelta(minutes=30), LAT, LON)
    assert np.allclose(base.hourly["zenith_deg"].to_numpy(), sp["zenith"].to_numpy(), atol=1e-9)


def test_night_gives_zero(year, base):
    night = year["ghi_w_m2"].to_numpy() == 0
    assert night.sum() > 3000
    h = base.hourly[night]
    assert (h["poa_global_w_m2"].abs() <= 1e-9).all()
    assert (h["dc_kw"].abs() <= 1e-9).all() and (h["ac_kw"].abs() <= 1e-9).all()
    assert (base.hourly["poa_global_w_m2"] >= 0).all()


def test_erbs_split_closes(year, base):
    h = base.hourly
    day = h["zenith_deg"] < 80
    rebuilt = h["dni_w_m2"] * np.cos(np.radians(h["zenith_deg"])) + h["dhi_w_m2"]
    assert np.allclose(rebuilt[day], year["ghi_w_m2"][day], atol=1e-6)


@pytest.mark.parametrize("model", ["haydavies", "isotropic"])
def test_flat_array_sees_ghi(year, model):
    r = simulate_pv(year, LAT, LON, PVDesign(tilt_deg=0.0, transposition=model))
    day = r.hourly["zenith_deg"] < 80
    assert np.allclose(r.hourly["poa_global_w_m2"][day], year["ghi_w_m2"][day], atol=1e-6)


def test_given_dni_dhi_are_used():
    w = clear_weather(n=48)
    w["dni_w_m2"] = 0.0
    w["dhi_w_m2"] = w["ghi_w_m2"]
    r = simulate_pv(w, LAT, LON, PVDesign(tilt_deg=0.0))
    assert np.allclose(r.hourly["dni_w_m2"], 0.0)
    assert np.allclose(r.hourly["dhi_w_m2"], w["ghi_w_m2"])
    assert np.allclose(r.hourly["poa_global_w_m2"], w["ghi_w_m2"], atol=1e-6)


def test_dc_by_hand_on_flat_array(year):
    d = PVDesign(tilt_deg=0.0)
    r = simulate_pv(year, LAT, LON, d, pdc0_kw=3.0)
    h = r.hourly
    poa = h["poa_global_w_m2"].to_numpy()
    tc = 27.0 + poa / (25.0 + 6.84 * 2.0)
    assert np.allclose(h["temp_cell_degc"], tc, atol=1e-9)
    dc = 3.0 * poa / 1000.0 * (1 - 0.004 * (tc - 25.0)) * (1 - 0.14)
    assert np.allclose(h["dc_kw"], dc, atol=1e-9)


def test_ac_limits_and_clipping(year, base):
    h = base.hourly
    assert (h["ac_kw"] >= 0).all()
    assert (h["ac_kw"] <= base.pac0_kw + 1e-12).all()
    assert (h["ac_kw"] <= h["dc_kw"] + 1e-12).all()
    big = simulate_pv(year, LAT, LON, PVDesign(dc_ac_ratio=2.0))
    assert big.pac0_kw == pytest.approx(0.5)
    assert np.isclose(big.hourly["ac_kw"], 0.5).sum() > 100


def test_output_scales_with_size(year, base):
    r = simulate_pv(year, LAT, LON, pdc0_kw=2.0)
    assert np.allclose(r.hourly["ac_kw"], 2.0 * base.hourly["ac_kw"], rtol=1e-9, atol=1e-12)
    assert r.specific_yield_kwh_kwp == pytest.approx(base.specific_yield_kwh_kwp, rel=1e-9)


def test_time_zone_kept_and_results_equal():
    w_utc = clear_weather(n=72)
    w_jkt = w_utc.tz_convert("Asia/Jakarta")
    a = simulate_pv(w_utc, LAT, LON)
    b = simulate_pv(w_jkt, LAT, LON)
    assert b.hourly.index.equals(w_jkt.index)
    assert np.allclose(a.hourly["ac_kw"].to_numpy(), b.hourly["ac_kw"].to_numpy())


def test_short_series_not_full_year_and_zero_insolation():
    r = simulate_pv(clear_weather(n=48), LAT, LON)
    assert r.n_hours == 48 and not r.is_full_year
    w = clear_weather(n=24)
    w["ghi_w_m2"] = 0.0
    r0 = simulate_pv(w, LAT, LON)
    assert r0.performance_ratio_frac is None and r0.energy_ac_kwh == pytest.approx(0.0, abs=1e-9)


def test_leap_year_is_full_year():
    w = clear_weather(n=8784, start="2020-01-01")
    assert simulate_pv(w, LAT, LON).is_full_year


def bad_weather(kind):
    w = clear_weather(n=48)
    if kind == "naive":
        return w.tz_localize(None)
    if kind == "half_hour":
        w.index = pd.date_range("2021-01-01", periods=48, freq="30min", tz="UTC")
    elif kind == "gap":
        w = w.drop(w.index[10])
    elif kind == "unsorted":
        w = w.iloc[::-1]
    elif kind == "short":
        w = w.iloc[:23]
    elif kind == "no_wind":
        w = w.drop(columns="wind_speed_m_s")
    elif kind == "nan_ghi":
        w.iloc[12, 0] = math.nan
    elif kind == "neg_ghi":
        w.iloc[12, 0] = -1.0
    elif kind == "huge_ghi":
        w.iloc[12, 0] = 1600.0
    elif kind == "hot":
        w["temp_air_degc"] = 70.0
    elif kind == "only_dni":
        w["dni_w_m2"] = 100.0
    elif kind == "only_dhi":
        w["dhi_w_m2"] = 100.0
    elif kind == "not_frame":
        return w["ghi_w_m2"]
    return w


@pytest.mark.parametrize("kind", ["naive", "half_hour", "gap", "unsorted", "short", "no_wind", "nan_ghi", "neg_ghi",
                                  "huge_ghi", "hot", "only_dni", "only_dhi", "not_frame"])
def test_bad_weather_rejected(kind):
    with pytest.raises(ValueError):
        simulate_pv(bad_weather(kind), LAT, LON)


@pytest.mark.parametrize("lat, lon, pdc0", [(95.0, LON, 1.0), (LAT, 200.0, 1.0), (LAT, LON, 0.0),
                                            (LAT, LON, -1.0), (math.nan, LON, 1.0)])
def test_bad_site_or_size_rejected(lat, lon, pdc0):
    with pytest.raises(ValueError):
        simulate_pv(clear_weather(n=48), lat, lon, pdc0_kw=pdc0)


@pytest.mark.parametrize("kw", [dict(tilt_deg=95.0), dict(tilt_deg=-1.0), dict(azimuth_deg=360.0),
                                dict(azimuth_deg=-5.0), dict(dc_ac_ratio=0.0), dict(dc_ac_ratio=3.5),
                                dict(gamma_pdc_per_degc=0.001), dict(system_loss_pct=60.0),
                                dict(eta_inv_nom_frac=0.4), dict(eta_inv_nom_frac=1.1), dict(albedo_frac=1.5),
                                dict(transposition="perez"), dict(faiman_u0_w_m2_k=0.0),
                                dict(tilt_deg=math.nan)])
def test_bad_design_rejected(kw):
    with pytest.raises(ValueError):
        PVDesign(**kw)
