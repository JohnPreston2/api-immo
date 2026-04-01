path = "app.py"
content = open(path, encoding="utf-8").read()

# Rayon adaptatif selon la taille de la commune
old = '''def _fetch_plu_wfs(lat, lon, rayon_deg=0.04):
    import json as _j
    d = rayon_deg
    geom = _j.dumps({"type":"Polygon","coordinates":[[[lon-d,lat-d],[lon+d,lat-d],[lon+d,lat+d],[lon-d,lat+d],[lon-d,lat-d]]]})
    features = []
    for page in range(10):
        params = {"geom": geom, "_limit": 500, "_start": page * 500}
        try:
            r = requests.get("https://apicarto.ign.fr/api/gpu/zone-urba", params=params, timeout=25)
            if r.status_code != 200:
                print(f"[PLU] HTTP {r.status_code}: {r.text[:200]}")
                break
            batch = r.json().get("features", [])
            features.extend(batch)
            if len(batch) < 500:
                break
        except Exception as e:
            print(f"[PLU] page {page} erreur: {e}")
            break
    return features'''

new = '''def _fetch_plu_wfs(lat, lon, rayon_deg=0.04):
    """
    Recupere zones PLU via API Carto IGN (Polygon bbox).
    Pagination automatique, deduplication par id feature.
    """
    import json as _j
    d = rayon_deg
    geom = _j.dumps({"type":"Polygon","coordinates":[[[lon-d,lat-d],[lon+d,lat-d],[lon+d,lat+d],[lon-d,lat+d],[lon-d,lat-d]]]})
    features = []
    seen = set()
    for page in range(20):  # max 20 pages x 500 = 10 000 features
        params = {"geom": geom, "_limit": 500, "_start": page * 500}
        try:
            r = requests.get("https://apicarto.ign.fr/api/gpu/zone-urba", params=params, timeout=30)
            if r.status_code != 200:
                print(f"[PLU] HTTP {r.status_code}: {r.text[:200]}")
                break
            data = r.json()
            batch = data.get("features", [])
            for f in batch:
                fid = f.get("id") or str(f.get("properties", {}).get("gid", ""))
                if fid not in seen:
                    seen.add(fid)
                    features.append(f)
            if len(batch) < 500:
                break
        except Exception as e:
            print(f"[PLU] page {page} erreur: {e}")
            break
    print(f"[PLU] {len(features)} features uniques, {page+1} pages")
    return features'''

if old in content:
    content = content.replace(old, new, 1)
    open(path, "w", encoding="utf-8").write(content)
    print("OK : pagination corrigee (20 pages max)")
else:
    print("ERREUR pattern non trouve")
    idx = content.find("def _fetch_plu_wfs")
    print(repr(content[idx:idx+300]))

# Aussi augmenter le rayon dans api_plu selon la population / taille commune
content = open(path, encoding="utf-8").read()

old2 = '''    # 1) WFS Geoplateforme IGN par bbox (couvre PLUi metropolitain)
    try:
        features = _fetch_plu_wfs(lat, lon, rayon_deg=0.04)
        source = "WFS Geoplateforme IGN bbox"'''

new2 = '''    # Rayon adaptatif : grandes villes ont un territoire plus etendu
    # Marseille ~240km2, Lyon ~48km2, Paris ~105km2
    GRANDES_VILLES = {"13055": 0.20, "69123": 0.12, "75056": 0.10,
                      "31555": 0.12, "33063": 0.10, "06088": 0.10,
                      "67482": 0.12, "59350": 0.12, "34172": 0.10}
    rayon = GRANDES_VILLES.get(code_insee, 0.06)

    # 1) WFS Geoplateforme IGN par bbox (couvre PLUi metropolitain)
    try:
        features = _fetch_plu_wfs(lat, lon, rayon_deg=rayon)
        source = f"API Carto IGN bbox r={rayon}"'''

if old2 in content:
    content = content.replace(old2, new2, 1)
    open(path, "w", encoding="utf-8").write(content)
    print("OK : rayon adaptatif grandes villes")
else:
    print("ERREUR rayon pattern non trouve")
