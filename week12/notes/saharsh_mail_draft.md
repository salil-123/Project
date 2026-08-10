# Draft reply to Saharsh

> Draft only — review and send from your own mail. Optionally CC Susmit.

---

**Subject:** LULC model — ready to onboard into STACD (image + repo + draft YAMLs)

Hi Saharsh,

I've gone through the STACD material and dockerized our LULC classifier so it's ready to plug into the
framework. Everything's public and running:

- **Docker image:** `docker pull salil2003/corestack-lulc:latest` (FastAPI service, boots on port 8000,
  health at `/api/health`).
- **Source + Dockerfile + deploy files:** https://github.com/salil-123/Project (branch `week10-lulc-models`).
- **STACD provenance:** the app already emits a STAC 1.1.0 Item + DAG at `/api/stacd` (the one Susmit and
  I cross-checked earlier).

Following the `dev` repo, I've drafted the three onboarding YAMLs (DAG / Algorithm_Instance /
Dataset_Instance) — attached. Before I finalize them and add the last endpoint, a few questions:

1. **API-mode vs Docker-mode as primary?** Our app is a running service, so API-mode fits naturally
   (you'd call an endpoint on the container). Docker-mode also works — I'd add a small `runner.run()`
   wrapper that prints the `===RESULT_JSON_START===/END===` markers your `simple_docker_runner.py`
   expects. Which do you prefer for us?

2. **Success response for STAC ingestion.** I see the framework registers the returned
   `{asset_id, version, hosting_platform: "GEE"}` as a DatasetInstance. Our endpoints currently return
   tiles + class counts + STACD metadata, not a persisted GEE asset — so I'll add an `/api/export-asset`
   that runs `Export.image.toAsset` and returns that descriptor. Is that the right shape, and **which GEE
   project/path** should the output asset live under (and any naming convention)?

3. **AOI input:** do workflows pass the area as CoreStack **admin boundaries** (state/district/block) or
   as a **bbox**? We can take either — just want the DAG params right.

4. **EE credentials:** for headless EE in the container I'll use a **service-account key** (via
   `gee_account_id` / `GOOGLE_APPLICATION_CREDENTIALS`). Is there a shared service account you'd want us
   to use, or should we provide our own?

If there's a `sample_yaml/` example that's closest to our case (single algorithm, GEE raster output), a
pointer would help me match the format exactly. Happy to hop on a quick call to wire this up.

Thanks,
Salil
</content>
