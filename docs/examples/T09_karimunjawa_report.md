# AutoSolar pre-feasibility study: Karimunjawa

Question: Is solar plus battery worth it for Karimunjawa? The island runs on diesel.

Run cbf756b46b12a736. Labels: measured (service data saved with the run), computed (this run), paper, docs, assumed.

## Answer

- site lat deg: -5.8796 deg (docs)
- site lon deg: 110.4329 deg (docs)
- weather spread pct: 18.4 % (computed)
- demand kwh yr: 9,568,110 kWh/yr (computed)
- demand peak kw: 1,422 kW (paper)
- best pv kwp: 7,750 kWp (computed)
- best battery kwh: 19,000 kWh (computed)
- best battery kw: 4,750 kW (computed)
- best lcoe usd per kwh: 0.235 USD/kWh (computed)
- best npc usd: 22,054,923 USD (computed)
- best capex usd: 13,925,000 USD (computed)
- best renewable pct: 87.5 % (computed)
- best curtailed pct: 15.1 % (computed)
- best fuel l yr: 482,413 L/yr (computed)
- best co2 t yr: 1,293 t/yr (computed)
- diesel only lcoe usd per kwh: 0.355 USD/kWh (computed)
- diesel only fuel l yr: 3,653,468 L/yr (computed)
- diesel only co2 t yr: 9,791 t/yr (computed)
- fuel saved l yr: 3,171,055 L/yr (computed)
- co2 saved t yr: 8,498 t/yr (computed)
- lcoe change pct: -33.8 % (computed)
- break even fuel usd per l: 0.21 USD/L (computed)
- api cost usd: 0.00013 USD (computed)

## Weather sources

| Case | Year | GHI kWh/m2/yr (measured) | Yield kWh/kWp/yr (computed) | PR (computed) | G3 passed |
|---|---|---|---|---|---|
| CAMS | 2018 | 1,731 | 1,353 | 0.77 | yes |
| NASA POWER | 2020 | 1,826 | 1,424 | 0.77 | yes |
| PVGIS-ERA5 TMY | none | 2,049 | 1,603 | 0.78 | yes |
| GSA scaled | 2018 | 1,829 | 1,428 | 0.77 | yes |

## Range of the answer

| Weather | Demand | PV kWp | Battery kWh | LCOE USD/kWh | LCOE of the main design USD/kWh | Note |
|---|---|---|---|---|---|---|
| CAMS | paper | 7,750 | 19,000 | 0.235 | 0.235 |  |
| NASA POWER | paper | 7,500 | 19,000 | 0.224 | 0.224 |  |
| PVGIS-ERA5 TMY | paper | 6,750 | 19,000 | 0.201 | 0.204 |  |
| GSA scaled | paper | 7,500 | 19,000 | 0.230 | 0.230 |  |
| CAMS | tourist season | 7,750 | 19,000 | 0.236 | 0.236 |  |
| CAMS | growth | 9,000 | 22,000 | 0.233 | 0.237 |  |

## Sensitivity

| Input | Factor | LCOE of the main design USD/kWh | Least cost PV kWp | Least cost battery kWh | Least cost LCOE USD/kWh | Same design | Note |
|---|---|---|---|---|---|---|---|
| pv_capex_usd_per_kwp | 0.80 | 0.219 | 8,250 | 19,000 | 0.219 | no |  |
| pv_capex_usd_per_kwp | 1.20 | 0.251 | 7,500 | 19,000 | 0.250 | no |  |
| battery_capex_usd_per_kwh | 0.80 | 0.219 | 7,750 | 19,000 | 0.219 | yes |  |
| battery_capex_usd_per_kwh | 1.20 | 0.251 | 7,750 | 19,000 | 0.251 | yes |  |
| fuel_price_usd_per_l | 0.80 | 0.226 | 7,250 | 19,000 | 0.226 | no |  |
| fuel_price_usd_per_l | 1.20 | 0.243 | 8,250 | 19,000 | 0.243 | no |  |
| discount_rate_frac | 0.80 | 0.217 | 8,000 | 19,000 | 0.217 | no |  |
| discount_rate_frac | 1.20 | 0.253 | 7,500 | 19,000 | 0.252 | no |  |
| demand | 0.80 | 0.262 | 6,250 | 15,000 | 0.239 | no |  |
| demand | 1.20 | 0.238 | 9,000 | 23,000 | 0.232 | no |  |

## Checks

| Gate | Scope | Passed | Detail |
|---|---|---|---|
| G3 PV physics | CAMS | yes | yield kWh/kWp 1353.29, PR 0.7733115084634804 |
| G3 PV physics | NASA POWER | yes | yield kWh/kWp 1424.06, PR 0.7726481173782533 |
| G3 PV physics | PVGIS-ERA5 TMY | yes | yield kWh/kWp 1603.41, PR 0.7765870553549006 |
| G3 PV physics | GSA scaled | yes | yield kWh/kWp 1428.24, PR 0.771323045456913 |
| G1 energy balance | main design | yes | max hourly gap kW: pv 0, load 0, diesel 0 |
| G2 battery | main design | yes | soc band kWh [1900, 19000], discharge kWh 4.85662e+06 against stored kWh 4.85662e+06 |
| G4 diesel | main design | yes | worst margin kW above min load: 0 |
| G5 weather spread | weather | yes | range required: True, weather rows in range: 4 |
| G7 grid edge | main design | yes | grid widened 2 times |
| G8 LCOE twins | main design | yes | max twin gap frac: 1.05076e-15 |

## Inputs

| Name | Value | Unit | Label | Note |
|---|---|---|---|---|
| pv_capex_usd_per_kwp | 1000.0 | USD/kWp | assumed | remote island install, including transport |
| pv_om_usd_per_kwp_yr | 15.0 | USD/kWp/yr | assumed |  |
| pv_life_yr | 25 | yr | assumed |  |
| battery_capex_usd_per_kwh | 300.0 | USD/kWh | assumed | LFP energy part |
| battery_power_capex_usd_per_kw | 100.0 | USD/kW | assumed | inverter part |
| battery_om_usd_per_kwh_yr | 5.0 | USD/kWh/yr | assumed |  |
| battery_life_yr | 12 | yr | assumed |  |
| diesel_om_usd_per_kwh | 0.03 | USD/kWh | assumed | existing plant; capital cost treated as sunk |
| fuel_price_usd_per_l | 0.85 | USD/L | assumed | delivered to the island |
| discount_rate_frac | 0.08 | frac | assumed | real |
| project_life_yr | 20 | yr | assumed |  |
| currency_year | 2025 | year | assumed |  |
| battery_round_trip_eff_frac | 0.9 | frac | assumed | AC to AC |
| battery_soc_min_frac | 0.1 | frac | assumed |  |
| battery_soc_initial_frac | 0.5 | frac | assumed |  |
| battery_duration_h | 4.0 | h | assumed | battery kW = kWh / duration |
| diesel_unit_kw | 1800.0 | kW | paper | Hiron et al. 2021 p7: 2 x 1.8 MW (p1 and Table 1 print 2 x 2.7 MW) |
| diesel_n_units | 2 | units | paper | Hiron et al. 2021 p7 |
| diesel_min_load_frac | 0.3 | frac | assumed | share of the rating of the units online |
| fuel_intercept_l_per_h_per_kw_rated | 0.08 | L/h per kW rated | assumed | straight line fuel curve |
| fuel_slope_l_per_kwh | 0.25 | L/kWh | assumed | straight line fuel curve |
| co2_kg_per_l | 2.68 | kg/L | assumed | diesel combustion only |
| unserved_max_frac | 0.001 | frac | assumed | largest share of load left unserved |
| rf_target_frac | 0.5 | frac | assumed | renewable share for the high renewable design |
| swing_frac | 0.2 | frac | assumed | sensitivity swing |
| pv_kwp_step | 250.0 | kWp | assumed | search grid |
| pv_kwp_max | 4000.0 | kWp | assumed | search grid, widened when the answer sits on the edge |
| battery_kwh_step | 1000.0 | kWh | assumed | search grid |
| battery_kwh_max | 16000.0 | kWh | assumed | search grid, widened when the answer sits on the edge |

## Sources

- Hiron et al. 2021, Energies 14, 8311, Table 6 (p19), doi:10.3390/en14248311
- OpenStreetMap Nominatim (data OpenStreetMap contributors, ODbL)
- Weather sources: CAMS, NASA POWER, PVGIS-ERA5 TMY, GSA scaled
- CAMS case: temperature and wind from NASA POWER 2018
- GSA scaled case: CAMS 2018 hourly shape scaled to the GSA long term annual GHI
- PVGIS-ERA5 TMY case: months from different years, stamped 1990 by pvlib
