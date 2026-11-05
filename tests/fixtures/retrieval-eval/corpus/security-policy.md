# Security policy

## Token rotation

API tokens rotate every 90 days; the rotation ticket is automated. A token
that cannot be rotated in time is revoked, not extended.

## Secret storage

Secrets live in the vault, never in config files. The config references a
vault path; the loader resolves it at startup.

## Audit

Write-side operations are audited with actor, action, and target; audit rows
are append-only and kept for 400 days.
