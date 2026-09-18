"""Drone Crop Health tab — first-party drone imagery, read straight from S3.

Self-contained and additive: renders a new tab in dashboard.py without touching
the existing PostGIS-backed tabs. Reads the AD4 processed bucket directly
(orthophoto + derived VARI/index layers + stats.json + a web map overlay written
by the drone pipeline), so it needs no database and no schema changes.
"""
import json

import streamlit as st
import pydeck as pdk

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
    overlay_url = _presign(s3_client, bucket, f"{flight}/derived/vari_overlay.png")

    layers = [pdk.Layer("BitmapLayer", data=None, image=overlay_url,
                        bounds=[w, s, e, n], opacity=0.8)]
    outline = {"type": "Feature", "geometry": {"type": "Polygon",
               "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}}
    layers.append(pdk.Layer("GeoJsonLayer", data=outline, stroked=True,
                            filled=False, get_line_color=[255, 255, 255],
                            line_width_min_pixels=2))
    view = pdk.ViewState(latitude=clat, longitude=clon, zoom=16, pitch=0)
    style = "mapbox://styles/mapbox/satellite-v9" if mapbox_token else None
    st.pydeck_chart(pdk.Deck(
        layers=layers, initial_view_state=view, map_style=style,
        api_keys={"mapbox": mapbox_token} if mapbox_token else None,
    ))
    st.caption("VARI overlay (red = low vigor, green = vegetation) on the real "
               "flight footprint. Add a Mapbox token for a satellite basemap.")


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
