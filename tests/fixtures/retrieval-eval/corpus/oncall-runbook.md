# On-call runbook

## Pager triage order

1. Is it a customer-visible outage? Check the status page first.
2. Consumer lag: the Kafka pipeline runbook covers triage.
3. Error rate spike: look at the deployment digest that went out last.

## Escalation

Primary on-call escalates to the secondary after 15 minutes without a
mitigation path. The incident commander role rotates weekly.

## Postmortems

Every Sev-1 gets a blameless postmortem within 72 hours, filed next to the
meeting notes that decided the feature.
