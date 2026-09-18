"""Drone Crop Health tab — first-party drone imagery, read straight from S3.

Self-contained and additive: renders a new tab in dashboard.py without touching
the existing PostGIS-backed tabs. Reads the AD4 processed bucket directly
(orthophoto + derived index overlays + problem-zone overlay + stats.json + a web
map overlay written by the drone pipeline), so it needs no database and no
schema changes. Works with older flights too: if a flight predates the per-index
overlays / problem zones, it falls back to the VARI-only view.
"""
import base64
import io
import json

import streamlit as st
import folium
from streamlit_folium import st_folium
from PIL import Image

_INDEX_ORDER = ["vari", "gli", "ngrdi", "exg", "tgi"]
_INDEX_LABELS = {"vari": "VARI", "gli": "GLI", "ngrdi": "NGRDI",
                 "exg": "ExG", "tgi": "TGI", "dsm": "Elevation (DSM)"}
_INDEX_HELP = {
    "vari": "Visible Atmospherically Resistant Index — broadband greenness.",
    "gli": "Green Leaf Index.",
    "ngrdi": "Normalized Green-Red Difference Index.",
    "exg": "Excess Green — vegetation vs. soil segmentation.",
    "tgi": "Triangular Greenness Index — chlorophyll proxy.",
}


@st.cache_data(ttl=300, show_spinner=False)
def _list_flights(_s3_client, bucket):
    """Flight folders = common prefixes at the bucket root. Cached (5 min TTL)
    so new flights still appear within a few minutes."""
    flights, token = [], None
    while True:
        kw = {"Bucket": bucket, "Delimiter": "/"}
        if token:
            kw["ContinuationToken"] = token
        resp = _s3_client.list_objects_v2(**kw)
        flights += [p["Prefix"].rstrip("/") for p in resp.get("CommonPrefixes", [])]
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break
    return sorted(flights)


@st.cache_data(ttl=300, show_spinner=False)
def _list_assets(_s3_client, bucket, flight):
    keys, token = set(), None
    while True:
        kw = {"Bucket": bucket, "Prefix": f"{flight}/"}
        if token:
            kw["ContinuationToken"] = token
        resp = _s3_client.list_objects_v2(**kw)
        keys |= {o["Key"] for o in resp.get("Contents", [])}
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break
    return keys


@st.cache_data(ttl=300, show_spinner=False)
def _load_json(_s3_client, bucket, key, _assets):
    if key not in _assets:
        return None
    obj = _s3_client.get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read())


def _presign(s3_client, bucket, key, expires=3600):
    return s3_client.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires)


@st.cache_data(ttl=3600, show_spinner=False)
def _overlay_data_uri(_s3_client, bucket, key, max_px=1000):
    """Fetch a PNG overlay server-side, downsize, and inline as a data URI.

    A presigned S3 URL can resolve to the global endpoint and 503 (wrong region);
    fetching server-side and inlining a downsized PNG sidesteps the browser->S3
    request (and CORS) entirely, so overlays always render.
    """
    try:
        obj = _s3_client.get_object(Bucket=bucket, Key=key)
        img = Image.open(io.BytesIO(obj["Body"].read())).convert("RGBA")
        img.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001 - a bad/missing overlay must not crash the tab
        return None


def _render_map(s3_client, bucket, flight, assets, mapinfo, stats,
                index_key, show_problem):
    """Interactive map: the selected index raster overlaid on satellite at the
    field's real coordinates, optionally with problem zones + scouting markers."""
    w, s, e, n = mapinfo["lonlat_bounds"]
    clon, clat = mapinfo["center"]
    bounds = [[s, w], [n, e]]  # folium: [[lat_min, lon_min], [lat_max, lon_max]]

    # Selected layer overlay (DSM is a special key), falling back to VARI.
    if index_key == "dsm":
        ov_key = f"{flight}/derived/dsm_overlay.png"
    else:
        ov_key = f"{flight}/derived/{index_key}_overlay.png"
    if ov_key not in assets:
        ov_key = f"{flight}/derived/vari_overlay.png"
        index_key = "vari"
    overlay_uri = _overlay_data_uri(s3_client, bucket, ov_key)
    layer_name = ("Elevation (DSM)" if index_key == "dsm"
                  else f"{_INDEX_LABELS.get(index_key, index_key.upper())} crop health")

    m = folium.Map(location=[clat, clon], zoom_start=17, tiles=None,
                   control_scale=True)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Satellite").add_to(m)
    if overlay_uri:
        folium.raster_layers.ImageOverlay(
            image=overlay_uri, bounds=bounds, opacity=0.8, name=layer_name
        ).add_to(m)
    folium.Rectangle(bounds=bounds, color="#ffffff", weight=2, fill=False).add_to(m)

    pz = (stats or {}).get("problem_zones") or {}
    pkey = f"{flight}/derived/problem_zones_overlay.png"
    targets = pz.get("scouting_targets", []) if show_problem else []
    if show_problem and pz.get("available") and pkey in assets:
        puri = _overlay_data_uri(s3_client, bucket, pkey)
        if puri:
            folium.raster_layers.ImageOverlay(
                image=puri, bounds=bounds,
                opacity=0.85, name="Problem zones").add_to(m)
        fg = folium.FeatureGroup(name="Scouting targets").add_to(m)
        for i, t in enumerate(targets, 1):
            folium.Marker(
                [t["lat"], t["lon"]],
                tooltip=f"Scouting target {i}",
                popup=f"Target {i} — {t['area_acres']} ac of low vigor",
                icon=folium.Icon(color="red", icon="exclamation-sign"),
            ).add_to(fg)

    folium.LayerControl(collapsed=True).add_to(m)
    # Frame the field explicitly. fit_bounds overrides location/zoom_start and,
    # with a per-view component key, stops st_folium from retaining a stale
    # pan/zoom across reruns (which otherwise leaves the field just off-screen).
    m.fit_bounds(bounds, padding=(30, 30))
    st_folium(m, height=520, use_container_width=True, returned_objects=[],
              key=f"map_{flight}_{index_key}_{int(show_problem)}")

    if index_key == "dsm":
        cap = ("Elevation / surface height (terrain ramp: low → high) on a "
               "satellite basemap at the flight's real footprint. Surface height, "
               "not true canopy height.")
    else:
        lbl = _INDEX_LABELS.get(index_key, index_key.upper())
        cap = (f"{lbl} overlay (red = low, green = high) on a satellite basemap at "
               "the flight's real footprint.")
    if targets:
        cap += f" Pink = lowest-vigor zones; {len(targets)} scouting target(s) pinned."
    st.caption(cap)


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

    pz = (stats or {}).get("problem_zones") or {}
    has_pz = bool(pz.get("available"))
    elev = (stats or {}).get("elevation") or {}
    has_elev = bool(elev.get("available"))

    if stats:
        cc = stats.get("canopy_cover", {})
        otsu = cc.get("exg_otsu", {}).get("canopy_cover_pct")
        vari = stats.get("indices", {}).get("vari", {})
        metrics = [
            ("Coverage", f"{stats.get('coverage_pct', '?')}%", None),
            ("Canopy cover", f"{otsu}%" if otsu is not None else "N/A", None),
            ("Mean VARI",
             f"{vari['mean']:.3f}" if isinstance(vari.get('mean'), (int, float))
             else "N/A", None),
            ("GSD", f"{stats.get('gsd_m', '?')} m", None),
        ]
        if has_pz:
            pct = pz.get("flagged_pct_of_field")
            acres = pz.get("flagged_area_acres")
            metrics.append((
                "Problem area", f"{pct}%" if pct is not None else "N/A",
                f"Lowest-vigor ~{pz.get('percentile', 10)}% of the field "
                f"(~{acres} ac). Scouting targets pinned on the map."))
        if has_elev:
            relief = elev.get("relief_p5_p95_m", elev.get("relief_m"))
            metrics.append((
                "Relief", f"{relief} m" if relief is not None else "N/A",
                "Surface-elevation range across the field (p5-p95), from the DSM. "
                "Surface height, not true canopy height."))
        cols = st.columns(len(metrics))
        for col, (lbl, val, hlp) in zip(cols, metrics):
            col.metric(lbl, val, help=hlp)
        st.caption(f"Processed {stats.get('generated_at', '?')} · "
                   f"{stats.get('sensor_note', '')}")

    # Layer controls: layer switcher (indices + elevation) + problem-zone toggle.
    avail = [i for i in _INDEX_ORDER
             if mapinfo and i in (mapinfo.get("indices") or [])]
    if not avail:
        avail = ["vari"]
    layers = list(avail)
    if has_elev and mapinfo and mapinfo.get("has_elevation"):
        layers.append("dsm")
    index_key = "vari"
    show_problem = has_pz
    if len(layers) > 1 or has_pz:
        c_idx, c_pz = st.columns([2, 1])
        if len(layers) > 1:
            index_key = c_idx.selectbox(
                "Map layer", layers,
                format_func=lambda k: _INDEX_LABELS.get(k, k.upper()),
                help="\n".join(f"{_INDEX_LABELS[k]}: {_INDEX_HELP[k]}"
                               for k in layers if k in _INDEX_HELP))
        if has_pz:
            show_problem = c_pz.checkbox("Show problem zones", value=True,
                                         help="Highlight the lowest-vigor areas "
                                              "and pin scouting targets.")

    # Interactive map of the flight, if the pipeline produced the overlay
    # and map.json carries the geo keys the map needs.
    if (mapinfo and mapinfo.get("lonlat_bounds") and mapinfo.get("center")
            and f"{flight}/derived/vari_overlay.png" in assets):
        _render_map(s3_client, processed_bucket, flight, assets, mapinfo, stats,
                    index_key, show_problem)
    else:
        preview = f"{flight}/derived/vari_preview.png"
        if preview in assets:
            st.image(_presign(s3_client, processed_bucket, preview),
                     caption=f"VARI crop-health map — {flight}",
                     width="stretch")

    if has_pz and show_problem and pz.get("scouting_targets"):
        import pandas as pd
        st.markdown("**Scouting targets** (lowest-vigor clusters, largest first)")
        trows = [{"#": i, "Latitude": t["lat"], "Longitude": t["lon"],
                  "Low-vigor area (ac)": t["area_acres"]}
                 for i, t in enumerate(pz["scouting_targets"], 1)]
        st.dataframe(pd.DataFrame(trows), hide_index=True, width="stretch")

    if stats:
        idx = stats.get("indices", {})
        rows = []
        for k in _INDEX_ORDER:
            v = idx.get(k)
            if v and all(isinstance(v.get(x), (int, float))
                         for x in ("mean", "median", "p5", "p95")):
                rows.append({"Index": k.upper(), "mean": round(v["mean"], 3),
                             "median": round(v["median"], 3),
                             "p5": round(v["p5"], 3), "p95": round(v["p95"], 3)})
        if rows:
            import pandas as pd
            st.markdown("**Vegetation index distributions**")
            st.dataframe(pd.DataFrame(rows), hide_index=True,
                         width="stretch")
    else:
        st.warning("No stats.json for this flight yet — showing available assets only.")

    downloadable = sorted(k for k in assets if k.endswith((".tif", ".png")))
    if downloadable:
        st.markdown("**Georeferenced layers (1-hour download links)**")
        for key in downloadable:
            st.markdown(f"- [{key[len(flight) + 1:]}]"
                        f"({_presign(s3_client, processed_bucket, key)})")
