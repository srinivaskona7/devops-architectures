---
title: SLO-based alerting and burn rates
minutes: 60
objectives:
  - Define SLIs, SLOs and the error budget with real numbers
  - Compute burn rate and the multiwindow thresholds 14.4, 6 and 1
  - Write the Prometheus rules that implement them
---
Threshold alerts on CPU or error counts are noisy. SLO alerting asks one question: are we spending our error budget too fast?

@concept SLI, SLO and error budget
@plain
An **SLI** is a measured ratio of good events. An **SLO** is the target for it over a window. The **error budget** is the allowed failure: 100 percent minus the SLO.
@problem
"Make it as reliable as possible" has infinite cost. A target lets you balance reliability against shipping features.
@does
- SLO 99.9 percent over 30 days gives an error budget of 0.1 percent.
- In time: 30 days × 24 × 60 = 43 200 minutes; 0.001 × 43 200 = 43.2 minutes of full outage.
- In requests: at 10 million requests per day, 30 days is 300 million; 0.001 × 300 million = 300 000 failed requests allowed.
- SLO 99.99 percent shrinks the budget to 4.32 minutes. SLO 99 percent gives 432 minutes.
@diagram flow
caption: From SLI to budget
nodes:
  - "SLI|good divided by total|info"
  - "SLO|99.9 percent in 30 days|cp"
  - "Error budget|0.1 percent = 43.2 minutes|warn"
  - "Policy|freeze releases when spent|bad"
@check
Budget for a 99.95 percent SLO over 30 days? || 0.0005 × 43 200 = 21.6 minutes.
@end

@concept Burn rate
@plain
**Burn rate** is how fast you consume the error budget compared to a pace that would use exactly all of it at the end of the window. Burn rate 1 spends the budget exactly in 30 days.
@problem
An error ratio of 0.5 percent is trivial against a 99 percent SLO but a disaster against 99.99 percent. Burn rate gives one scale for all SLOs.
@does
- Burn rate = observed error ratio ÷ allowed error ratio (1 − SLO).
- Example: SLO 99.9 percent allows 0.001. Observed 0.0144 gives burn rate 0.0144 ÷ 0.001 = 14.4.
- Time to exhaustion = window ÷ burn rate. At 14.4, 30 days ÷ 14.4 = 2.08 days (about 50 hours).
- At burn rate 1000 the budget is gone in 43.2 minutes.
@diagram cmp
caption: Burn rate meaning for a 30 day window
cards:
  - {h: "Burn rate 1", kind: ok, items: ["Budget lasts 30 days", "Normal"]}
  - {h: "Burn rate 6", kind: warn, items: ["Budget lasts 5 days", "Ticket or slow page"]}
  - {h: "Burn rate 14.4", kind: bad, items: ["Budget lasts about 2 days", "Page now"]}
@end

@concept The budget fraction behind 14.4, 6 and 3
@plain
The famous numbers come from choosing how much of the monthly budget one alert may consume before it fires.
@problem
You need thresholds with a clear meaning instead of guesses.
@does
- Budget consumed = burn rate × alert window ÷ SLO window (720 hours for 30 days).
- 14.4 over 1 hour: 14.4 × 1 ÷ 720 = 2 percent of the budget.
- 6 over 6 hours: 6 × 6 ÷ 720 = 5 percent.
- 3 over 3 days (72 hours): 3 × 72 ÷ 720 = 30 percent. Burn rate 1 over 3 days: 10 percent.
- So a page means "2 percent of the monthly budget gone in an hour".
@diagram flow
caption: The arithmetic
numbered: true
nodes:
  - "Pick budget share|2 percent in 1 hour|info"
  - "Multiply|0.02 × 720 ÷ 1|app"
  - "Burn rate|14.4|bad"
@check
Burn rate to consume 5 percent of the budget in 6 hours? || 0.05 × 720 ÷ 6 = 6.
@end

@concept Multiwindow multi-burn-rate alerts
@plain
Each alert checks two windows: a long one for significance and a short one (about one twelfth of it) to confirm the problem is still happening.
@problem
A single long window keeps alerting for an hour after the issue is fixed. A single short window pages on blips.
@does
- Page: burn rate above 14.4 over 1 hour AND over 5 minutes.
- Page: burn rate above 6 over 6 hours AND over 30 minutes.
- Ticket: burn rate above 3 over 1 day AND over 2 hours (or 6 over 3 days).
- Ticket: burn rate above 1 over 3 days AND over 6 hours.
- With SLO 99.9 percent the error-ratio thresholds are 14.4 × 0.001 = 0.0144, 6 × 0.001 = 0.006, 3 × 0.001 = 0.003 and 0.001.
@diagram layers
caption: Alert levels for a 99.9 percent SLO
layers:
  - {label: "Page", nodes: ["1h and 5m|ratio above 0.0144|bad", "6h and 30m|ratio above 0.006|bad"]}
  - {label: "Ticket", nodes: ["1d and 2h|ratio above 0.003|warn", "3d and 6h|ratio above 0.001|warn"]}
@end

@concept Recording rules for SLI windows
@plain
Compute the error ratio once per window with recording rules, then compare to thresholds.
@problem
Evaluating a 3-day rate directly inside every alert is expensive.
@does
- Create `sli:error_ratio:rate5m`, `rate30m`, `rate1h`, `rate6h`, `rate1d`, `rate3d` per service.
- Keep the label set small (service).
- Alert rules then reference the recorded series.
@diagram flow
caption: Rules feed alerts
nodes:
  - "Raw counters|http_requests_total|plain"
  - "Recording rules|ratios for 6 windows|warn"
  - "Alert rules|compare with burn thresholds|bad"
@h Recording rules
```yaml title="rules/slo-recording.yml"
groups:
  - name: slo-checkout-ratios
    rules:
      - record: sli:error_ratio:rate5m
        expr: |
          sum by (service) (rate(http_requests_total{code=~"5.."}[5m]))
          / sum by (service) (rate(http_requests_total[5m]))
      - record: sli:error_ratio:rate30m
        expr: |
          sum by (service) (rate(http_requests_total{code=~"5.."}[30m]))
          / sum by (service) (rate(http_requests_total[30m]))
      - record: sli:error_ratio:rate1h
        expr: |
          sum by (service) (rate(http_requests_total{code=~"5.."}[1h]))
          / sum by (service) (rate(http_requests_total[1h]))
      - record: sli:error_ratio:rate6h
        expr: |
          sum by (service) (rate(http_requests_total{code=~"5.."}[6h]))
          / sum by (service) (rate(http_requests_total[6h]))
```
@end

@concept Burn rate alert rules
@plain
The final alerts compare the recorded ratios with the thresholds for the service's SLO.
@problem
You need rules you can copy, test and adapt.
@does
- Threshold = burn rate × (1 − SLO). For 99.9 percent: 14.4 × 0.001 = 0.0144.
- Both windows must exceed the threshold (`and`).
- Use `for: 2m` for page alerts to absorb evaluation jitter.
- Tools such as Sloth and Pyrra generate these rules from a short SLO definition; check the current docs.
@diagram flow
caption: Two windows must agree
nodes:
  - "1h ratio above 0.0144|significant|info"
  - "and|both true|plain"
  - "5m ratio above 0.0144|still happening|warn"
  - "Page|fires|bad"
@h Alert rules
```yaml title="rules/slo-alerts.yml"
groups:
  - name: slo-checkout-alerts
    rules:
      - alert: ErrorBudgetBurnFast
        expr: |
          sli:error_ratio:rate1h{service="checkout"} > (14.4 * 0.001)
          and
          sli:error_ratio:rate5m{service="checkout"} > (14.4 * 0.001)
        for: 2m
        labels: {severity: page, slo: checkout-availability}
        annotations:
          summary: "Checkout burns 2 percent of the monthly budget per hour"
          runbook_url: https://runbooks.example.com/high-error-ratio
      - alert: ErrorBudgetBurnSlow
        expr: |
          sli:error_ratio:rate6h{service="checkout"} > (6 * 0.001)
          and
          sli:error_ratio:rate30m{service="checkout"} > (6 * 0.001)
        for: 15m
        labels: {severity: page, slo: checkout-availability}
        annotations:
          summary: "Checkout burns 5 percent of the monthly budget in 6 hours"
```
@end

@concept Worked example and error budget policy
@plain
Walk through a real incident with the numbers, then agree what the team does when the budget runs out.
@problem
An SLO without a consequence is decoration.
@does
- Incident: from 10:00 to 10:20 half of checkout requests fail (error ratio 0.5), the rest of the month is perfect. Burn rate = 0.5 ÷ 0.001 = 500.
- The 5m window passes 0.0144 at once; the 1h window averages 0.5 × 20 ÷ 60 = 0.167, also above. The page fires within the first few minutes.
- Budget used: 20 minutes × 0.5 = 10 minutes of full outage out of 43.2 allowed, so about 23 percent.
- Policy example: below 25 percent budget left, prioritise reliability work; at zero, freeze feature releases until recovered.
@diagram flow
caption: Incident accounting
numbered: true
nodes:
  - "Half of requests fail|20 minutes|bad"
  - "Burn rate 500|0.5 divided by 0.001|warn"
  - "Budget used|10 of 43.2 minutes, 23 percent|info"
  - "Policy|reliability work first|ok"
@h Check the arithmetic
```python title="burn_rate_math.py" lab
slo = 0.999
budget = 1 - slo
window_min = 30 * 24 * 60
print("budget minutes", round(budget * window_min, 1))
for rate, hours in [(14.4, 1), (6, 6), (3, 72), (1, 72)]:
    print(rate, hours, "h ->", round(rate * hours / 720 * 100, 1), "percent of budget")
err = 0.5
print("incident burn", err / budget, "budget used percent", round(err * 20 / (budget * window_min) * 100, 1))
```
@end
