# Deployment playbook

## Blue-green releases

We ship with blue-green: the green fleet takes traffic first, and rollback is
one load-balancer weight change. A release is only done when both fleets run
the same schema migration.

## Rollback criteria

Roll back when p99 latency exceeds 300 ms for five minutes, or when the error
rate doubles. Never roll back a schema migration — roll forward.

## Artifacts

Every build produces one immutable artifact; environments pull by digest, not
by tag.
