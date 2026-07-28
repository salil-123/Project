"""Build the ROI shapefile for the Tessera embedding request (week 7).

The geotessera issue form takes either four bbox corners or an attached shapefile, and a shapefile
wins when both are present. We have four disjoint stress-test sites, so one shapefile with four
rectangles is the tidy way to request them all in a single issue. Writes sites.shp/.shx/.dbf/.prj
(WGS84) and zips them into sites.zip, which is what you drag onto the GitHub issue.

Run:  python week7/tessera_request/make_shapefile.py
"""
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

HERE = Path(__file__).resolve().parent

# name -> [west, south, east, north]; the same boxes used as presets in the app
SITES = {
    "IIT Delhi + Sanjay Van": [77.165, 28.520, 77.205, 28.560],
    "Asola Bhatti":           [77.190, 28.420, 77.270, 28.480],
    "Jalpaiguri":             [88.680, 26.480, 88.780, 26.560],
    "Assam tea belt":         [95.750, 27.550, 95.980, 27.730],
}


def main():
    gdf = gpd.GeoDataFrame(
        {"name": list(SITES)},
        geometry=[box(w, s, e, n) for w, s, e, n in SITES.values()],
        crs=4326,
    )
    shp = HERE / "sites.shp"
    gdf.to_file(shp)  # writes .shp/.shx/.dbf/.prj alongside

    # zip every sidecar file into one archive to attach to the issue
    zpath = HERE / "sites.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for part in HERE.glob("sites.*"):
            if part.suffix != ".zip":
                z.write(part, part.name)
    print(f"wrote {zpath} with {len(SITES)} ROIs")


if __name__ == "__main__":
    main()
