# AutoSolar pre-feasibility study: Karimunjawa

Question: Is solar plus battery worth it for Karimunjawa? The island runs on diesel.

Run 9f9ac2afa1f46b43. Labels: measured (service data saved with the run), computed (this run), paper, docs, assumed.

## Answer

- Site latitude: -5.8796 deg (docs)
- Site longitude: 110.4329 deg (docs)
- Spread of annual sunshine across the weather sources: 18.4 % (computed)
- Annual electricity demand: 9,568,110 kWh/yr (computed)
- Peak demand: 1,422 kW (paper)
- Least cost design: PV size: 7,250 kWp (computed)
- Least cost design: battery energy: 19,000 kWh (computed)
- Least cost design: battery power: 4,750 kW (computed)
- Least cost design: cost of electricity (LCOE): 0.251 USD/kWh (computed)
- Least cost design: net present cost: 23,591,478 USD (computed)
- Least cost design: up front capital cost: 14,287,750 USD (computed)
- Least cost design: renewable share: 85.8 % (computed)
- Least cost design: PV energy curtailed: 11.0 % (computed)
- Least cost design: diesel fuel: 549,023 L/yr (computed)
- Least cost design: CO2: 1,471 t/yr (computed)
- Diesel only: cost of electricity (LCOE): 0.354 USD/kWh (computed)
- Diesel only: diesel fuel: 3,653,468 L/yr (computed)
- Diesel only: CO2: 9,791 t/yr (computed)
- Diesel fuel saved: 3,104,445 L/yr (computed)
- CO2 saved: 8,320 t/yr (computed)
- Change in cost of electricity against diesel only: -29.1 % (computed)
- Diesel price at which PV starts to pay: 0.27 USD/L (computed)
- Model API cost of this study: 0.00013 USD (computed)

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
| CAMS | paper | 7,250 | 19,000 | 0.251 | 0.251 |  |
| NASA POWER | paper | 7,250 | 19,000 | 0.240 | 0.240 |  |
| PVGIS-ERA5 TMY | paper | 6,750 | 19,000 | 0.215 | 0.217 |  |
| GSA scaled | paper | 7,000 | 19,000 | 0.246 | 0.246 |  |
| CAMS | tourist season | 7,500 | 19,000 | 0.251 | 0.252 |  |
| CAMS | growth | 8,500 | 22,000 | 0.249 | 0.252 |  |

## Sensitivity

| Input | Factor | LCOE of the main design USD/kWh | Least cost PV kWp | Least cost battery kWh | Least cost LCOE USD/kWh | Same design | Note |
|---|---|---|---|---|---|---|---|
| pv_capex_usd_per_kwp | 0.80 | 0.235 | 7,750 | 19,000 | 0.234 | no |  |
| pv_capex_usd_per_kwp | 1.20 | 0.268 | 7,000 | 19,000 | 0.268 | no |  |
| battery_capex_usd_per_kwh | 0.80 | 0.235 | 7,250 | 19,000 | 0.235 | yes |  |
| battery_capex_usd_per_kwh | 1.20 | 0.267 | 7,250 | 19,000 | 0.267 | yes |  |
| fuel_price_usd_per_l | 0.80 | 0.241 | 5,000 | 11,000 | 0.240 | no |  |
| fuel_price_usd_per_l | 1.20 | 0.261 | 7,750 | 19,000 | 0.260 | no |  |
| discount_rate_frac | 0.80 | 0.233 | 7,500 | 19,000 | 0.233 | no |  |
| discount_rate_frac | 1.20 | 0.269 | 7,250 | 19,000 | 0.269 | yes |  |
| demand | 0.80 | 0.278 | 6,000 | 15,000 | 0.256 | no |  |
| demand | 1.20 | 0.253 | 8,500 | 23,000 | 0.248 | no |  |

## Checks

| Gate | Scope | Passed | Detail |
|---|---|---|---|
| G3 PV physics | CAMS | yes | yield kWh/kWp 1,353, PR 0.77 |
| G3 PV physics | NASA POWER | yes | yield kWh/kWp 1,424, PR 0.77 |
| G3 PV physics | PVGIS-ERA5 TMY | yes | yield kWh/kWp 1,603, PR 0.78 |
| G3 PV physics | GSA scaled | yes | yield kWh/kWp 1,428, PR 0.77 |
| G1 energy balance | main design | yes | max hourly gap kW: pv 0, load 0, diesel 0 |
| G2 battery | main design | yes | soc band kWh [1,900, 19,000], discharge kWh 4,725,626 against stored kWh 4,725,626 |
| G4 diesel | main design | yes | worst margin kW above min load: 0.0 |
| G5 weather spread | weather | yes | range required: True, weather rows in range: 4 |
| G6 sourced inputs | inputs | yes | 4 of 7 sourced inputs checked, 3 kept assumed |
| G7 grid edge | main design | yes | grid widened 2 times |
| G8 LCOE twins | main design | yes | max twin gap frac: 8.5e-16 |

## Inputs

| Name | Value | Unit | Label | Note |
|---|---|---|---|---|
| pv_capex_usd_per_kwp | 1119.0 | USD/kWp | paper | S3 checked: A comparative assessment of policy induced diffusion pathways for utility scale solar PV: case study of Indonesia; https://www.frontiersin.org/journals/sustainable-energy-policy/articles/10.3389/fsuep.2024.1308441/full; quote near; as written 1119 USD/kW; currency year 2022; support judged by Muse Glimmer 30B Q4_K_M, local llama.cpp, reasoning low |
| pv_om_usd_per_kwp_yr | 24.38 | USD/kWp/yr | paper | S3 checked: Techno-economic analysis of rooftop solar power plant implementation and policy on mosques: an Indonesian case study; https://www.nature.com/articles/s41598-022-08968-6; quote near; as written 24.38 US$/kW per year; support judged by Muse Glimmer 30B Q4_K_M, local llama.cpp, reasoning low |
| pv_life_yr | 25 | yr | assumed |  |
| battery_capex_usd_per_kwh | 300.0 | USD/kWh | assumed | LFP energy part |
| battery_power_capex_usd_per_kw | 100.0 | USD/kW | assumed | inverter part |
| battery_om_usd_per_kwh_yr | 5.0 | USD/kWh/yr | assumed |  |
| battery_life_yr | 12 | yr | assumed |  |
| diesel_om_usd_per_kwh | 0.03 | USD/kWh | assumed | existing plant; capital cost treated as sunk |
| fuel_price_usd_per_l | 0.848485 | USD/L | docs | S3 checked: National Strategy for Climate Mitigation: Private Sector Circular Use of Palm Oil Mill Waste; https://ap.fftc.org.tw/article/3866; quote exact; as written 14000 IDR per liter; fx 16500 IDR per USD assumed; support judged by Muse Glimmer 30B Q4_K_M, local llama.cpp, reasoning low; found on search try 2 |
| discount_rate_frac | 0.08 | frac | assumed | real |
| project_life_yr | 20 | yr | assumed |  |
| currency_year | 2025 | year | assumed |  |
| battery_round_trip_eff_frac | 0.9 | frac | assumed | AC to AC |
| battery_soc_min_frac | 0.1 | frac | assumed |  |
| battery_soc_initial_frac | 0.5 | frac | assumed |  |
| battery_duration_h | 4.0 | h | assumed | battery kW = kWh / duration |
| diesel_unit_kw | 1800.0 | kW | paper | Hiron et al. 2021 p7: 2 x 1.8 MW (p1 and Table 1 print 2 x 2.7 MW) |
| diesel_n_units | 2 | units | paper | Hiron et al. 2021 p7 |
| diesel_min_load_frac | 0.25 | frac | paper | S3 checked: Design Framework of a Stand-Alone Microgrid Considering Power System Performance and Economic Efficiency; https://mdpi-res.com/d_attachment/energies/energies-14-00457/article_deploy/energies-14-00457-v2.pdf?version=1611114955; page 8; quote exact; as written 25 % of their rated power; support judged by Muse Glimmer 30B Q4_K_M, local llama.cpp, reasoning low |
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

## Sourced inputs

4 of 7 inputs were sourced by web search and checked: the quote was found in the fetched source, the value appears in the quote, the DOI resolves when one is given, and the support judge (Muse Glimmer 30B Q4_K_M, local llama.cpp, reasoning low) agreed. The others keep their assumed value; the last column says why.

| Input | Status | Value used | Unit | Label | As written | Source | URL | Page | Quote match | Why kept assumed |
|---|---|---|---|---|---|---|---|---|---|---|
| pv_capex_usd_per_kwp | checked | 1119.0 | USD/kWp | paper | 1119 USD/kW | A comparative assessment of policy induced diffusion pathways for utility scale solar PV: case study of Indonesia | https://www.frontiersin.org/journals/sustainable-energy-policy/articles/10.3389/fsuep.2024.1308441/full | 1 | near | none |
| pv_om_usd_per_kwp_yr | checked | 24.38 | USD/kWp/yr | paper | 24.38 US$/kW per year | Techno-economic analysis of rooftop solar power plant implementation and policy on mosques: an Indonesian case study | https://www.nature.com/articles/s41598-022-08968-6 | 1 | near | none |
| battery_capex_usd_per_kwh | assumed | 300.0 | USD/kWh | assumed | 192 USD/kWh | Energy Storage Cost-of-service Tool 2.0 | https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2017/Oct/IRENA_DAT_Cost-of-service_Tool_2025.pdf | 1 | exact | try 1: fetch: HTTP 403; try 2: judge says not supported: The quote states system-level battery storage costs fell to USD 192/kWh in 2024, not specifically the installed capital cost of a lithium-ion battery energy storage system per kWh. |
| battery_om_usd_per_kwh_yr | assumed | 5.0 | USD/kWh/yr | assumed | 50 USD/kWh/year | Life Cycle Analysis of Energy Storage Technologies: A Comparative Study | https://www.e3s-conferences.org/articles/e3sconf/pdf/2024/67/e3sconf_sdea2024_08004.pdf | none | not run | value 50 USD/kWh/yr outside band [0.5, 30]; fetch: HTTP 403; mirror: no open copy with the quote (3 tried) |
| fuel_price_usd_per_l | checked | 0.848485 | USD/L | docs | 14000 IDR per liter | National Strategy for Climate Mitigation: Private Sector Circular Use of Palm Oil Mill Waste | https://ap.fftc.org.tw/article/3866 | 1 | exact | none |
| discount_rate_frac | assumed | 0.08 | frac | assumed | 2.03 % | Life Cycle Cost Analysis of PV-Wind-Battery Hybrid Power System at PLN Nusantara Power Brantas Generation Unit Tulungagung | https://jaree.its.ac.id/jaree/article/download/550/233/2157 | none | not run | try 1: fetch: HTTP 403; try 2: fetch: ConnectionError |
| diesel_min_load_frac | checked | 0.25 | frac | paper | 25 % of their rated power | Design Framework of a Stand-Alone Microgrid Considering Power System Performance and Economic Efficiency | https://mdpi-res.com/d_attachment/energies/energies-14-00457/article_deploy/energies-14-00457-v2.pdf?version=1611114955 | 8 | exact | none |

## Sources

- Hiron et al. 2021, Energies 14, 8311, Table 6 (p19), doi:10.3390/en14248311
- OpenStreetMap Nominatim (data OpenStreetMap contributors, ODbL)
- Weather sources: CAMS, NASA POWER, PVGIS-ERA5 TMY, GSA scaled
- CAMS case: temperature and wind from NASA POWER 2018
- GSA scaled case: CAMS 2018 hourly shape scaled to the GSA long term annual GHI
- PVGIS-ERA5 TMY case: months from different years, stamped 1990 by pvlib
- Sourced input pv_capex_usd_per_kwp: A comparative assessment of policy induced diffusion pathways for utility scale solar PV: case study of Indonesia, https://www.frontiersin.org/journals/sustainable-energy-policy/articles/10.3389/fsuep.2024.1308441/full, doi:10.3389/fsuep.2024.1308441
- Sourced input pv_om_usd_per_kwp_yr: Techno-economic analysis of rooftop solar power plant implementation and policy on mosques: an Indonesian case study, https://www.nature.com/articles/s41598-022-08968-6, doi:10.1038/s41598-022-08968-6
- Sourced input fuel_price_usd_per_l: National Strategy for Climate Mitigation: Private Sector Circular Use of Palm Oil Mill Waste, https://ap.fftc.org.tw/article/3866
- Sourced input diesel_min_load_frac: Design Framework of a Stand-Alone Microgrid Considering Power System Performance and Economic Efficiency, https://mdpi-res.com/d_attachment/energies/energies-14-00457/article_deploy/energies-14-00457-v2.pdf?version=1611114955, doi:10.3390/en14020457
