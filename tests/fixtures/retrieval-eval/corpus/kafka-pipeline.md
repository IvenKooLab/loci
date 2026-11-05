# Kafka streaming pipeline

## Partitioning

Events are keyed by customer id into 24 partitions. Re-keying requires a
topic migration, so choose keys carefully at design time.

## Consumer lag alarms

Page at consumer lag > 60 s sustained for five minutes. The on-call
runbook has the triage order: check the consumer group, then brokers, then
producers.

## Exactly-once

We use idempotent producers plus transactional reads; at-least-once with
dedup at ingest is acceptable for analytics topics.
