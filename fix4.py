"""
fix4.py - Remplace l'endpoint PLU par WFS bbox sur data.geopf.fr
Fonctionne pour toutes communes y compris Marseille/Lyon/Paris (PLUi)
Lance avec : python fix4.py
"""

path = "app.py"
content = open(path, encoding="utf-8").read()
original = content

old_marker = "# ─── PLU ──────────────────────────────────────────────────────────────────────\n@app.route(\"/api/plu\")"
new_block = '''# ─── PLU ──────────────────────────────────────────────────────────────────────
GPU_WFS = "https://data.geopf.fr/wfs/geoserver/ows"

def _fetch_plu_wfs(lat, lon, rayon_deg=0.04):
    bbox = f"{lon-rayon_deg},{lat-rayon_deg},{lon+rayon_deg},{lat+rayon_deg}"
    params = {
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
        "TYPENAMES": "gpu:zone_urba", "OUTPUTFORMAT": "application/json",
        "SRSNAME": "EPSG:4326", "BBOX": bbox + ",EPSG:4326", "COUNT": 1000,
    }
    r = requests.get(GPU_WFS, params=params, timeout=25)
    r.raise_for_status()
    return r.json().get("features", [])

@app.route("/api/plu")'''

if old_marker in content:
    content = content.replace(old_marker, new_block, 1)
    print("OK marker replaced")
else:
    print("MARKER NOT FOUND")
    import sys; sys.exit(1)

# Now fix the body of api_plu to use bbox
old_body = '''def api_plu():
    commune = request.args.get("commune", "").strip()
    if not commune:
        return jsonify({"error": "commune manquante"}), 400

    geo = geocode_commune(commune)
    if not geo:
        return jsonify({"error": f"Commune '{commune}' introuvable"}), 404

    code_insee = geo["code_insee"]
    # Pour Paris/Lyon/Marseille, interroger chaque arrondissement
    codes = ARRONDISSEMENTS.get(code_insee, [code_insee])
    features = []
    try:
        for code in codes[:5]:  # max 5 codes pour éviter timeout
            r = requests.get(GPU_API, params={"code_insee": code, "_limit": 500}, timeout=10)
            if r.status_code == 200:
                features.extend(r.json().get("features", []))
        # Si rien trouvé avec arrondissements, essayer code commune directement
        if not features:
            r = requests.get(GPU_API, params={"code_insee": code_insee, "_limit": 500}, timeout=10)
            if r.status_code == 200:
                features = r.json().get("features", [])
    except Exception as e:
        return jsonify({
            "commune": geo["nom"],
            "code_insee": code_insee,
            "total_features": 0,
            "zones": {},
            "features": [],
            "note": f"API Carto GPU indisponible: {e}"
        })

    zones = {}
    for f in features:
        props = f.get("properties", {})
        tz = props.get("typezone") or "?"
        zones[tz] = zones.get(tz, 0) + 1

    return jsonify({
        "commune": geo["nom"],
        "code_insee": code_insee,
        "total_features": len(features),
        "zones": zones,
        "features": features[:30],
        "plu_zones_sample": [f.get("properties",{}) for f in features[:10]]
    })'''

new_body = '''def api_plu():
    commune = request.args.get("commune", "").strip()
    if not commune:
        return jsonify({"error": "commune manquante"}), 400

    geo = geocode_commune(commune)
    if not geo:
        return jsonify({"error": f"Commune '{commune}' introuvable"}), 404

    code_insee = geo["code_insee"]
    lat, lon   = geo["lat"], geo["lon"]
    features   = []
    source     = ""

    # 1) WFS Geoplateforme IGN par bbox (couvre PLUi metropolitain)
    try:
        features = _fetch_plu_wfs(lat, lon, rayon_deg=0.04)
        source = "WFS Geoplateforme IGN bbox"
    except Exception as e1:
        # 2) Fallback API Carto IGN par code_insee
        try:
            codes = ARRONDISSEMENTS.get(code_insee, [code_insee])
            for code in codes[:3]:
                r = requests.get(GPU_API, params={"code_insee": code, "_limit": 500}, timeout=10)
                if r.status_code == 200:
                    features.extend(r.json().get("features", []))
            source = "API Carto IGN code_insee (fallback)"
        except Exception as e2:
            return jsonify({
                "commune": geo["nom"], "code_insee": code_insee,
                "total_features": 0, "zones": {}, "features": [],
                "note": f"WFS: {e1} | Carto: {e2}"
            })

    # Dedoublonnage
    seen, unique = set(), []
    for f in features:
        fid = f.get("id") or str(f.get("properties", {}).get("gid", id(f)))
        if fid not in seen:
            seen.add(fid)
            unique.append(f)
    features = unique

    zones = {}
    for f in features:
        props = f.get("properties", {})
        tz = props.get("typezone") or props.get("type_zone") or "?"
        zones[tz] = zones.get(tz, 0) + 1

    CONSTRUCTIBLE = {"U", "AU", "1AU", "2AU", "AUC", "AUS"}
    nb_c  = sum(v for k, v in zones.items() if k.upper()[:2] in CONSTRUCTIBLE or k.upper() in CONSTRUCTIBLE)
    nb_nc = sum(v for k, v in zones.items() if k.upper()[:1] in {"A", "N"} and k.upper()[:2] not in CONSTRUCTIBLE)

    return jsonify({
        "commune": geo["nom"], "code_insee": code_insee, "source": source,
        "total_features": len(features),
        "zones": zones,
        "nb_constructible": nb_c, "nb_non_constructible": nb_nc,
        "features": features[:50],
        "plu_zones_sample": [f.get("properties", {}) for f in features[:10]]
    })'''

if old_body in content:
    content = content.replace(old_body, new_body, 1)
    print("OK body replaced")
else:
    print("BODY NOT FOUND")
    import sys; sys.exit(1)

open(path, "w", encoding="utf-8").write(content)
print("app.py mis a jour.")
