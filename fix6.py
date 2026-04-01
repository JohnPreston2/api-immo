path = "app.py"
content = open(path, encoding="utf-8").read()

old_wfs = 'GPU_WFS = "https://data.geopf.fr/wfs/geoserver/ows"\n\ndef _fetch_plu_wfs(lat, lon, rayon_deg=0.04):\n    bbox = f"{lon-rayon_deg},{lat-rayon_deg},{lon+rayon_deg},{lat+rayon_deg}"\n    params = {\n        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",\n        "TYPENAMES": "gpu:zone_urba", "OUTPUTFORMAT": "application/json",\n        "SRSNAME": "EPSG:4326", "BBOX": bbox + ",EPSG:4326", "COUNT": 1000,\n    }\n    r = requests.get(GPU_WFS, params=params, timeout=25)\n    r.raise_for_status()\n    return r.json().get("features", [])'

if old_wfs not in content:
    print("Pattern non trouve, recherche...")
    idx = content.find("GPU_WFS")
    print(repr(content[idx:idx+300]))
    import sys; sys.exit(1)

new_wfs = '''def _fetch_plu_wfs(lat, lon, rayon_deg=0.04):
    import json as _json
    geom = _json.dumps({"type": "Point", "coordinates": [round(lon,6), round(lat,6)]})
    features = []
    for page in range(10):
        params = {"geom": geom, "_limit": 500, "_start": page * 500}
        try:
            r = requests.get("https://apicarto.ign.fr/api/gpu/zone-urba", params=params, timeout=20)
            if r.status_code != 200:
                break
            batch = r.json().get("features", [])
            features.extend(batch)
            if len(batch) < 500:
                break
        except Exception as e:
            print(f"[PLU] page {page} erreur: {e}")
            break
    return features'''

content = content.replace(old_wfs, new_wfs, 1)
open(path, "w", encoding="utf-8").write(content)
print("OK app.py mis a jour")
