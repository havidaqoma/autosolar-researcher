# Twin test of the checking step (post hoc)

Post hoc test, written after the studies. Each checked or curated value is given to the checker again with its number moved by 1%, 10% and 30%, down and up. The script check needs the claimed number inside the quote. The local judge (votes 1 and 2 in a study) sees the claimed value, the quote, the source title and URL; here the quote stands in for the source text around it. The Wonder vote (vote 3 in a study) is not run, to keep Meta model spending at zero. In a study a value is used only if every check passes.

Judge: Muse Glimmer 30B Q4_K_M, local llama.cpp, reasoning low. Votes per twin: 3. Items: 10. Twins: 70.

| Number given to the checker | Twins | Script: number not in the quote | Local judge, single votes: not yes | Local judge, votes 1 and 2 as in a study: not yes |
|---|---|---|---|---|
| True value | 10 | 0 of 10 | 3 of 30 | 2 of 10 |
| Moved 1% | 20 | 20 of 20 | 60 of 60 | 20 of 20 |
| Moved 10% | 20 | 20 of 20 | 60 of 60 | 20 of 20 |
| Moved 30% | 20 | 20 of 20 | 60 of 60 | 20 of 20 |

## Items

- i01: pv_capex_usd_per_kwp (checked, study 107477f112e5d92c): 1119 USD/kW; quote: "The unsubsidised initial CAPEX in 2022 value is set at 1,119 USD/kW (IEA, )."
- i02: pv_om_usd_per_kwp_yr (checked, study 107477f112e5d92c): 24.38 US$/kW per year; quote: "Darghouth et al. estimated that the CAPEX and OPEX for SPP in Indonesia is 1365.76 US$ and 24.38 US$/kW per year."
- i03: battery_capex_usd_per_kwh (curated, study 107477f112e5d92c): 0.35 MUSD/MWh energy component, before 0.04 other project costs; quote: "Batteries - Lithium-ion (utility-scale), column 2023: - energy component (MUSD/MWh) 0.35; - other project costs (MUSD/MWh) 0.04; uncertainty (2023) of the energy component 0.26 to 0.38"
- i04: battery_om_usd_per_kwh_yr (curated, study 107477f112e5d92c): 15000 USD/MW/year; quote: "Batteries - Lithium-ion (utility-scale), column 2023: Fixed O&M (USD/MW/year) 15,000; Discharge time (hours) 4; Variable O&M (USD/MWh) 2.00"
- i05: discount_rate_frac (curated, study 107477f112e5d92c): 9.4 % nominal; quote: "The median weighted average cost of capital (WACC, nominal, post-tax and in local currency) for solar PV in Indonesia, Viet Nam and the Philippines based on survey responses was 9.4%, 9.0% and 8.0% re"
- i06: diesel_min_load_frac (checked, study 107477f112e5d92c): 25 % of their rated power; quote: "When RES generation is greater than the load demand, online diesel generators operate at their minimum loading condition, which is typically 25% of their rated power."
- i07: battery_power_capex_usd_per_kw (curated, study 107477f112e5d92c): 0.33 MUSD/MW; quote: "Batteries - Lithium-ion (utility-scale), column 2023: - power component (MUSD/MW) 0.33; uncertainty (2023) 0.24 to 0.35"
- i08: battery_life_yr (curated, study 107477f112e5d92c): 15 years; quote: "Batteries - Lithium-ion (utility-scale), column 2023: Technical lifetime (years) 15; Technical lifetime (cycles) 7,500"
- i09: battery_round_trip_eff_frac (curated, study 107477f112e5d92c): 90 %; quote: "Batteries - Lithium-ion (utility-scale), column 2023: Round-trip efficiency (%) AC 90"
- i10: fuel_price_usd_per_l (checked, study 5ee65dcd3350bec1): 14000 IDR per liter; quote: "Assuming the current industrial diesel price is around IDR 14,000 (US$ 0.84) per liter, the potential financial savings could exceed IDR 4 billion (US$ 238.73 million) per year per installation unit."

## Skipped

- fuel_price_usd_per_l (curated, study 107477f112e5d92c): value not in quote
