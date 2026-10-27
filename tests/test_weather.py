"""Acceptance tests for T05 (autosolar/weather.py). Written by the orchestrator. No network: fakes only."""
import json
import math
import pathlib

import numpy as np
import pandas as pd
import pytest
from pvlib import location

from autosolar.pv import simulate_pv
from autosolar.weather import (CASE_NAMES, RANGE_REQUIRED_PCT, YEAR_FROM, YEAR_TO, WeatherCases, WeatherFetchers,
                               annual_totals_cams_monthly, annual_totals_nasa_monthly, build_weather_cases,
                               cached_fetchers, default_fetchers, ghi_from_pvlib, gsa_annual_ghi_kwh_m2,
                               meteo_from_pvlib, scale_ghi_to_annual, spread_pct, weather_table,
                               year_closest_to_mean)

FIX = pathlib.Path(__file__).parent / "fixtures" / "weather"
LAT, LON = -5.85, 110.43
EMAIL = "someone@example.org"


def read_frame(name):
    d = pd.read_csv(FIX / name, index_col=0)
    d.index = pd.to_datetime(d.index, utc=True)
    return d


def read_json(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def cams_monthly_real():
    return pd.read_csv(FIX / "cams_monthly_2016_2024.csv", index_col=0, parse_dates=True)


# ---------- constants ----------

def test_constants():
    assert (YEAR_FROM, YEAR_TO) == (2016, 2024)
    assert RANGE_REQUIRED_PCT == 10.0
    assert CASE_NAMES == ("CAMS", "NASA POWER", "PVGIS-ERA5 TMY", "GSA scaled")


# ---------- hourly frames (real saved responses, first 48 rows) ----------

@pytest.mark.parametrize("name", ["cams_hourly_2020_head.csv", "nasa_hourly_2020_head.csv", "pvgis_tmy_head.csv"])
def test_ghi_from_real_frames(name):
    df = read_frame(name)
    g = ghi_from_pvlib(df)
    assert isinstance(g, pd.Series) and g.name == "ghi_w_m2" and g.dtype == np.float64
    assert g.index.equals(df.index)
    assert np.allclose(g.to_numpy(), df["ghi"].to_numpy())


@pytest.mark.parametrize("name", ["nasa_hourly_2020_head.csv", "pvgis_tmy_head.csv"])
def test_meteo_from_real_frames(name):
    df = read_frame(name)
    m = meteo_from_pvlib(df)
    assert list(m.columns) == ["temp_air_degc", "wind_speed_m_s"]
    assert m.index.equals(df.index)
    assert np.allclose(m["temp_air_degc"], df["temp_air"]) and np.allclose(m["wind_speed_m_s"], df["wind_speed"])
    assert all(m[c].dtype == np.float64 for c in m.columns)


def test_cams_has_no_meteo():
    with pytest.raises(ValueError):
        meteo_from_pvlib(read_frame("cams_hourly_2020_head.csv"))


def bad_hourly(kind):
    df = read_frame("nasa_hourly_2020_head.csv")
    if kind == "naive":
        df.index = df.index.tz_localize(None)
    elif kind == "half_hour":
        df.index = pd.date_range("2020-01-01", periods=len(df), freq="30min", tz="UTC")
    elif kind == "gap":
        df = df.drop(df.index[5])
    elif kind == "short":
        df = df.iloc[:23]
    elif kind == "nan":
        df.iloc[3, df.columns.get_loc("ghi")] = math.nan
    elif kind == "fill":
        df.iloc[3, df.columns.get_loc("ghi")] = -999.0
    elif kind == "huge":
        df.iloc[3, df.columns.get_loc("ghi")] = 1600.0
    elif kind == "no_ghi":
        df = df.drop(columns="ghi")
    elif kind == "text":
        df["ghi"] = "x"
    elif kind == "not_frame":
        return df["ghi"]
    return df


@pytest.mark.parametrize("kind", ["naive", "half_hour", "gap", "short", "nan", "fill", "huge", "no_ghi", "text",
                                  "not_frame"])
def test_ghi_rejects(kind):
    with pytest.raises(ValueError):
        ghi_from_pvlib(bad_hourly(kind))


@pytest.mark.parametrize("col, value", [("temp_air", 75.0), ("temp_air", math.nan), ("wind_speed", -999.0),
                                        ("wind_speed", 61.0)])
def test_meteo_rejects(col, value):
    df = read_frame("nasa_hourly_2020_head.csv")
    df.iloc[4, df.columns.get_loc(col)] = value
    with pytest.raises(ValueError):
        meteo_from_pvlib(df)


def test_weather_table_order_and_index_check():
    df = read_frame("nasa_hourly_2020_head.csv")
    w = weather_table(ghi_from_pvlib(df), meteo_from_pvlib(df))
    assert list(w.columns) == ["ghi_w_m2", "temp_air_degc", "wind_speed_m_s"]
    assert w.index.equals(df.index)
    other = read_frame("pvgis_tmy_head.csv")
    with pytest.raises(ValueError):
        weather_table(ghi_from_pvlib(df), meteo_from_pvlib(other))


# ---------- annual totals (real saved responses) ----------

def test_nasa_monthly_real():
    t = annual_totals_nasa_monthly(read_json("nasa_monthly_2016_2024.json"))
    assert list(t) == list(range(2016, 2025))
    assert t[2020] == pytest.approx(4.9886 * 366)
    assert t[2019] == pytest.approx(5.394 * 365)
    assert sum(t.values()) / 9 == pytest.approx(1823.94, abs=0.01)
    assert year_closest_to_mean(t) == 2020


def test_nasa_monthly_rejects():
    p = read_json("nasa_monthly_2016_2024.json")
    p["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]["201813"] = -999.0
    with pytest.raises(ValueError):
        annual_totals_nasa_monthly(p)
    p = read_json("nasa_monthly_2016_2024.json")
    p["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"] = {k: v for k, v in
                                                         p["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"].items()
                                                         if not k.endswith("13")}
    with pytest.raises(ValueError):
        annual_totals_nasa_monthly(p)
    with pytest.raises(ValueError):
        annual_totals_nasa_monthly({"properties": {}})


def test_cams_monthly_real():
    t = annual_totals_cams_monthly(cams_monthly_real())
    assert list(t) == list(range(2016, 2025))
    assert t[2020] == pytest.approx(1680.235, abs=0.001)
    assert sum(t.values()) / 9 == pytest.approx(1701.646, abs=0.001)
    assert year_closest_to_mean(t) == 2020


def test_cams_monthly_aware_index_same_result():
    df = cams_monthly_real()
    df.index = df.index.tz_localize("UTC")
    assert annual_totals_cams_monthly(df)[2020] == pytest.approx(1680.235, abs=0.001)


@pytest.mark.parametrize("kind", ["drop_month", "nan", "neg"])
def test_cams_monthly_rejects(kind):
    df = cams_monthly_real()
    if kind == "drop_month":
        df = df.drop(df.index[30])
    elif kind == "nan":
        df.iloc[30, df.columns.get_loc("ghi")] = math.nan
    else:
        df.iloc[30, df.columns.get_loc("ghi")] = -1.0
    with pytest.raises(ValueError):
        annual_totals_cams_monthly(df)


def test_gsa_real_and_rejects():
    assert gsa_annual_ghi_kwh_m2(read_json("gsa_lta.json")) == pytest.approx(1776.8203125)
    for bad in ({}, {"annual": {"data": {"GHI": None}}}, {"annual": {"data": {"GHI": 0}}},
                {"annual": {"data": {"GHI": math.nan}}}, {"annual": {"data": {"GHI": "1776"}}}):
        with pytest.raises(ValueError):
            gsa_annual_ghi_kwh_m2(bad)


def test_year_rule():
    assert year_closest_to_mean({2016: 10.0, 2017: 20.0, 2018: 31.0}) == 2017
    assert year_closest_to_mean({2019: 1.0, 2017: 3.0}) == 2017
    for bad in ({}, {2016: math.nan}, {2016: math.inf, 2017: 1.0}):
        with pytest.raises(ValueError):
            year_closest_to_mean(bad)


def test_spread():
    four = {"PVGIS-ERA5": 2021.8, "GSA": 1776.8, "NASA POWER": 1867.1, "CAMS": 1701.6}
    assert spread_pct(four) == pytest.approx((2021.8 - 1701.6) / 1701.6 * 100)
    assert spread_pct({k: v for k, v in four.items() if k != "PVGIS-ERA5"}) == pytest.approx(9.7261, abs=1e-3)
    for bad in ({"a": 1.0}, {"a": 1.0, "b": 0.0}, {"a": 1.0, "b": math.nan}, {"a": -1.0, "b": 2.0}):
        with pytest.raises(ValueError):
            spread_pct(bad)


# ---------- synthetic full years ----------

def clear_year(year, factor=1.0, temp=27.0, wind=3.0, cols=("ghi", "temp_air", "wind_speed")):
    n = 8784 if year % 4 == 0 else 8760
    idx = pd.date_range(f"{year}-01-01", periods=n, freq="1h", tz="UTC")
    ghi = location.Location(LAT, LON).get_clearsky(idx + pd.Timedelta(minutes=30), model="haurwitz")["ghi"]
    d = pd.DataFrame({"ghi": ghi.to_numpy() * factor, "temp_air": temp, "wind_speed": wind}, index=idx)
    return d[list(cols)]


def test_scale_ghi_to_annual():
    w = weather_table(ghi_from_pvlib(clear_year(2021)), meteo_from_pvlib(clear_year(2021)))
    s = scale_ghi_to_annual(w, 1776.8)
    assert s["ghi_w_m2"].sum() / 1000 == pytest.approx(1776.8)
    assert s.index.equals(w.index) and list(s.columns) == list(w.columns)
    assert (s["temp_air_degc"] == w["temp_air_degc"]).all() and (s["wind_speed_m_s"] == w["wind_speed_m_s"]).all()
    assert w["ghi_w_m2"].sum() / 1000 == pytest.approx(clear_year(2021)["ghi"].sum() / 1000)
    for target in (0.0, -5.0, math.nan, 10000.0):
        with pytest.raises(ValueError):
            scale_ghi_to_annual(w, target)
    zero = w.copy()
    zero["ghi_w_m2"] = 0.0
    with pytest.raises(ValueError):
        scale_ghi_to_annual(zero, 1700.0)


def cams_monthly_frame(totals):
    rows = []
    for y, tot in totals.items():
        for m in range(1, 13):
            rows.append((pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0), tot * 1000.0 / 12))
    return pd.DataFrame({"ghi": [r[1] for r in rows]}, index=pd.DatetimeIndex([r[0] for r in rows]))


def nasa_monthly_payload(totals):
    p = {}
    for y, tot in totals.items():
        p[f"{y}13"] = tot / (366 if y % 4 == 0 else 365)
        for m in range(1, 13):
            p[f"{y}{m:02d}"] = 5.0
    return {"properties": {"parameter": {"ALLSKY_SFC_SW_DWN": p}}}


YEARS = list(range(2016, 2025))
CAMS_TOT = dict(zip(YEARS, [1590.0, 1670.0, 1740.0, 1820.0, 1700.0, 1620.0, 1610.0, 1820.0, 1760.0]))  # mean 1703.3
NASA_TOT = dict(zip(YEARS, [1755.0, 1782.0, 1847.0, 1969.0, 1700.0, 1777.0, 1706.0, 1927.0, 1826.0]))  # mean 1809.9


class Fakes:
    def __init__(self, cams_tot=CAMS_TOT, nasa_tot=NASA_TOT):
        self.calls = []
        self.cams_tot, self.nasa_tot = cams_tot, nasa_tot

    def fetchers(self):
        return WeatherFetchers(cams_monthly=self.cams_monthly, cams_hourly=self.cams_hourly,
                               nasa_monthly=self.nasa_monthly, nasa_hourly=self.nasa_hourly,
                               pvgis_tmy=self.pvgis_tmy, gsa=self.gsa)

    def cams_monthly(self, lat, lon, y0, y1, email):
        self.calls.append(("cams_monthly", lat, lon, y0, y1, email))
        return cams_monthly_frame(self.cams_tot)

    def cams_hourly(self, lat, lon, year, email):
        self.calls.append(("cams_hourly", lat, lon, year, email))
        return clear_year(year, 0.62, cols=("ghi",))

    def nasa_monthly(self, lat, lon, y0, y1):
        self.calls.append(("nasa_monthly", lat, lon, y0, y1))
        return nasa_monthly_payload(self.nasa_tot)

    def nasa_hourly(self, lat, lon, year):
        self.calls.append(("nasa_hourly", lat, lon, year))
        return clear_year(year, 0.70, temp=28.0 + (year - 2016) * 0.1, wind=4.0)

    def pvgis_tmy(self, lat, lon):
        self.calls.append(("pvgis_tmy", lat, lon))
        return clear_year(1990, 0.76, temp=27.2, wind=4.7)

    def gsa(self, lat, lon):
        self.calls.append(("gsa", lat, lon))
        return {"annual": {"data": {"GHI": 1776.8}}}


def names(calls):
    return [c[0] for c in calls]


def test_build_cases_full_flow():
    f = Fakes()
    r = build_weather_cases(LAT, LON, EMAIL, f.fetchers())
    assert isinstance(r, WeatherCases)
    assert r.basis == "CAMS"
    assert list(r.cases) == list(CASE_NAMES)
    assert r.years == {"CAMS": 2020, "NASA POWER": 2024, "PVGIS-ERA5 TMY": None, "GSA scaled": 2020}
    for k, w in r.cases.items():
        assert list(w.columns) == ["ghi_w_m2", "temp_air_degc", "wind_speed_m_s"]
        assert r.annual_ghi_kwh_m2[k] == pytest.approx(w["ghi_w_m2"].sum() / 1000)
    assert len(r.cases["CAMS"]) == 8784 and len(r.cases["PVGIS-ERA5 TMY"]) == 8760
    assert r.annual_ghi_kwh_m2["GSA scaled"] == pytest.approx(1776.8)
    assert r.gsa_annual_ghi_kwh_m2 == pytest.approx(1776.8)
    assert np.allclose(r.cases["CAMS"]["temp_air_degc"], 28.4)  # NASA POWER 2020 temperature
    assert np.allclose(r.cases["NASA POWER"]["temp_air_degc"], 28.8)  # NASA POWER 2024 temperature
    assert np.allclose(r.cases["GSA scaled"]["temp_air_degc"], r.cases["CAMS"]["temp_air_degc"])
    assert r.cams_annual_totals_kwh_m2 == pytest.approx(CAMS_TOT)
    assert r.nasa_annual_totals_kwh_m2 == pytest.approx(NASA_TOT)
    a = r.annual_ghi_kwh_m2
    assert r.spread_pct_all == pytest.approx((max(a.values()) - min(a.values())) / min(a.values()) * 100)
    b = {k: v for k, v in a.items() if k != "PVGIS-ERA5 TMY"}
    assert r.spread_pct_no_era5 == pytest.approx((max(b.values()) - min(b.values())) / min(b.values()) * 100)
    assert r.range_required is (r.spread_pct_all > 10.0)
    assert r.notes == ["CAMS case: temperature and wind from NASA POWER 2020",
                       "GSA scaled case: CAMS 2020 hourly shape scaled to the GSA long term annual GHI",
                       "PVGIS-ERA5 TMY case: months from different years, stamped 1990 by pvlib"]
    assert names(f.calls) == ["cams_monthly", "nasa_monthly", "nasa_hourly", "nasa_hourly", "cams_hourly",
                              "pvgis_tmy", "gsa"] or sorted(names(f.calls)) == sorted(
        ["cams_monthly", "nasa_monthly", "nasa_hourly", "nasa_hourly", "cams_hourly", "pvgis_tmy", "gsa"])
    assert ("cams_monthly", LAT, LON, 2016, 2024, EMAIL) in f.calls
    assert ("nasa_monthly", LAT, LON, 2016, 2024) in f.calls
    assert ("nasa_hourly", LAT, LON, 2020) in f.calls and ("nasa_hourly", LAT, LON, 2024) in f.calls
    assert ("cams_hourly", LAT, LON, 2020, EMAIL) in f.calls


def test_build_cases_same_year_calls_nasa_hourly_once():
    nasa = dict(NASA_TOT)
    nasa[2020], nasa[2024] = 1810.0, 1700.0  # now 2020 is closest to the mean
    f = Fakes(nasa_tot=nasa)
    r = build_weather_cases(LAT, LON, EMAIL, f.fetchers())
    assert r.years["NASA POWER"] == 2020
    assert names(f.calls).count("nasa_hourly") == 1
    assert np.allclose(r.cases["NASA POWER"]["temp_air_degc"], r.cases["CAMS"]["temp_air_degc"])


def test_cases_feed_the_pv_model():
    r = build_weather_cases(LAT, LON, EMAIL, Fakes().fetchers())
    yields = {k: simulate_pv(w, LAT, LON).specific_yield_kwh_kwp for k, w in r.cases.items()}
    order_ghi = sorted(r.annual_ghi_kwh_m2, key=r.annual_ghi_kwh_m2.get)
    order_yield = sorted(yields, key=yields.get)
    assert order_ghi == order_yield
    assert all(simulate_pv(w, LAT, LON).is_full_year for w in r.cases.values())


@pytest.mark.parametrize("kind", ["cams_years", "nasa_years", "email", "lat", "lon"])
def test_build_cases_rejects(kind):
    cams = {y: v for y, v in CAMS_TOT.items() if not (kind == "cams_years" and y == 2016)}
    nasa = {y: v for y, v in NASA_TOT.items() if not (kind == "nasa_years" and y == 2024)}
    f = Fakes(cams_tot=cams, nasa_tot=nasa)
    lat = 95.0 if kind == "lat" else LAT
    lon = math.nan if kind == "lon" else LON
    email = "not an address" if kind == "email" else EMAIL
    with pytest.raises(ValueError):
        build_weather_cases(lat, lon, email, f.fetchers())


def test_build_cases_mismatched_cams_and_nasa_index():
    f = Fakes()
    f.cams_hourly = lambda lat, lon, year, email: clear_year(2021, 0.62, cols=("ghi",))  # wrong year
    with pytest.raises(ValueError):
        build_weather_cases(LAT, LON, EMAIL, f.fetchers())


# ---------- fetchers ----------

def test_default_fetchers_make_no_call_on_creation():
    d = default_fetchers()
    assert isinstance(d, WeatherFetchers)
    for name in ("cams_monthly", "cams_hourly", "nasa_monthly", "nasa_hourly", "pvgis_tmy", "gsa"):
        assert callable(getattr(d, name))


def test_cached_fetchers(tmp_path):
    f = Fakes()
    c = cached_fetchers(f.fetchers(), tmp_path / "cache")
    first = c.cams_hourly(LAT, LON, 2020, EMAIL)
    again = c.cams_hourly(LAT, LON, 2020, EMAIL)
    assert names(f.calls) == ["cams_hourly"]
    assert (tmp_path / "cache" / "cams_hourly_-5.8500_110.4300_2020.csv").is_file()
    assert again.index.equals(first.index) and str(again.index.tz) == "UTC"
    assert np.allclose(again["ghi"].to_numpy(), first["ghi"].to_numpy())
    p1 = c.nasa_monthly(LAT, LON, 2016, 2024)
    p2 = c.nasa_monthly(LAT, LON, 2016, 2024)
    assert p1 == p2 and names(f.calls).count("nasa_monthly") == 1
    c.cams_monthly(LAT, LON, 2016, 2024, EMAIL)
    c.nasa_hourly(LAT, LON, 2024)
    c.pvgis_tmy(LAT, LON)
    c.gsa(LAT, LON)
    got = sorted(p.name for p in (tmp_path / "cache").iterdir())
    assert got == sorted(["cams_hourly_-5.8500_110.4300_2020.csv", "nasa_monthly_-5.8500_110.4300_2016_2024.json",
                          "cams_monthly_-5.8500_110.4300_2016_2024.csv", "nasa_hourly_-5.8500_110.4300_2024.csv",
                          "pvgis_tmy_-5.8500_110.4300.csv", "gsa_-5.8500_110.4300.json"])
    assert not any("example" in p.name for p in (tmp_path / "cache").iterdir())


def test_cached_round_trip_feeds_build(tmp_path):
    f = Fakes()
    c = cached_fetchers(f.fetchers(), tmp_path)
    r1 = build_weather_cases(LAT, LON, EMAIL, c)
    n_calls = len(f.calls)
    r2 = build_weather_cases(LAT, LON, EMAIL, c)
    assert len(f.calls) == n_calls  # second build reads only the cache
    assert r2.years == r1.years
    for k in CASE_NAMES:
        assert r2.annual_ghi_kwh_m2[k] == pytest.approx(r1.annual_ghi_kwh_m2[k])
