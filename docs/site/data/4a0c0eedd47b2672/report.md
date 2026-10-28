# AutoSolar pre-feasibility study: Karimunjawa

Question: Is solar plus battery worth it for Karimunjawa? The island runs on diesel.

Run 4a0c0eedd47b2672. Labels: measured (service data saved with the run), computed (this run), paper, docs, assumed.

## Answer

- Site latitude: -5.8796 deg (docs)
- Site longitude: 110.4329 deg (docs)
- Spread of annual sunshine across the weather sources: 18.4 % (computed)
- Annual electricity demand: 9,568,110 kWh/yr (computed)
- Peak demand: 1,422 kW (paper)
- Least cost design: PV size: 8,500 kWp (computed)
- Least cost design: battery energy: 19,000 kWh (computed)
- Least cost design: battery power: 4,750 kW (computed)
- Least cost design: cost of electricity (LCOE): 0.277 USD/kWh (computed)
- Least cost design: net present cost: 28,719,685 USD (computed)
- Least cost design: up front capital cost: 18,489,000 USD (computed)
- Least cost design: renewable share: 89.6 % (computed)
- Least cost design: PV energy curtailed: 20.7 % (computed)
- Least cost design: diesel fuel: 404,089 L/yr (computed)
- Least cost design: CO2: 1,083 t/yr (computed)
- Diesel only: cost of electricity (LCOE): 0.511 USD/kWh (computed)
- Diesel only: diesel fuel: 3,653,468 L/yr (computed)
- Diesel only: CO2: 9,791 t/yr (computed)
- Diesel fuel saved: 3,249,378 L/yr (computed)
- CO2 saved: 8,708 t/yr (computed)
- Change in cost of electricity against diesel only: -45.7 % (computed)
- Diesel price at which PV starts to pay: 0.24 USD/L (computed)
- Model API cost of this study: 0.00013 USD (computed)

## How firm is the answer

- Near tie: share above the least LCOE that still counts as a tie: 1.0 % (assumed)
- Near tie: designs within that share: 8 designs (computed)
- Near tie: smallest PV size: 7,500 kWp (computed)
- Near tie: largest PV size: 9,000 kWp (computed)
- Near tie: smallest battery: 19,000 kWh (computed)
- Near tie: largest battery: 20,000 kWh (computed)
- Least cost design: hours the diesel runs: 1,080 h/yr (computed)
- Least cost design: diesel starts: 163 starts/yr (computed)
- Least cost design: hours the battery and PV hold the grid with no diesel: 7,680 h/yr (computed)
- Reserve case: diesel units that run in every hour: 1 units (assumed)
- Reserve case: least cost PV size: 4,250 kWp (computed)
- Reserve case: least cost battery: 11,000 kWh (computed)
- Reserve case: least cost LCOE: 0.461 USD/kWh (computed)
- Reserve case: renewable share: 49.3 % (computed)
- Reserve case: diesel fuel: 2,475,347 L/yr (computed)
- Reserve case: LCOE of the main design: 0.533 USD/kWh (computed)
- Land: area set aside for the PV plant: 9.0 ha (press)
- Land: PV per hectare: 0.87 MWdc/ha (paper)
- Land: area the main design needs: 9.8 ha (computed)
- Land: largest PV that fits: 7,830 kWp (computed)
- Land: main design fits: no (computed)
- Land: least cost PV size that fits: 7,750 kWp (computed)
- Land: battery with that PV: 19,000 kWh (computed)
- Land: LCOE of that design: 0.279 USD/kWh (computed)
- Published design size: PV only: 1,244 kWp (paper)
- Published design size: LCOE: 0.477 USD/kWh (computed)
- Published design size: renewable share: 17.6 % (computed)
- Published design size: diesel fuel saved: 348,465 L/yr (computed)
- Diesel unit size check: other unit rating in the sources: 2,700 kW (paper)
- Diesel unit size check: diesel only LCOE: 0.594 USD/kWh (computed)
- Diesel unit size check: least cost PV size: 9,000 kWp (computed)
- Diesel unit size check: least cost battery: 19,000 kWh (computed)
- Diesel unit size check: least cost LCOE: 0.287 USD/kWh (computed)
- Diesel unit size check: saving against diesel only: 51.7 % (computed)
- Diesel unit size check: least cost design on the grid edge: yes (computed)
- Diesel unit size check: that design with the reserve units always on: 0.690 USD/kWh (computed)
- Diesel unit size check: reserve case PV size: 2,750 kWp (computed)
- Diesel unit size check: reserve case battery: 8,000 kWh (computed)
- Diesel unit size check: reserve case LCOE: 0.565 USD/kWh (computed)
- Battery power: highest discharge in any hour, main design: 1,422 kW (computed)
- Battery power: highest charge in any hour, main design: 4,750 kW (computed)
- Battery power: highest hour as a share of the power rating: 100.0 % (computed)
- Battery duration check: other duration (battery kWh per kW): 8.0 h (assumed)
- Battery duration check: least cost PV size: 8,500 kWp (computed)
- Battery duration check: least cost battery: 19,000 kWh (computed)
- Battery duration check: battery power rating: 2,375 kW (computed)
- Battery duration check: least cost LCOE: 0.277 USD/kWh (computed)
- Battery duration check: change against the main least cost LCOE: 0.0 % (computed)
- Battery duration check: least cost design on the grid edge: no (computed)
- Island prices: rise in PV and battery capital prices before diesel only is cheaper: 364.6 % (computed)
- Island prices: PV capital price at that point: 5,199 USD/kWp (computed)
- Island prices: battery energy capital price at that point: 1,812 USD/kWh (computed)
- Least cost design: load not served: 0 kWh/yr (computed)
- Least cost design: hours with some load not served: 0 h/yr (computed)
- Least cost design: battery discharge in full battery cycles: 263 cycles/yr (computed)
- Diesel engine hours: diesel only (hours times units running): 8,760 unit h/yr (computed)
- Diesel engine hours: least cost design: 1,080 unit h/yr (computed)
- Diesel engine hours: cut by the least cost design: 87.7 % (computed)
- Cost of the web search that sourced the inputs: 0.10367 USD (computed)
- Total model API cost behind this study: 0.10380 USD (computed)

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
| CAMS | paper | 8,500 | 19,000 | 0.277 | 0.277 |  |
| NASA POWER | paper | 8,250 | 19,000 | 0.263 | 0.263 |  |
| PVGIS-ERA5 TMY | paper | 7,250 | 19,000 | 0.233 | 0.239 |  |
| GSA scaled | paper | 8,250 | 19,000 | 0.272 | 0.272 |  |
| CAMS | tourist season | 8,500 | 20,000 | 0.280 | 0.281 |  |
| CAMS | growth | 9,000 | 23,000 | 0.276 | 0.289 | on grid edge |

## Sensitivity

| Input | Factor | LCOE of the main design USD/kWh | Least cost PV kWp | Least cost battery kWh | Least cost LCOE USD/kWh | Same design | Note |
|---|---|---|---|---|---|---|---|
| pv_capex_usd_per_kwp | 0.80 | 0.260 | 9,000 | 19,000 | 0.260 | no | on grid edge |
| pv_capex_usd_per_kwp | 1.20 | 0.295 | 8,000 | 19,000 | 0.294 | no |  |
| battery_capex_usd_per_kwh | 0.80 | 0.260 | 8,500 | 19,000 | 0.260 | yes |  |
| battery_capex_usd_per_kwh | 1.20 | 0.295 | 8,500 | 19,000 | 0.295 | yes |  |
| fuel_price_usd_per_l | 0.80 | 0.267 | 7,750 | 19,000 | 0.266 | no |  |
| fuel_price_usd_per_l | 1.20 | 0.288 | 9,000 | 19,000 | 0.288 | no | on grid edge |
| discount_rate_frac | 0.80 | 0.259 | 8,500 | 19,000 | 0.259 | yes |  |
| discount_rate_frac | 1.20 | 0.297 | 8,250 | 19,000 | 0.297 | no |  |
| demand | 0.80 | 0.308 | 7,000 | 15,000 | 0.283 | no |  |
| demand | 1.20 | 0.290 | 9,000 | 23,000 | 0.276 | no | on grid edge |

## Checks

| Gate | Scope | Passed | Detail |
|---|---|---|---|
| G3 PV physics | CAMS | yes | yield kWh/kWp 1,353, PR 0.77 |
| G3 PV physics | NASA POWER | yes | yield kWh/kWp 1,424, PR 0.77 |
| G3 PV physics | PVGIS-ERA5 TMY | yes | yield kWh/kWp 1,603, PR 0.78 |
| G3 PV physics | GSA scaled | yes | yield kWh/kWp 1,428, PR 0.77 |
| G1 energy balance | main design | yes | max hourly gap kW: pv 0, load 0, diesel 0 |
| G2 battery | main design | yes | soc band kWh [1,900, 19,000], discharge kWh 4,999,169 against stored kWh 4,999,169 |
| G4 diesel | main design | yes | worst margin kW above min load: 0.0 |
| G5 weather spread | weather | yes | range required: True, weather rows in range: 4 |
| G6 sourced inputs | inputs | yes | 3 of 10 sourced inputs checked, 0 kept assumed, 7 curated post hoc |
| G7 grid edge | main design | yes | grid widened 2 times |
| G8 LCOE twins | main design | yes | max twin gap frac: 1.5e-15 |

## Inputs

| Name | Value | Unit | Label | Note |
|---|---|---|---|---|
| pv_capex_usd_per_kwp | 1119.0 | USD/kWp | paper | S3 checked: A comparative assessment of policy induced diffusion pathways for utility scale solar PV: case study of Indonesia; https://www.frontiersin.org/journals/sustainable-energy-policy/articles/10.3389/fsuep.2024.1308441/full; quote near; as written 1119 USD/kW; currency year 2022; support judged by Muse Glimmer 30B Q4_K_M, local llama.cpp, reasoning low (votes 1 and 2) and muse-wonder-1.0 (vote 3), yes needed in all 3 votes |
| pv_om_usd_per_kwp_yr | 24.38 | USD/kWp/yr | paper | S3 checked: Techno-economic analysis of rooftop solar power plant implementation and policy on mosques: an Indonesian case study; https://www.nature.com/articles/s41598-022-08968-6; quote near; as written 24.38 US$/kW per year; support judged by Muse Glimmer 30B Q4_K_M, local llama.cpp, reasoning low (votes 1 and 2) and muse-wonder-1.0 (vote 3), yes needed in all 3 votes |
| pv_life_yr | 25 | yr | assumed |  |
| battery_capex_usd_per_kwh | 390.0 | USD/kWh | docs | S5 curated post hoc: Technology Data for the Indonesian Power Sector 2024 (Danish Energy Agency and EA Energy Analyses), data sheet Batteries - Lithium-ion (utility-scale); https://www.ea-energianalyse.dk/wp-content/uploads/2025/05/technology-data-for-the-indonesian-power-sector-2024.pdf; page 266; quote table; as written 0.35 MUSD/MWh energy component, before 0.04 other project costs; currency year 2022; energy component 0.35 plus other project costs 0.04 MUSD/MWh in the 2023 column (the printed year nearest the study); 1 MUSD/MWh = 1000 USD/kWh; USD at price level 2022 without VAT, not escalated; the same page also has a Technology specific data block with a lower expansion cost (total 1.33 MUSD/MW, so 0.33 MUSD/MWh at 4 h) that does not add up with the financial block; the higher financial block is used |
| battery_power_capex_usd_per_kw | 330.0 | USD/kW | docs | S5 curated post hoc: Technology Data for the Indonesian Power Sector 2024 (Danish Energy Agency and EA Energy Analyses), data sheet Batteries - Lithium-ion (utility-scale); https://www.ea-energianalyse.dk/wp-content/uploads/2025/05/technology-data-for-the-indonesian-power-sector-2024.pdf; page 266; quote table; as written 0.33 MUSD/MW; currency year 2022; power component 0.33 MUSD/MW in the 2023 column; 1 MUSD/MW = 1000 USD/kW; with the energy part this gives 390 + 330 / 4 = 472.5 USD/kWh for a 4 h battery, against 0.47 MUSD/MWh total investment printed on the sheet |
| battery_om_usd_per_kwh_yr | 4.48 | USD/kWh/yr | docs | S5 curated post hoc: Technology Data for the Indonesian Power Sector 2024 (Danish Energy Agency and EA Energy Analyses), data sheet Batteries - Lithium-ion (utility-scale); https://www.ea-energianalyse.dk/wp-content/uploads/2025/05/technology-data-for-the-indonesian-power-sector-2024.pdf; page 266; quote table; as written 15000 USD/MW/year; currency year 2022; fixed 15,000 USD per MW per year over the 4 h discharge time is 3.75 USD per kWh per year; variable O&M 2.00 USD/MWh at an upper bound of one full cycle a day adds 365 x 2.00 / 1000 = 0.73, so 4.48 in total (study f86df9819fa150a7 ran 249 cycles a year, computed) |
| battery_life_yr | 15 | yr | docs | S5 curated post hoc: Technology Data for the Indonesian Power Sector 2024 (Danish Energy Agency and EA Energy Analyses), data sheet Batteries - Lithium-ion (utility-scale); https://www.ea-energianalyse.dk/wp-content/uploads/2025/05/technology-data-for-the-indonesian-power-sector-2024.pdf; page 266; quote table; as written 15 years; calendar life as printed; at the 249 full cycles a year of study f86df9819fa150a7 (computed) the 7,500 cycles last 30 years, so the calendar life binds; the model replaces the battery at the end of its life |
| diesel_om_usd_per_kwh | 0.03 | USD/kWh | assumed | existing plant; capital cost treated as sunk |
| fuel_price_usd_per_l | 1.26 | USD/L | docs | S5 curated post hoc: Harga Solar Industri 01-14 Maret 2026 (Solar Industri, a fuel reseller, reposting the Pertamina Patra Niaga industrial fuel list); https://solarindustri.com/berita/harga-solar-industri-01-14-maret-2026/; quote exact; as written 1.26 USD/L; currency year 2026; median of the list's own USD/L column for wilayah 1 (Java) over the 17 half-month lists from October 2025 to September 2026 that pass the period check (the quote is one of them; range 1.03 to 1.64 USD/L; median 21,250 IDR/L), so no exchange rate is assumed; loco depot price before PPN, PPh, PBBKB and sea transport, so a floor for the island; one list value (23,050 IDR/L) matches a Pertamina Patra Niaga letter reported by Kontan (Rp 23,05 juta per KL tanpa pajak) |
| discount_rate_frac | 0.0673 | frac | docs | S5 curated post hoc: High cost of capital and limited project pipeline hinder clean energy investment in Southeast Asia (IEA commentary, Teng and Erdogan); https://www.iea.org/commentaries/high-cost-of-capital-and-limited-project-pipeline-hinder-clean-energy-investment-in-southeast-asia; quote exact; as written 9.4 % nominal; real rate (1 + 0.094) / (1 + 0.025) - 1 = 0.0673, with the 2.5% inflation target for 2025 to 2027 set in PMK No. 31 of 2024 (Bank Indonesia inflation page); the higher of two sourced real rates (IRENA, The cost of financing for renewable power, 2023, Appendix Figure A1: 6.0% real after tax for solar PV in Indonesia in 2021); a solar PV rate used for the whole system, and the IEA says batteries cost more to finance, so see the sensitivity row at 1.2 times (0.081) |
| project_life_yr | 20 | yr | assumed |  |
| currency_year | 2025 | year | assumed |  |
| battery_round_trip_eff_frac | 0.9 | frac | docs | S5 curated post hoc: Technology Data for the Indonesian Power Sector 2024 (Danish Energy Agency and EA Energy Analyses), data sheet Batteries - Lithium-ion (utility-scale); https://www.ea-energianalyse.dk/wp-content/uploads/2025/05/technology-data-for-the-indonesian-power-sector-2024.pdf; page 266; quote table; as written 90 %; 90 percent AC to AC as printed; same value as the old assumed input, now with a source |
| battery_soc_min_frac | 0.1 | frac | assumed |  |
| battery_soc_initial_frac | 0.5 | frac | assumed |  |
| battery_duration_h | 4.0 | h | assumed | battery kW = kWh / duration |
| diesel_unit_kw | 1800.0 | kW | paper | Hiron et al. 2021 p7: 2 x 1.8 MW (p1 and Table 1 print 2 x 2.7 MW) |
| diesel_n_units | 2 | units | paper | Hiron et al. 2021 p7 |
| diesel_min_load_frac | 0.25 | frac | paper | S3 checked: Design Framework of a Stand-Alone Microgrid Considering Power System Performance and Economic Efficiency; https://mdpi-res.com/d_attachment/energies/energies-14-00457/article_deploy/energies-14-00457-v2.pdf?version=1611114955; page 8; quote exact; as written 25 % of their rated power; support judged by Muse Glimmer 30B Q4_K_M, local llama.cpp, reasoning low (votes 1 and 2) and muse-wonder-1.0 (vote 3), yes needed in all 3 votes |
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

3 of 10 inputs were sourced by web search and checked: the quote was found in the fetched source, the value appears in the quote, the DOI resolves when one is given, and the support judge (Muse Glimmer 30B Q4_K_M, local llama.cpp, reasoning low (votes 1 and 2) and muse-wonder-1.0 (vote 3), yes needed in all 3 votes) agreed. The others keep their assumed value; the last column says why.

7 of 10 inputs were curated by hand after pre-registration (post hoc), from the documents named in the table. Quote match exact means the quote is word for word from the page; table means the value was read by eye from a table image and no script checked it.

| Input | Status | Value used | Unit | Label | As written | Source | URL | Page | Quote match | Why kept assumed |
|---|---|---|---|---|---|---|---|---|---|---|
| pv_capex_usd_per_kwp | checked | 1119.0 | USD/kWp | paper | 1119 USD/kW | A comparative assessment of policy induced diffusion pathways for utility scale solar PV: case study of Indonesia | https://www.frontiersin.org/journals/sustainable-energy-policy/articles/10.3389/fsuep.2024.1308441/full | 1 | near | none |
| pv_om_usd_per_kwp_yr | checked | 24.38 | USD/kWp/yr | paper | 24.38 US$/kW per year | Techno-economic analysis of rooftop solar power plant implementation and policy on mosques: an Indonesian case study | https://www.nature.com/articles/s41598-022-08968-6 | 1 | near | none |
| battery_capex_usd_per_kwh | curated | 390.0 | USD/kWh | docs | 0.35 MUSD/MWh energy component, before 0.04 other project costs | Technology Data for the Indonesian Power Sector 2024 (Danish Energy Agency and EA Energy Analyses), data sheet Batteries - Lithium-ion (utility-scale) | https://www.ea-energianalyse.dk/wp-content/uploads/2025/05/technology-data-for-the-indonesian-power-sector-2024.pdf | 266 | table | none |
| battery_om_usd_per_kwh_yr | curated | 4.48 | USD/kWh/yr | docs | 15000 USD/MW/year | Technology Data for the Indonesian Power Sector 2024 (Danish Energy Agency and EA Energy Analyses), data sheet Batteries - Lithium-ion (utility-scale) | https://www.ea-energianalyse.dk/wp-content/uploads/2025/05/technology-data-for-the-indonesian-power-sector-2024.pdf | 266 | table | none |
| fuel_price_usd_per_l | curated | 1.26 | USD/L | docs | 1.26 USD/L | Harga Solar Industri 01-14 Maret 2026 (Solar Industri, a fuel reseller, reposting the Pertamina Patra Niaga industrial fuel list) | https://solarindustri.com/berita/harga-solar-industri-01-14-maret-2026/ | none | exact | none |
| discount_rate_frac | curated | 0.0673 | frac | docs | 9.4 % nominal | High cost of capital and limited project pipeline hinder clean energy investment in Southeast Asia (IEA commentary, Teng and Erdogan) | https://www.iea.org/commentaries/high-cost-of-capital-and-limited-project-pipeline-hinder-clean-energy-investment-in-southeast-asia | none | exact | none |
| diesel_min_load_frac | checked | 0.25 | frac | paper | 25 % of their rated power | Design Framework of a Stand-Alone Microgrid Considering Power System Performance and Economic Efficiency | https://mdpi-res.com/d_attachment/energies/energies-14-00457/article_deploy/energies-14-00457-v2.pdf?version=1611114955 | 8 | exact | none |
| battery_power_capex_usd_per_kw | curated | 330.0 | USD/kW | docs | 0.33 MUSD/MW | Technology Data for the Indonesian Power Sector 2024 (Danish Energy Agency and EA Energy Analyses), data sheet Batteries - Lithium-ion (utility-scale) | https://www.ea-energianalyse.dk/wp-content/uploads/2025/05/technology-data-for-the-indonesian-power-sector-2024.pdf | 266 | table | none |
| battery_life_yr | curated | 15 | yr | docs | 15 years | Technology Data for the Indonesian Power Sector 2024 (Danish Energy Agency and EA Energy Analyses), data sheet Batteries - Lithium-ion (utility-scale) | https://www.ea-energianalyse.dk/wp-content/uploads/2025/05/technology-data-for-the-indonesian-power-sector-2024.pdf | 266 | table | none |
| battery_round_trip_eff_frac | curated | 0.9 | frac | docs | 90 % | Technology Data for the Indonesian Power Sector 2024 (Danish Energy Agency and EA Energy Analyses), data sheet Batteries - Lithium-ion (utility-scale) | https://www.ea-energianalyse.dk/wp-content/uploads/2025/05/technology-data-for-the-indonesian-power-sector-2024.pdf | 266 | table | none |

## Not covered by this study

- Grid stability: frequency and voltage control, grid forming inverters and protection for hours with no diesel running
- Land ownership, permits and the environmental review
- Site layout, shading, soil and access for construction
- Shipping to the island, local labour and construction time
- Financing terms, tariffs, subsidies and who pays
- Demand growth beyond the growth case, and new loads such as electric boats
- Battery ageing beyond the replacement rule, and salt air corrosion
- Diesel price risk beyond the sensitivity table
- Diesel overhaul and engine replacement costs, which grow with engine hours

## Sources

- Hiron et al. 2021, Energies 14, 8311, Table 6 (p19), doi:10.3390/en14248311
- OpenStreetMap Nominatim (data OpenStreetMap contributors, ODbL)
- Weather sources: CAMS, NASA POWER, PVGIS-ERA5 TMY, GSA scaled
- CAMS case: temperature and wind from NASA POWER 2018
- GSA scaled case: CAMS 2018 hourly shape scaled to the GSA long term annual GHI
- PVGIS-ERA5 TMY case: months from different years, stamped 1990 by pvlib
- Sourced input pv_capex_usd_per_kwp: A comparative assessment of policy induced diffusion pathways for utility scale solar PV: case study of Indonesia, https://www.frontiersin.org/journals/sustainable-energy-policy/articles/10.3389/fsuep.2024.1308441/full, doi:10.3389/fsuep.2024.1308441
- Sourced input pv_om_usd_per_kwp_yr: Techno-economic analysis of rooftop solar power plant implementation and policy on mosques: an Indonesian case study, https://www.nature.com/articles/s41598-022-08968-6, doi:10.1038/s41598-022-08968-6
- Curated input (post hoc) battery_capex_usd_per_kwh: Technology Data for the Indonesian Power Sector 2024 (Danish Energy Agency and EA Energy Analyses), data sheet Batteries - Lithium-ion (utility-scale), https://www.ea-energianalyse.dk/wp-content/uploads/2025/05/technology-data-for-the-indonesian-power-sector-2024.pdf, page 266
- Curated input (post hoc) battery_om_usd_per_kwh_yr: Technology Data for the Indonesian Power Sector 2024 (Danish Energy Agency and EA Energy Analyses), data sheet Batteries - Lithium-ion (utility-scale), https://www.ea-energianalyse.dk/wp-content/uploads/2025/05/technology-data-for-the-indonesian-power-sector-2024.pdf, page 266
- Curated input (post hoc) fuel_price_usd_per_l: Harga Solar Industri 01-14 Maret 2026 (Solar Industri, a fuel reseller, reposting the Pertamina Patra Niaga industrial fuel list), https://solarindustri.com/berita/harga-solar-industri-01-14-maret-2026/
- Curated input (post hoc) discount_rate_frac: High cost of capital and limited project pipeline hinder clean energy investment in Southeast Asia (IEA commentary, Teng and Erdogan), https://www.iea.org/commentaries/high-cost-of-capital-and-limited-project-pipeline-hinder-clean-energy-investment-in-southeast-asia
- Sourced input diesel_min_load_frac: Design Framework of a Stand-Alone Microgrid Considering Power System Performance and Economic Efficiency, https://mdpi-res.com/d_attachment/energies/energies-14-00457/article_deploy/energies-14-00457-v2.pdf?version=1611114955, doi:10.3390/en14020457
- Curated input (post hoc) battery_power_capex_usd_per_kw: Technology Data for the Indonesian Power Sector 2024 (Danish Energy Agency and EA Energy Analyses), data sheet Batteries - Lithium-ion (utility-scale), https://www.ea-energianalyse.dk/wp-content/uploads/2025/05/technology-data-for-the-indonesian-power-sector-2024.pdf, page 266
- Curated input (post hoc) battery_life_yr: Technology Data for the Indonesian Power Sector 2024 (Danish Energy Agency and EA Energy Analyses), data sheet Batteries - Lithium-ion (utility-scale), https://www.ea-energianalyse.dk/wp-content/uploads/2025/05/technology-data-for-the-indonesian-power-sector-2024.pdf, page 266
- Curated input (post hoc) battery_round_trip_eff_frac: Technology Data for the Indonesian Power Sector 2024 (Danish Energy Agency and EA Energy Analyses), data sheet Batteries - Lithium-ion (utility-scale), https://www.ea-energianalyse.dk/wp-content/uploads/2025/05/technology-data-for-the-indonesian-power-sector-2024.pdf, page 266
- Check input site_land_ha: PLN Indonesia Power plans about 9 hectares of land on Legon Bajak for the Karimunjawa PV plant (Tribun Jateng, interview with PLN IP engineering; the same article says permits are in process)
- Check input pv_mwdc_per_ha: Bolinger and Bolinger, Land Requirements for Utility-Scale PV, IEEE Journal of Photovoltaics, doi:10.1109/JPHOTOV.2021.3136805, Section IV: median power density of fixed-tilt US plants; low latitude sites need less row spacing, so this may overstate the land
- Check input reference_pv_kwp: Hiron 2021 design: 3889 modules of 320 Wp (p11), 0.99 MW AC; its battery size is not stated in kWh, so the check runs PV only
- Check input diesel_unit_kw_alt: Hiron 2021 prints two diesel fleet sizes: 2 x 2.7 MW on p1 and in Table 1, and 2 x 1.8 MW on p7 (the field section, with the feeder voltages); the main study uses 1.8 MW units, and this check reruns the design search with 2.7 MW units
