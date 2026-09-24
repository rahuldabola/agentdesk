# Cloud Cost Management

## Budgets

Each team has a monthly cloud budget set during annual planning. An alert fires at 80% of budget
and again at 100%. Overspend above 10% of budget requires a written explanation to the finance
partner in the following month's review.

## Tagging

Every cloud resource carries `team`, `service`, and `env` tags. Untagged resources are reported
weekly, and resources that remain untagged for 30 days are scheduled for deletion after the owning
account is notified.

## Savings

Steady-state compute is covered by one-year committed-use discounts, reviewed each quarter.
Non-production environments scale to zero outside 08:00–20:00 on weekdays unless a team opts out
with a reason. Idle load balancers and unattached disks are cleaned up automatically after 14 days.

## Cost Reviews

Teams whose spend grows more than 25% quarter over quarter present the cause at the monthly cost
review. Growth that tracks customer growth is expected; growth that does not is investigated.
