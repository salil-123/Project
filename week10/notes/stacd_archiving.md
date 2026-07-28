# #14 — Aaditeshwar's STACD archiving / deployment email

Two threads in the mail. Short version: **defer the heavy parts to the deployment week; ship only the
cheap forward-looking hook now.**

## Thread 1 — "not all STAC runs need to be archived"

Sir's point: routing every run through STACD is right, but test runs generate STAC items that
shouldn't all be retained. There should be a **user signal to archive**, tied to the data-sharing
policy, and the data-management service should later clean up the unflagged test items and keep only
the sharable ones. His own line: *"No change to be done for now but eventually we should simplify
this."*

**What we did (the cheap half):** the STACD emit now carries an `archive` flag —
`GET /api/stacd?...&archive=true` sets `properties.archive` on the output STAC item (`src/stacd.py`).
That's the "checkbox from the user" made expressible: a run can now *declare* whether it's a keeper or
a test. It's emit-only — we do **not** build the retention/cleanup service, since that lives in the
shared data-management layer, not our emitter, and sir said not to change anything there yet.

**Deferred (correctly):** the actual cleanup policy (which service prunes unflagged items, how the
data-sharing consent is captured, TTLs for test items). That's cross-project (drones + bioacoustics +
LULC) and belongs to the deployment/data-management effort, not this week.

## Thread 2 — workstation + dockerize

The earlier part of the chain (set the project up on act4dws5, dockerize per the usual protocol,
Anunay/Susmit to show their STAC/STACD generation) is the **deployment week** work, and it lines up
with week10 #2/#9 which sir also deferred ("this leave it for next time cause this week i would test
everything out properly"). Nothing to build now; the STACD side is already emitting specs Anunay/
Susmit can diff against theirs (see `week10/notes/stacd_audit.md`).

## Recommendation
Defer both threads to the deployment week. The only thing worth having ready — a per-output archive
signal — is now in place, so when the data-management cleanup is built it has a field to read. No
further action this week beyond documenting it here.
