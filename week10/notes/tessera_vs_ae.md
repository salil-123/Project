# Tessera vs Alpha Earth timing (#5) — IIT Delhi + Sanjay Van (acacia)

Measured live: 20x20 = 400 points, year 2024. Tessera tiles fetched this run: 0 (~0 MB).

| stage | Tessera | Alpha Earth |
|-------|--------:|------------:|
| download | ~29 s / tile (151 MB @ 5.2 MB/s)* | n/a (server-side) |
| sample   | 31.4 s | 4.1 s |
| train    | 0.52 s (RF 128-d) | 0.03 s (LinearSVC 64-d) |
| classify | 39.9 s (soft-vote grid) | 8.0 s (band-math tiles) |
| **total** | **71.9 s** | **12.1 s** |

\* the benchmark run's tile was already cached (0 MB that run); the download figure is a separately
measured fresh pull of one 0.1° tile (151 MB in 29.4 s, 5.2 MB/s here). An AOI spanning several tiles
multiplies this. So first-touch on a new area adds ~30 s/tile before any classification even starts.

**Takeaway.** Tessera's cost is dominated by the ~150 MB/tile local download (a one-time hit, then cached) plus local sampling; Alpha Earth downloads nothing and both sampling and the classify render happen server-side in Earth Engine (the classify is band-math tiles, not a point grid). Training is comparable once features are in hand. So for browsing anywhere, AE wins on first-touch latency; Tessera only pays off when you need its 128-d local features and have already paid the download.