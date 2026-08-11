# Get-ready-for-Saharsh build plan

Goal: be ready for the joint local test (his Airflow calls our backend). Two pieces to build + verify.

## 1. `/api/export-asset` endpoint  (the STACD success contract)
His pipeline expects a synchronous call that runs the GEE task and returns the output asset:
`{ "asset_id": "...", "version": "1", "hosting_platform": "GEE" }`.

- Build the labelled LULC ee.Image (reuse infer's labelled-image path, the same one the tiles use).
- `ee.batch.Export.image.toAsset(image, assetId, region, scale=10, crs=EPSG:4326, maxPixels)`.
- Block until the task finishes (poll status), then return the descriptor. Matches "APIs are synchronous".
- Output asset lives under OUR GEE project (config.EE_PROJECT) for now: `projects/<proj>/assets/corestack_lulc/<region>_<year>`.

## 2. Admin-boundary input (match their DAG params)
Their algorithms take `state/district/block` + read geometry from the `MWS_Boundaries` GEE asset that
`MWS_Layer` produces upstream. So the endpoint accepts:
- `roi_asset` = a FeatureCollection asset id (the filtered MWS boundaries) -> AOI = its geometry, OR
- `west/south/east/north` = a plain bbox (standalone testing, the path we already know works).
- `year` (default 2024; also accept `end_year`).

Note: exact MWS property names for filtering state/district/block are their schema — for the joint test
we pass the already-filtered MWS asset id (what their pipeline hands downstream), so we just read its
geometry. No hardcoded property names needed.

## 3. Verify
- Local: `uvicorn` up, call `/api/export-asset` on a small bbox, confirm it returns an asset_id and the
  asset appears in our GEE project.
- Keep the tile/classify path unchanged (regression).
- Rebuild + push the image so the container has the new endpoint.

## Commands (see chat) — run app, test endpoint, rebuild image.
</content>
