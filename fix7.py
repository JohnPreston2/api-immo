path = "app.py"
content = open(path, encoding="utf-8").read()

# Pattern exact tel qu'il existe encore dans app.py
old = 'def _fetch_plu_wfs(lat, lon, rayon_deg=0.04):\n    bbox = f"{lon-rayon_deg},{lat-rayon_deg},{lon+rayon_deg},{lat+rayon_deg}"\n    params = {\n        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",\n        "TYPENAMES": "gpu:zone_urba", "OUTPUTFORMAT": "application/json",\n        "SRSNAME": "EPSG:4326", "BBOX": bbox + ",EPSG:4326", "COUNT": 1000,\n    }\n    r = requests.get(GPU_WFS, params=params, timeout=25)\n    r.raise_for_status()\n    return r.json().get("features", [])'

new = 'def _fetch_plu_wfs(lat, lon, rayon_deg=0.04):\n    import json as _j\n    d = rayon_deg\n    geom = _j.dumps({"type":"Polygon","coordinates":[[[lon-d,lat-d],[lon+d,lat-d],[lon+d,lat+d],[lon-d,lat+d],[lon-d,lat-d]]]})\n    features = []\n    for page in range(10):\n        params = {"geom": geom, "_limit": 500, "_start": page * 500}\n        try:\n            r = requests.get("https://apicarto.ign.fr/api/gpu/zone-urba", params=params, timeout=25)\n            if r.status_code != 200:\n                print(f"[PLU] HTTP {r.status_code}: {r.text[:200]}")\n                break\n            batch = r.json().get("features", [])\n            features.extend(batch)\n            if len(batch) < 500:\n                break\n        except Exception as e:\n            print(f"[PLU] page {page} erreur: {e}")\n            break\n    return features'

if old in content:
    content = content.replace(old, new, 1)
    open(path, "w", encoding="utf-8").write(content)
    print("OK")
else:
    print("ERREUR - recherche GPU_WFS pour contexte:")
    idx = content.find("GPU_WFS")
    if idx >= 0:
        print(repr(content[max(0,idx-50):idx+300]))
    else:
        print("GPU_WFS absent aussi")
        idx2 = content.find("_fetch_plu_wfs")
        print(repr(content[idx2:idx2+400]))
