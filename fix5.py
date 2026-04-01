"""
fix5.py - Connecte _fetch_plu_zones dans densification au WFS bbox Geoplateforme
(meme source que l'onglet PLU qui fonctionne desormais)
Lance avec : python fix5.py
"""

path = "app.py"
content = open(path, encoding="utf-8").read()
original = content

# Remplacer _fetch_plu_zones pour utiliser _fetch_plu_wfs (deja defini apres fix4)
old = """def _fetch_plu_zones(code_insee, codes_arr=None):
    \"\"\"
    Récupère les zones PLU avec leur géométrie.
    Retourne la liste des features GeoJSON.
    \"\"\"
    codes = codes_arr or ARRONDISSEMENTS.get(code_insee, [code_insee])
    features = []
    for code in codes[:3]:
        try:
            r = requests.get(GPU_API, params={"code_insee": code, "_limit": 500}, timeout=15)
            if r.status_code == 200:
                features.extend(r.json().get("features", []))
        except:
            pass
    # Dédoublonnage par libelle
    seen = set()
    unique = []
    for f in features:
        k = f.get("properties", {}).get("libelle", "")
        if k not in seen:
            seen.add(k)
            unique.append(f)
    return unique"""

new = """def _fetch_plu_zones(code_insee, codes_arr=None, lat=None, lon=None):
    \"\"\"
    Récupère les zones PLU avec géométrie via WFS Géoplateforme bbox.
    Fallback sur API Carto IGN si WFS échoue.
    \"\"\"
    features = []

    # 1) WFS Géoplateforme par bbox (fonctionne pour PLUi métropolitain)
    if lat is not None and lon is not None:
        try:
            features = _fetch_plu_wfs(lat, lon, rayon_deg=0.04)
        except Exception as e:
            print(f"[PLU-DENSIF] WFS bbox échoué: {e}")

    # 2) Fallback API Carto par code_insee
    if not features:
        codes = codes_arr or ARRONDISSEMENTS.get(code_insee, [code_insee])
        for code in codes[:3]:
            try:
                r = requests.get(GPU_API, params={"code_insee": code, "_limit": 500}, timeout=15)
                if r.status_code == 200:
                    features.extend(r.json().get("features", []))
            except:
                pass

    # Dédoublonnage par id feature
    seen, unique = set(), []
    for f in features:
        fid = f.get("id") or str(f.get("properties", {}).get("gid", id(f)))
        if fid not in seen:
            seen.add(fid)
            unique.append(f)
    return unique"""

if old in content:
    content = content.replace(old, new, 1)
    print("OK : _fetch_plu_zones mis a jour avec WFS bbox")
else:
    print("ERREUR : pattern _fetch_plu_zones non trouve")
    import sys; sys.exit(1)

# Passer lat/lon a _fetch_plu_zones dans api_densification
old2 = "        plu_features = _fetch_plu_zones(code_insee)"
new2 = "        plu_features = _fetch_plu_zones(code_insee, lat=geo['lat'], lon=geo['lon'])"

if old2 in content:
    content = content.replace(old2, new2, 1)
    print("OK : appel _fetch_plu_zones avec lat/lon")
else:
    print("ERREUR : appel _fetch_plu_zones non trouve")
    import sys; sys.exit(1)

open(path, "w", encoding="utf-8").write(content)
print("app.py mis a jour.")
