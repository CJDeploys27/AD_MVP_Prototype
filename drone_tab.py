"""Drone Crop Health tab — first-party drone imagery, read straight from S3.

Self-contained and additive: renders a new tab in dashboard.py without touching
the existing PostGIS-backed tabs. Reads the AD4 processed bucket directly
(orthophoto + derived VARI/index layers + stats.json + a web map overlay written
by the drone pipeline), so it needs no database and no schema changes.
"""
import base64
import io
import json

import streamlit as st
import folium
from streamlit_folium import st_folium
from PIL import Image

_INDEX_ORDER = ["vari", "gli", "ngrdi", "exg", "tgi"]


def _list_flights(s3_client, bucket):
    """Flight folders = common prefixes at the bucket root."""
    flights, token = [], None
    while True:
        kw = {"Bucket": bucket, "Delimiter": "/"}
        if token:
            kw["ContinuationToken"] = token
        resp = s3_client.list_objects_v2(**kw)
        flights += [p["Prefix"].rstrip("/") for p in resp.get("CommonPrefixes", [])]
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break
    return sorted(flights)


def _list_assets(s3_client, bucket, flight):
    resp = s3_client.list_objects_v2(Bucket=bucket, Prefix=f"{flight}/")
    return {o["Key"] for o in resp.get("Contents", [])}


def _load_json(s3_client, bucket, key, assets):
    if key not in assets:
        return None
    obj = s3_client.get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read())


def _presign(s3_client, bucket, key, expires=3600):
    return s3_client.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires)


def _render_map(s3_client, bucket, flight, assets, mapinfo, mapbox_token):
    """Interactive map: VARI raster overlaid on satellite at the field's real
    coordinates, with the flight footprint outlined."""
    w, s, e, n = mapinfo["lonlat_bounds"]
    clon, clat = mapinfo["center"]
    bounds = [[s, w], [n, e]]  # folium: [[lat_min, lon_min], [lat_max, lon_max]]

    # Embed the overlay as a data URI instead of linking to S3 from the browser.
    # A presigned S3 URL can resolve to the global endpoint and 503 (wrong region);
    # fetching server-side and inlining a downsized PNG sidesteps the browser->S3
    # request (and CORS) entirely, so the overlay always renders.
    obj = s3_client.get_object(Bucket=bucket, Key=f"{flight}/derived/vari_overlay.png")
    img = Image.open(io.BytesIO(obj["Body"].read())).convert("RGBA")
    img.thumbnail((1000, 1000))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    overlay_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    m = folium.Map(location=[clat, clon], zoom_start=17, tiles=None, control_scale=True)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Satellite").add_to(m)
    folium.raster_layers.ImageOverlay(
        image=overlay_uri, bounds=bounds, opacity=0.8, name="VARI crop health").add_to(m)
    folium.Rectangle(bounds=bounds, color="#ffffff", weight=2, fill=False).add_to(m)
    # Frame the field explicitly. fit_bounds overrides location/zoom_start and,
    # with a per-flight component key, stops st_folium from retaining a stale
    # pan/zoom across reruns (which otherwise leaves the field just off-screen).
    m.fit_bounds(bounds, padding=(30, 30))
    st_folium(m, height=520, use_container_width=True,
              returned_objects=[], key=f"map_{flight}")
    st.caption("VARI overlay (red = low vigor, green = vegetation) on a satellite "
               "basemap at the flight's real footprint.")


def render(s3_client, processed_bucket, mapbox_token=""):
    if s3_client is None:
        st.error("No AWS S3 client. Check your AWS credentials in the .env file.")
        return
    try:
        flights = _list_flights(s3_client, processed_bucket)
    except Exception as e:
        st.error(f"Couldn't list flights in the processed bucket: {e}")
        return
    if not flights:
        st.info("No processed drone flights yet. Fly a mission and let the "
                "auto-export pipeline land it here.")
        return

    flight = st.selectbox("Flight", flights)
    assets = _list_assets(s3_client, processed_bucket, flight)
    mapinfo = _load_json(s3_client, processed_bucket, f"{flight}/derived/map.json", assets)
    stats = _load_json(s3_client, processed_bucket, f"{flight}/derived/stats.json", assets)

    label = (mapinfo or {}).get("label") or "Drone Crop Health"
    st.header(f"🛰️ {label}")
    st.caption(f"First-party drone imagery, read live from `s3://{processed_bucket}/` "
               "— no database required.")

    if stats:
        cc = stats.get("canopy_cover", {})
        otsu = cc.get("exg_otsu", {}).get("canopy_cover_pct")
        vari = stats.get("indices", {}).get("vari", {})
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Coverage", f"{stats.get('coverage_pct', '?')}%")
        c2.metric("Canopy cover", f"{otsu}%" if otsu is not None else "N/A")
        c3.metric("Mean VARI", f"{vari.get('mean'):.3f}" if vari else "N/A")
        c4.metric("GSD", f"{stats.get('gsd_m', '?')} m")
        st.caption(f"Processed {stats.get('generated_at', '?')} · "
                   f"{stats.get('sensor_note', '')}")

    # Interactive map of the flight, if the pipeline produced the overlay.
    if mapinfo and f"{flight}/derived/vari_overlay.png" in assets:
        _render_map(s3_client, processed_bucket, flight, assets, mapinfo, mapbox_token)
    else:
        preview = f"{flight}/derived/vari_preview.png"
        if preview in assets:
            st.image(_presign(s3_client, processed_bucket, preview),
                     caption=f"VARI crop-health map — {flight}",
                     use_container_width=True)

    if stats:
        idx = stats.get("indices", {})
        rows = []
        for k in _INDEX_ORDER:
            v = idx.get(k)
            if v:
                rows.append({"Index": k.upper(), "mean": round(v["mean"], 3),
                             "median": round(v["median"], 3),
                             "p5": round(v["p5"], 3), "p95": round(v["p95"], 3)})
        if rows:
            import pandas as pd
            st.markdown("**Vegetation index distributions**")
            st.dataframe(pd.DataFrame(rows), hide_index=True,
                         use_container_width=True)
    else:
        st.warning("No stats.json for this flight yet — showing available assets only.")

    downloadable = sorted(k for k in assets if k.endswith((".tif", ".png")))
    if downloadable:
        st.markdown("**Georeferenced layers (1-hour download links)**")
        for key in downloadable:
            st.markdown(f"- [{key[len(flight) + 1:]}]"
                        f"({_presign(s3_client, processed_bucket, key)})")
