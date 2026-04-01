from flask import Flask, render_template, jsonify, request
import requests, csv, io, json, os, time, threading
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# â”€â”€â”€ ENDPOINTS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# DVF : fichiers locaux (tÃ©lÃ©chargÃ©s depuis data.gouv.fr)
DVF_BASE   = "https://files.data.gouv.fr/geo-dvf/latest/csv"  # fallback rÃ©seau
DVF_LOCAL  = {
    "2022": os.path.join(os.path.dirname(__file__), "Data", "full (2).csv.gz"),
    "2023": os.path.join(os.path.dirname(__file__), "Data", "full (1).csv.gz"),
    "2024": os.path.join(os.path.dirname(__file__), "Data", "full.csv.gz"),
    "2025": os.path.join(os.path.dirname(__file__), "Data", "full (3).csv.gz"),
}
# DPE ADEME : dataset dpe03existant (logements existants depuis juillet 2021)
DPE_API    = "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines"
# API Carto GPU â†’ endpoint simplifiÃ© par code INSEE
GPU_API    = "https://apicarto.ign.fr/api/gpu/zone-urba"
GEOCODE_API  = "https://api-adresse.data.gouv.fr/search/"
# API Carto cadastre IGN (parcelles + bÃ¢ti)
CADELSTRE_API = "https://apicarto.ign.fr/api/cadastre"
# DFI index local (gÃ©nÃ©rÃ© par build_dfi_index.py)
DFI_INDEX     = os.path.join(os.path.dirname(__file__), "cache", "dfi_index.json")
# SITADEL index local (gÃ©nÃ©rÃ© par build_sitadel_index.py)
SITADEL_INDEX = os.path.join(os.path.dirname(__file__), "cache", "sitadel_index.json")

# â”€â”€â”€ UTILS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def geocode_commune(nom):
    for tentative in range(3):
        try:
            r = requests.get(GEOCODE_API, params={"q": nom, "type": "municipality", "limit": 1}, timeout=15)
            r.raise_for_status()
            break
        except Exception as e:
            if tentative == 2:
                raise
            time.sleep(1)
    feats = r.json().get("features", [])
    if not feats:
        return None
    f = feats[0]
    props = f["properties"]
    lon, lat = f["geometry"]["coordinates"]
    dep = props.get("citycode", "")[:2]  # 2 premiers chiffres = dÃ©partement
    return {
        "lat": lat, "lon": lon,
        "code_insee": props.get("citycode", ""),
        "departement": dep,
        "nom": props.get("label", "")
    }

# â”€â”€â”€ CACHE DVF â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
CACHE_DIR    = os.path.join(os.path.dirname(__file__), "cache")
CACHE_TTL    = 24 * 3600   # 24h en secondes
_mem_cache   = {}           # code_insee -> mutations (RAM)
_cache_lock  = threading.Lock()

os.makedirs(CACHE_DIR, exist_ok=True)

def _cache_path(code_insee):
    return os.path.join(CACHE_DIR, f"dvf_{code_insee}.json")

def _cache_valid(path):
    """Retourne True si le fichier existe et a moins de 24h"""
    return os.path.exists(path) and (time.time() - os.path.getmtime(path)) < CACHE_TTL

def _cache_load(code_insee):
    """Charge depuis RAM, puis fichier, sinon None. Supprime le cache si JSON corrompu."""
    with _cache_lock:
        if code_insee in _mem_cache:
            return _mem_cache[code_insee]
    path = _cache_path(code_insee)
    if _cache_valid(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with _cache_lock:
                _mem_cache[code_insee] = data
            return data
        except Exception as e:
            print(f"[CACHE] JSON corrompu {path}, suppression : {e}")
            try:
                os.remove(path)
            except:
                pass
    return None

def _cache_save(code_insee, mutations):
    """Sauvegarde en fichier JSON et en RAM"""
    path = _cache_path(code_insee)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mutations, f, ensure_ascii=False)
    with _cache_lock:
        _mem_cache[code_insee] = mutations

# Grandes villes dÃ©coupÃ©es en arrondissements
ARRONDISSEMENTS = {
    "69123": [f"693{i:02d}" for i in range(81, 90)],   # Lyon 69381-69389
    "75056": [f"751{i:02d}" for i in range(1, 21)],    # Paris 75101-75120
    "13055": [f"13{200+i}" for i in range(1, 17)],    # Marseille 13201-13216
}

def _parse_row(m):
    return {
        "date_mutation":       m.get("date_mutation", ""),
        "valeur_fonciere":     m.get("valeur_fonciere", "").replace(",", "."),
        "surface_reelle_bati": m.get("surface_reelle_bati", "").replace(",", "."),
        "surface_terrain":     m.get("surface_terrain", "").replace(",", "."),
        "type_local":          m.get("type_local", ""),
        "adresse_numero":      m.get("adresse_numero", ""),
        "adresse_nom_voie":    m.get("adresse_nom_voie", ""),
        "nature_mutation":     m.get("nature_mutation", ""),
        "code_commune":        m.get("code_commune", ""),
        "nom_commune":         m.get("nom_commune", ""),
    }

DVF_INDEX_DIR = os.path.join(os.path.dirname(__file__), "cache", "dvf")

def fetch_dvf(code_insee, departement):
    """Lit les fichiers JSON prÃ©-indexÃ©s par commune (build_dvf_index.py). Cache RAM."""
    # 1. Cache RAM
    cached = _cache_load(code_insee)
    if cached is not None:
        return cached

    # Codes Ã  chercher (arrondissements ou commune simple)
    codes = ARRONDISSEMENTS.get(code_insee, [code_insee])

    mutations = []
    for code in codes:
        path = os.path.join(DVF_INDEX_DIR, f"{code}.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                mutations.extend(json.load(f))
        except Exception as e:
            print(f"[DVF] Erreur lecture {path}: {e}")

    if mutations:
        _cache_save(code_insee, mutations)
    return mutations

# Noms lisibles des arrondissements
ARRONDISSEMENT_NOMS = {
    # Lyon
    "69381": "Lyon 1er", "69382": "Lyon 2e", "69383": "Lyon 3e",
    "69384": "Lyon 4e", "69385": "Lyon 5e", "69386": "Lyon 6e",
    "69387": "Lyon 7e", "69388": "Lyon 8e", "69389": "Lyon 9e",
    # Paris
    **{f"751{i:02d}": f"Paris {i}e" for i in range(1, 21)},
    # Marseille
    "13201": "Marseille 1er", "13202": "Marseille 2e", "13203": "Marseille 3e",
    "13204": "Marseille 4e", "13205": "Marseille 5e", "13206": "Marseille 6e",
    "13207": "Marseille 7e", "13208": "Marseille 8e", "13209": "Marseille 9e",
    "13210": "Marseille 10e", "13211": "Marseille 11e", "13212": "Marseille 12e",
    "13213": "Marseille 13e", "13214": "Marseille 14e", "13215": "Marseille 15e",
    "13216": "Marseille 16e",
}

# â”€â”€â”€ ROUTE PRINCIPALE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/rag")
def rag_page():
    return render_template("rag.html")

# â”€â”€â”€ DVF PAR ARRONDISSEMENT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route("/api/dvf/arrondissements")
def api_dvf_arrondissements():
    commune = request.args.get("commune", "").strip()
    type_bien = request.args.get("type", "Appartement")
    if not commune:
        return jsonify({"error": "commune manquante"}), 400
    geo = geocode_commune(commune)
    if not geo:
        return jsonify({"error": f"Commune '{commune}' introuvable"}), 404
    if geo["code_insee"] not in ARRONDISSEMENTS:
        return jsonify({"error": f"{geo['nom']} n'est pas dÃ©coupÃ©e en arrondissements"}), 400
    try:
        mutations = fetch_dvf(geo["code_insee"], geo["departement"])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    par_arr = {}
    for m in mutations:
        if m.get("type_local") != type_bien: continue
        if m.get("nature_mutation") != "Vente": continue  # exclure successions, expropriations
        try:
            v = float(m["valeur_fonciere"])
            s = float(m["surface_reelle_bati"]) if type_bien != "Terrain" else float(m["surface_terrain"])
            if v <= 0 or s <= 5: continue  # surface minimum 5mÂ²
            pm2 = v / s
            if pm2 < 500 or pm2 > 25000: continue  # filtre aberrants
        except: continue
        code = m.get("code_commune", "?")
        par_arr.setdefault(code, []).append(pm2)

    result = []
    for code, prix_list in sorted(par_arr.items()):
        if not prix_list: continue
        sp = sorted(prix_list)
        result.append({
            "code": code,
            "nom": ARRONDISSEMENT_NOMS.get(code, code),
            "nb_transactions": len(prix_list),
            "prix_m2_moyen": round(sum(prix_list)/len(prix_list)),
            "prix_m2_median": round(sp[len(sp)//2]),
            "prix_m2_min": round(sp[0]),
            "prix_m2_max": round(sp[-1]),
        })

    return jsonify({
        "commune": geo["nom"],
        "type_bien": type_bien,
        "total_transactions": sum(r["nb_transactions"] for r in result),
        "arrondissements": result
    })

# â”€â”€â”€ DVF â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route("/api/dvf")
def api_dvf():
    commune = request.args.get("commune", "").strip()
    if not commune:
        return jsonify({"error": "commune manquante"}), 400

    geo = geocode_commune(commune)
    if not geo:
        return jsonify({"error": f"Commune '{commune}' introuvable"}), 404

    try:
        mutations = fetch_dvf(geo["code_insee"], geo["departement"])
    except Exception as e:
        return jsonify({"error": f"DVF: {e}"}), 500

    if not mutations:
        return jsonify({"error": f"Pas de donnÃ©es DVF pour {geo['nom']} (dep {geo['departement']})"}), 404

    def filtre_vente(m, type_local, surf_key="surface_reelle_bati"):
        if m.get("type_local") != type_local: return False
        if m.get("nature_mutation") != "Vente": return False
        try:
            v = float(m["valeur_fonciere"]); s = float(m[surf_key])
            if v <= 0 or s <= 5: return False
            pm2 = v/s
            return 500 <= pm2 <= 25000
        except: return False

    apparts = [m for m in mutations if filtre_vente(m, "Appartement")]
    maisons  = [m for m in mutations if filtre_vente(m, "Maison")]
    terrains = [m for m in mutations if "Terrain" in m.get("type_local","")
                and m.get("nature_mutation") == "Vente"
                and m.get("valeur_fonciere") and m.get("surface_terrain")]

    def prix_m2(lst, key="surface_reelle_bati"):
        vals = []
        for m in lst:
            try:
                v = float(m["valeur_fonciere"]); s = float(m[key])
                if s > 0: vals.append(v/s)
            except: pass
        return round(sum(vals)/len(vals)) if vals else None

    def prix_list(lst, key="surface_reelle_bati"):
        vals = []
        for m in lst:
            try:
                v = float(m["valeur_fonciere"]); s = float(m[key])
                if s > 0: vals.append(v/s)
            except: pass
        return vals

    def median(lst):
        if not lst: return None
        s = sorted(lst); return s[len(s)//2]

    return jsonify({
        "commune": geo["nom"],
        "code_insee": geo["code_insee"],
        "total_transactions": len(mutations),
        "appartements": {
            "count": len(apparts),
            "prix_m2_moyen": prix_m2(apparts),
            "prix_m2_median": round(median(prix_list(apparts))) if prix_list(apparts) else None,
        },
        "maisons": {
            "count": len(maisons),
            "prix_m2_moyen": prix_m2(maisons),
            "prix_m2_median": round(median(prix_list(maisons))) if prix_list(maisons) else None,
        },
        "terrains": {
            "count": len(terrains),
            "prix_m2_moyen": prix_m2(terrains, "surface_terrain"),
        },
        "transactions_recentes": sorted(
            [m for m in mutations if m.get("date_mutation") and m.get("valeur_fonciere")],
            key=lambda x: x["date_mutation"], reverse=True
        )[:20]
    })

# â”€â”€â”€ DPE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route("/api/dpe")
def api_dpe():
    commune = request.args.get("commune", "").strip()
    if not commune:
        return jsonify({"error": "commune manquante"}), 400

    geo = geocode_commune(commune)
    if not geo:
        return jsonify({"error": f"Commune '{commune}' introuvable"}), 404

    try:
        # Champs rÃ©els du dataset dpe03existant (minuscules)
        # Filtre par nom de commune (champ disponible dans dpe03existant)
        nom_commune = geo["nom"].split(" ")[0].upper()  # ex: "LYON" depuis "Lyon"
        params = {
            "q": nom_commune,
            "q_fields": "nom_commune_brut",
            "select": "etiquette_dpe,etiquette_ges,conso_5_usages_par_m2_ep,emission_ges_5_usages_par_m2,surface_habitable_logement,annee_construction,code_postal_brut,nom_commune_brut,type_batiment,adresse_brut",
            "size": 1000
        }
        r = requests.get(DPE_API, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    results = data.get("results", [])
    total   = data.get("total", 0)

    classes = {"A":0,"B":0,"C":0,"D":0,"E":0,"F":0,"G":0}
    for d in results:
        cl = (d.get("etiquette_dpe") or "").strip().upper()
        if cl in classes:
            classes[cl] += 1

    consos = []
    for d in results:
        try:
            c = float(d.get("conso_5_usages_par_m2_ep") or 0)
            if 0 < c < 2000: consos.append(c)
        except: pass
    conso_moy = round(sum(consos)/len(consos)) if consos else None

    passoires = classes.get("F",0) + classes.get("G",0)
    total_cl  = sum(classes.values())
    pct_passoires = round(100*passoires/total_cl) if total_cl > 0 else 0

    types = {}
    for d in results:
        t = d.get("type_batiment") or "Inconnu"
        types[t] = types.get(t, 0) + 1

    return jsonify({
        "commune": geo["nom"],
        "code_insee": geo["code_insee"],
        "total_dpe_bd": total,
        "echantillon": len(results),
        "distribution_classes": classes,
        "conso_moyenne_ep_m2": conso_moy,
        "passoires_thermiques": {"count": passoires, "pourcentage": pct_passoires},
        "types_batiment": types,
        "details": [
            {
                "Etiquette_DPE": d.get("etiquette_dpe",""),
                "Etiquette_GES": d.get("etiquette_ges",""),
                "Conso_5_usages_ep_m2": d.get("conso_5_usages_par_m2_ep",""),
                "Surface_habitable_logement": d.get("surface_habitable_logement",""),
                "Annee_construction": d.get("annee_construction",""),
                "Adresse_BAN": d.get("adresse_brut",""),
            }
            for d in results[:50]
        ]
    })

# â”€â”€â”€ PRIME VERTE DVF Ã— DPE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route("/api/croisement/prime-verte")
def prime_verte():
    commune = request.args.get("commune", "").strip()
    if not commune:
        return jsonify({"error": "commune manquante"}), 400

    geo = geocode_commune(commune)
    if not geo:
        return jsonify({"error": f"Commune '{commune}' introuvable"}), 404

    try:
        dvf_data = fetch_dvf(geo["code_insee"], geo["departement"])
    except Exception as e:
        return jsonify({"error": f"DVF: {e}"}), 500

    try:
        nom_commune = geo["nom"].split(" ")[0].upper()
        params = {
            "q": nom_commune,
            "q_fields": "nom_commune_brut",
            "select": "etiquette_dpe,surface_habitable_logement",
            "size": 2000
        }
        r2 = requests.get(DPE_API, params=params, timeout=20)
        r2.raise_for_status()
        dpe_data = r2.json().get("results", [])
    except Exception as e:
        return jsonify({"error": f"DPE: {e}"}), 500

    # Matching par surface arrondie
    dpe_surface_map = {}
    for d in dpe_data:
        try:
            surf = float(d.get("surface_habitable_logement") or 0)
            cl   = (d.get("etiquette_dpe") or "").strip().upper()
            if surf > 0 and cl in "ABCDEFG":
                key = round(surf/5)*5
                dpe_surface_map.setdefault(key, []).append(cl)
        except: pass

    from collections import Counter
    prix_par_classe = {cl: [] for cl in "ABCDEFG"}
    for m in dvf_data:
        if m.get("type_local") not in ("Appartement","Maison"): continue
        if m.get("nature_mutation") != "Vente": continue
        try:
            surf = float(m.get("surface_reelle_bati") or 0)
            val  = float(m.get("valeur_fonciere") or 0)
            if surf <= 5 or val <= 0: continue
            pm2 = val / surf
            if pm2 < 500 or pm2 > 25000: continue
            key = round(surf/5)*5
            proches = dpe_surface_map.get(key, [])
            if proches:
                cl = Counter(proches).most_common(1)[0][0]
                prix_par_classe[cl].append(pm2)
        except: pass

    result_classes = {}
    for cl, prix in prix_par_classe.items():
        if prix:
            result_classes[cl] = {
                "count": len(prix),
                "prix_m2_moyen": round(sum(prix)/len(prix)),
            }

    try:
        bons    = [p for cl in ["A","B","C"] for p in prix_par_classe[cl]]
        mauvais = [p for cl in ["E","F","G"] for p in prix_par_classe[cl]]
        prime   = round(sum(bons)/len(bons) - sum(mauvais)/len(mauvais)) if bons and mauvais else None
    except Exception as e:
        return jsonify({"error": f"Calcul prime: {e}"}), 500

    return jsonify({
        "commune": geo["nom"],
        "methode": "matching par surface arrondie Â±5mÂ²",
        "prix_par_classe_dpe": result_classes,
        "prime_verte_estimee": {
            "valeur_eur_m2": prime,
            "description": "DiffÃ©rence prix/mÂ² entre biens A-C vs E-G"
        }
    })

# â”€â”€â”€ PLU â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
GPU_WFS = "https://data.geopf.fr/wfs/geoserver/ows"

def _fetch_plu_wfs(lat, lon, rayon_deg=0.04):
    import json as _j
    d = 0.04
    geom = _j.dumps({"type":"Polygon","coordinates":[[[lon-d,lat-d],[lon+d,lat-d],[lon+d,lat+d],[lon-d,lat+d],[lon-d,lat-d]]]})
    features = []
    seen = set()
    for page in range(3):
        params = {"geom": geom, "_limit": 500, "_start": page * 500}
        try:
            r = requests.get("https://apicarto.ign.fr/api/gpu/zone-urba", params=params, timeout=15)
            if r.status_code != 200:
                break
            batch = r.json().get("features", [])
            for f in batch:
                fid = f.get("id") or str(f.get("properties", {}).get("gid", id(f)))
                if fid not in seen:
                    seen.add(fid)
                    features.append(f)
            if len(batch) < 500:
                break
        except Exception as e:
            print(f"[PLU] page {page}: {e}")
            break
    return features

@app.route("/api/plu")
def api_plu():
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

    # Rayon adaptatif : grandes villes ont un territoire plus etendu
    # Marseille ~240km2, Lyon ~48km2, Paris ~105km2
    GRANDES_VILLES = {"13055": 0.20, "69123": 0.12, "75056": 0.10,
                      "31555": 0.12, "33063": 0.10, "06088": 0.10,
                      "67482": 0.12, "59350": 0.12, "34172": 0.10}
    rayon = GRANDES_VILLES.get(code_insee, 0.06)

    # 1) WFS Geoplateforme IGN par bbox (couvre PLUi metropolitain)
    try:
        features = _fetch_plu_wfs(lat, lon, rayon_deg=rayon)
        source = f"API Carto IGN bbox r={rayon}"
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
    })

# â”€â”€â”€ DVF Ã— PLU â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route("/api/croisement/dvf-plu")
def dvf_plu():
    commune = request.args.get("commune", "").strip()
    if not commune:
        return jsonify({"error": "commune manquante"}), 400

    geo = geocode_commune(commune)
    if not geo:
        return jsonify({"error": f"Commune '{commune}' introuvable"}), 404

    try:
        dvf = fetch_dvf(geo["code_insee"], geo["departement"])
    except: dvf = []

    try:
        r2 = requests.get(GPU_API, params={"code_insee": geo["code_insee"], "_limit": 100}, timeout=20)
        plu_features = r2.json().get("features", []) if r2.status_code == 200 else []
    except: plu_features = []

    vals = []
    for m in dvf:
        try: vals.append(float(m["valeur_fonciere"]))
        except: pass

    return jsonify({
        "commune": geo["nom"],
        "dvf_transactions": len(dvf),
        "dvf_prix_moyen": round(sum(vals)/len(vals)) if vals else None,
        "plu_zones_count": len(plu_features),
        "note": "Croisement spatial DVFÃ—PLU nÃ©cessite PostGIS. DonnÃ©es brutes disponibles.",
        "plu_zones_sample": [f.get("properties",{}) for f in plu_features[:10]]
    })

# â”€â”€â”€ SAISONNALITÃ‰ DVF â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route("/api/saisonnalite")
def api_saisonnalite():
    commune = request.args.get("commune", "").strip()
    type_bien = request.args.get("type", "Appartement")
    if not commune:
        return jsonify({"error": "commune manquante"}), 400
    geo = geocode_commune(commune)
    if not geo:
        return jsonify({"error": f"Commune '{commune}' introuvable"}), 404
    mutations = fetch_dvf(geo["code_insee"], geo["departement"])

    # Filtrage
    ventes = []
    for m in mutations:
        if m.get("type_local") != type_bien: continue
        if m.get("nature_mutation") != "Vente": continue
        date = m.get("date_mutation", "")
        if not date or len(date) < 7: continue
        try:
            v = float(m["valeur_fonciere"])
            s = float(m["surface_reelle_bati"])
            if s <= 5 or v <= 0: continue
            pm2 = v / s
            if pm2 < 500 or pm2 > 25000: continue
            annee = date[:4]
            mois  = int(date[5:7])
            ventes.append({"annee": annee, "mois": mois, "pm2": pm2})
        except: continue

    # AgrÃ©gation par mois (toutes annÃ©es confondues)
    MOIS_NOMS = ["Jan","FÃ©v","Mar","Avr","Mai","Juin","Juil","AoÃ»t","Sep","Oct","Nov","DÃ©c"]
    par_mois = {i: [] for i in range(1, 13)}
    for v in ventes:
        par_mois[v["mois"]].append(v["pm2"])

    saisonnalite = []
    for mois in range(1, 13):
        prix = par_mois[mois]
        saisonnalite.append({
            "mois": mois,
            "nom": MOIS_NOMS[mois-1],
            "nb_transactions": len(prix),
            "prix_m2_moyen": round(sum(prix)/len(prix)) if prix else None,
        })

    # AgrÃ©gation par trimestre et annÃ©e
    par_trimestre = {}
    for v in ventes:
        t = (int(v["mois"])-1)//3 + 1
        key = f"{v['annee']}-T{t}"
        par_trimestre.setdefault(key, []).append(v["pm2"])

    evolution = []
    for key in sorted(par_trimestre.keys()):
        prix = par_trimestre[key]
        evolution.append({
            "periode": key,
            "nb_transactions": len(prix),
            "prix_m2_moyen": round(sum(prix)/len(prix)) if prix else None,
        })

    # Meilleur/pire mois pour acheter (prix le plus bas/haut)
    mois_valides = [s for s in saisonnalite if s["prix_m2_moyen"]]
    meilleur = min(mois_valides, key=lambda x: x["prix_m2_moyen"]) if mois_valides else None
    pire     = max(mois_valides, key=lambda x: x["prix_m2_moyen"]) if mois_valides else None

    return jsonify({
        "commune": geo["nom"],
        "type_bien": type_bien,
        "total_ventes": len(ventes),
        "saisonnalite_mensuelle": saisonnalite,
        "evolution_trimestrielle": evolution,
        "conseil": {
            "meilleur_mois_achat": meilleur,
            "pire_mois_achat": pire,
        }
    })


# â”€â”€â”€ SCORE ATTRACTIVITÃ‰ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route("/api/score")
def api_score():
    commune = request.args.get("commune", "").strip()
    if not commune:
        return jsonify({"error": "commune manquante"}), 400
    geo = geocode_commune(commune)
    if not geo:
        return jsonify({"error": f"Commune '{commune}' introuvable"}), 404
    mutations = fetch_dvf(geo["code_insee"], geo["departement"])

    # Filtrage appartements
    ventes = []
    for m in mutations:
        if m.get("type_local") != "Appartement": continue
        if m.get("nature_mutation") != "Vente": continue
        date = m.get("date_mutation", "")
        if not date or len(date) < 4: continue
        try:
            v = float(m["valeur_fonciere"])
            s = float(m["surface_reelle_bati"])
            if s <= 5 or v <= 0: continue
            pm2 = v / s
            if pm2 < 500 or pm2 > 25000: continue
            ventes.append({"annee": int(date[:4]), "pm2": pm2})
        except: continue

    if not ventes:
        return jsonify({"error": "Pas assez de donnÃ©es"}), 404

    # Score volume (nb transactions normalisÃ©)
    score_volume = min(100, len(ventes) / 50)  # 5000 ventes = 100

    # Score tendance prix (variation 2022 â†’ 2024)
    par_annee = {}
    for v in ventes:
        par_annee.setdefault(v["annee"], []).append(v["pm2"])
    prix_annee = {a: round(sum(p)/len(p)) for a, p in par_annee.items() if p}
    annees = sorted(prix_annee.keys())
    if len(annees) >= 2:
        variation = (prix_annee[annees[-1]] - prix_annee[annees[0]]) / prix_annee[annees[0]] * 100
    else:
        variation = 0
    score_tendance = min(100, max(0, 50 + variation * 2))  # centrÃ© sur 0%

    # Score accessibilitÃ© prix (inverse du prix â€” plus c'est cher, moins c'est accessible)
    prix_moyen = sum(v["pm2"] for v in ventes) / len(ventes)
    score_accessibilite = min(100, max(0, 100 - (prix_moyen - 1000) / 60))

    # Score dynamisme (transactions 2024 vs 2022)
    n_2022 = len(par_annee.get(2022, []))
    n_2024 = len(par_annee.get(2024, []))
    if n_2022 > 0:
        ratio = n_2024 / n_2022
        score_dynamisme = min(100, max(0, ratio * 50))
    else:
        score_dynamisme = 50

    score_global = round((score_volume + score_tendance + score_accessibilite + score_dynamisme) / 4)

    return jsonify({
        "commune": geo["nom"],
        "code_insee": geo["code_insee"],
        "score_global": score_global,
        "details": {
            "volume":        round(score_volume),
            "tendance_prix": round(score_tendance),
            "accessibilite": round(score_accessibilite),
            "dynamisme":     round(score_dynamisme),
        },
        "stats": {
            "prix_m2_moyen": round(prix_moyen),
            "variation_pct": round(variation, 1),
            "nb_ventes_total": len(ventes),
            "prix_par_annee": prix_annee,
        }
    })


# â”€â”€â”€ RADAR COMPARATIF â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route("/api/radar")
def api_radar():
    communes_param = request.args.get("communes", "").strip()
    if not communes_param:
        return jsonify({"error": "communes manquantes (ex: ?communes=Marseille,Aix-en-Provence,Toulon)"}), 400

    noms = [c.strip() for c in communes_param.split(",") if c.strip()][:4]  # max 4
    resultats = []

    for nom in noms:
        try:
            geo = geocode_commune(nom)
            if not geo: continue
            mutations = fetch_dvf(geo["code_insee"], geo["departement"])

            ventes = []
            for m in mutations:
                if m.get("type_local") != "Appartement": continue
                if m.get("nature_mutation") != "Vente": continue
                date = m.get("date_mutation", "")
                if not date or len(date) < 4: continue
                try:
                    v = float(m["valeur_fonciere"])
                    s = float(m["surface_reelle_bati"])
                    if s <= 5 or v <= 0: continue
                    pm2 = v / s
                    if pm2 < 500 or pm2 > 25000: continue
                    ventes.append({"annee": int(date[:4]), "pm2": pm2})
                except: continue

            if not ventes: continue

            prix_moyen = sum(v["pm2"] for v in ventes) / len(ventes)
            par_annee  = {}
            for v in ventes:
                par_annee.setdefault(v["annee"], []).append(v["pm2"])
            prix_annee = {a: round(sum(p)/len(p)) for a, p in par_annee.items() if p}
            annees = sorted(prix_annee.keys())
            variation = (prix_annee[annees[-1]] - prix_annee[annees[0]]) / prix_annee[annees[0]] * 100 if len(annees) >= 2 else 0
            n_2022 = len(par_annee.get(2022, []))
            n_2024 = len(par_annee.get(2024, []))

            resultats.append({
                "commune": geo["nom"],
                "code_insee": geo["code_insee"],
                "prix_m2_moyen": round(prix_moyen),
                "variation_pct": round(variation, 1),
                "nb_ventes": len(ventes),
                "dynamisme": round(n_2024/n_2022*100) if n_2022 else 100,
                "accessibilite": round(min(100, max(0, 100 - (prix_moyen - 1000) / 60))),
                "prix_par_annee": prix_annee,
            })
        except Exception as e:
            print(f"[RADAR] Erreur {nom}: {e}")
            continue

    return jsonify({"communes": resultats})


# â”€â”€â”€ CHARGEMENT INDEX INSEE POPULATION â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_INSEE_POP = None
_INSEE_POP_PATH = os.path.join(os.path.dirname(__file__), "cache", "insee_pop.json")

def get_insee_pop():
    """Charge l'index population INSEE en mÃ©moire (lazy load)."""
    global _INSEE_POP
    if _INSEE_POP is None:
        if os.path.exists(_INSEE_POP_PATH):
            with open(_INSEE_POP_PATH, "r", encoding="utf-8") as f:
                _INSEE_POP = json.load(f)
            print(f"[INSEE] Index chargÃ© : {len(_INSEE_POP)} communes")
        else:
            _INSEE_POP = {}
            print("[INSEE] âš  cache/insee_pop.json absent â€” lancez build_insee_pop_index.py")
    return _INSEE_POP


# â”€â”€â”€ DÃ‰MOGRAPHIE INSEE (version enrichie) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route("/api/demographie")
def api_demographie():
    commune = request.args.get("commune", "").strip()
    if not commune:
        return jsonify({"error": "commune manquante"}), 400
    geo = geocode_commune(commune)
    if not geo:
        return jsonify({"error": f"Commune '{commune}' introuvable"}), 404

    code_insee = geo["code_insee"]

    # â”€â”€ 1. Infos de base (geo.api.gouv.fr) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    commune_data = {}
    try:
        r = requests.get(
            f"https://geo.api.gouv.fr/communes/{code_insee}",
            params={"fields": "nom,code,population,codesPostaux,departement,region"},
            timeout=10
        )
        r.raise_for_status()
        commune_data = r.json()
    except Exception:
        pass

    population_actuelle = commune_data.get("population")

    # â”€â”€ 2. Historique population INSEE (index local) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    insee_index = get_insee_pop()
    historique_raw = insee_index.get(code_insee, {})

    # Trier les annÃ©es et calculer la tendance
    historique = {}
    for annee, pop in sorted(historique_raw.items()):
        try:
            historique[annee] = int(pop)
        except:
            pass

    # Tendance dÃ©mographique
    tendance = None
    variation_pop = None
    if len(historique) >= 2:
        annees_triees = sorted(historique.keys())
        pop_debut = historique[annees_triees[0]]
        pop_fin   = historique[annees_triees[-1]]
        if pop_debut > 0:
            variation_pop = round((pop_fin - pop_debut) / pop_debut * 100, 1)
            tendance = "croissance" if variation_pop > 3 else ("dÃ©clin" if variation_pop < -3 else "stable")
        if not population_actuelle:
            population_actuelle = pop_fin

    # â”€â”€ 3. DVF â€” pression immobiliÃ¨re â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    mutations = fetch_dvf(code_insee, geo["departement"])
    ventes = [m for m in mutations if m.get("nature_mutation") == "Vente"
              and m.get("type_local") in ("Appartement", "Maison")]

    prix_moyen = None
    vals = []
    for m in ventes:
        try:
            v = float(m["valeur_fonciere"])
            s = float(m["surface_reelle_bati"])
            if s > 5 and v > 0:
                pm2 = v/s
                if 500 <= pm2 <= 25000:
                    vals.append(pm2)
        except:
            pass
    if vals:
        prix_moyen = round(sum(vals)/len(vals))

    pression = None
    if population_actuelle and population_actuelle > 0 and ventes:
        pression = round(len(ventes) / population_actuelle * 1000, 1)

    # â”€â”€ 4. Score opportunitÃ© investissement â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    score_opp = None
    if tendance and prix_moyen:
        s_croissance = 100 if tendance == "croissance" else (50 if tendance == "stable" else 10)
        s_prix = min(100, max(0, 100 - (prix_moyen - 1000) / 60))
        score_opp = round(s_croissance * 0.6 + s_prix * 0.4)

    # â”€â”€ 5. Conseil narratif â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    conseil = None
    if tendance and prix_moyen:
        if tendance == "croissance" and prix_moyen < 3000:
            conseil = "ðŸŸ¢ OpportunitÃ© : commune en croissance avec prix abordables. Potentiel de valorisation Ã©levÃ©."
        elif tendance == "croissance" and prix_moyen >= 3000:
            conseil = "ðŸŸ¡ MarchÃ© porteur mais dÃ©jÃ  cher. Demande soutenue, risque de stagnation Ã  court terme."
        elif tendance == "stable":
            conseil = "ðŸ”µ MarchÃ© stable. Faible risque, rendement locatif prÃ©visible."
        elif tendance == "dÃ©clin":
            conseil = "ðŸ”´ Population en baisse. Risque de dÃ©prÃ©ciation Ã  moyen terme â€” rendement locatif Ã  surveiller."

    return jsonify({
        "commune": geo["nom"],
        "code_insee": code_insee,
        "population_actuelle": population_actuelle,
        "codes_postaux": commune_data.get("codesPostaux", []),
        "departement": commune_data.get("departement", {}).get("nom") if isinstance(commune_data.get("departement"), dict) else commune_data.get("departement"),
        "region": commune_data.get("region", {}).get("nom") if isinstance(commune_data.get("region"), dict) else commune_data.get("region"),
        "demographie": {
            "historique_population": historique,
            "variation_pct": variation_pop,
            "tendance": tendance,
            "source": "INSEE populations lÃ©gales" if historique else "geo.api.gouv.fr",
        },
        "immobilier": {
            "nb_ventes_2022_2025": len(ventes),
            "prix_m2_moyen": prix_moyen,
            "ventes_pour_1000_hab": pression,
        },
        "score_opportunite": score_opp,
        "conseil": conseil,
    })


# â”€â”€â”€ OPPORTUNITÃ‰S : communes en croissance avec prix bas â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route("/api/opportunites")
def api_opportunites():
    """
    Classe les communes par score d'opportunitÃ© investissement.
    ParamÃ¨tres :
      - departement : filtrer par dÃ©partement (ex: "13", "83", "06")
      - prix_max    : prix/mÂ² max (dÃ©faut: 4000)
      - limit       : nb de rÃ©sultats (dÃ©faut: 20, max: 50)
    """
    dep_filtre = request.args.get("departement", "").strip()
    prix_max   = int(request.args.get("prix_max", 4000))
    limit      = min(int(request.args.get("limit", 20)), 50)

    insee_index = get_insee_pop()
    if not insee_index:
        return jsonify({"error": "Index INSEE absent. Lancez build_insee_pop_index.py"}), 503

    codes_cibles = [
        code for code in insee_index.keys()
        if not dep_filtre or code.startswith(dep_filtre)
    ][:500]  # cap perf

    resultats = []
    for code in codes_cibles:
        historique_raw = insee_index.get(code, {})
        if len(historique_raw) < 1:
            continue
        annees = sorted(historique_raw.keys())
        try:
            pop_debut = int(historique_raw[annees[0]])
            pop_fin   = int(historique_raw[annees[-1]])
        except:
            continue
        if pop_debut <= 0 or pop_fin < 100:
            continue
        # Si 1 seule annÃ©e : variation inconnue, on considÃ¨re stable
        if len(annees) >= 2:
            variation = round((pop_fin - pop_debut) / pop_debut * 100, 1)
        else:
            variation = 0.0  # tendance stable par dÃ©faut

        dvf_path = os.path.join(DVF_INDEX_DIR, f"{code}.json")
        if not os.path.exists(dvf_path):
            continue
        try:
            with open(dvf_path, "r", encoding="utf-8") as f:
                mutations = json.load(f)
        except:
            continue

        vals = []
        for m in mutations:
            if m.get("type_local") not in ("Appartement", "Maison"): continue
            if m.get("nature_mutation") != "Vente": continue
            try:
                v = float(m["valeur_fonciere"]); s = float(m["surface_reelle_bati"])
                if s > 5 and v > 0:
                    pm2 = v/s
                    if 500 <= pm2 <= 25000: vals.append(pm2)
            except: pass

        if len(vals) < 10: continue
        prix_moyen = round(sum(vals)/len(vals))
        if prix_moyen > prix_max: continue

        s_croissance = 100 if variation > 3 else (50 if variation > -3 else 10)
        s_prix       = min(100, max(0, 100 - (prix_moyen - 1000) / 60))
        score        = round(s_croissance * 0.6 + s_prix * 0.4)

        resultats.append({
            "code_insee": code,
            "population": pop_fin,
            "variation_pop_pct": variation,
            "tendance": "croissance" if variation > 3 else ("stable" if variation > -3 else "dÃ©clin"),
            "prix_m2_moyen": prix_moyen,
            "nb_ventes": len(vals),
            "score_opportunite": score,
        })

    resultats.sort(key=lambda x: x["score_opportunite"], reverse=True)

    return jsonify({
        "departement": dep_filtre or "tous",
        "prix_max_filtre": prix_max,
        "nb_communes_analysees": len(resultats),
        "opportunites": resultats[:limit],
    })


# â”€â”€â”€ DENSIFICATION : potentiel constructible par parcelle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Zones PLU constructibles (U = urbain, AU = Ã  urbaniser)
PLU_CONSTRUCTIBLES = {"U", "AU", "1AU", "2AU", "UA", "UB", "UC", "UD", "UE", "UF", "UG",
                      "UH", "UI", "UJ", "UK", "UL", "UM", "UN", "UO", "UP", "UQ", "UR",
                      "US", "UT", "UU", "UV", "UW", "UX", "UY", "UZ"}
PLU_NON_CONSTRUCTIBLES = {"A", "N", "Ap", "Np", "Nj"}  # agricole, naturel


def _bbox_from_point(lat, lon, delta=0.02):
    """Retourne une bbox [minx, miny, maxx, maxy] autour d'un point."""
    return [lon - delta, lat - delta, lon + delta, lat + delta]


def _fetch_cadastre_batiments(code_insee, section=None):
    """
    RÃ©cupÃ¨re les bÃ¢timents cadastraux via l'API Carto IGN.
    Retourne un dict { id_parcelle: surface_batie_m2 }.
    L'endpoint /cadastre/batiment retourne les gÃ©omÃ©tries de bÃ¢timents
    avec l'ID de la parcelle d'appartenance.
    """
    bati_par_parcelle = {}
    params = {"code_insee": code_insee, "_limit": 1000}
    if section:
        params["section"] = section
    try:
        r = requests.get(
            "https://apicarto.ign.fr/api/cadastre/batiment",
            params=params, timeout=25
        )
        if r.status_code != 200:
            return bati_par_parcelle
        for feat in r.json().get("features", []):
            props = feat.get("properties", {})
            # id_parcelle est dans les propriÃ©tÃ©s du bÃ¢timent
            id_parc = props.get("id_parcelle", "") or props.get("parcelle_id", "")
            if not id_parc:
                continue
            # Surface du bÃ¢timent = contenance du bÃ¢timent en mÂ²
            surf = props.get("contenance", 0) or 0
            # Fallback : calculer depuis la gÃ©omÃ©trie (approximation bbox)
            if not surf:
                geom = feat.get("geometry", {})
                coords = geom.get("coordinates", [])
                if geom.get("type") == "Polygon" and coords:
                    ring = coords[0]
                    # Shoelace formula (coordonnÃ©es gÃ©ographiques â†’ approx mÂ²)
                    n = len(ring)
                    area_deg2 = abs(sum(
                        ring[i][0] * ring[(i+1) % n][1] - ring[(i+1) % n][0] * ring[i][1]
                        for i in range(n)
                    ) / 2)
                    # 1Â° lat â‰ˆ 111 000 m, 1Â° lon â‰ˆ 111 000 * cos(lat) m
                    import math
                    lat_rad = math.radians(sum(c[1] for c in ring) / n)
                    surf = area_deg2 * 111_000 * 111_000 * math.cos(lat_rad)
            bati_par_parcelle[id_parc] = bati_par_parcelle.get(id_parc, 0) + surf
    except Exception as e:
        print(f"[BATI] Erreur API bÃ¢timent: {e}")
    return bati_par_parcelle


def _fetch_plu_zones(code_insee, codes_arr=None, lat=None, lon=None):
    """
    RÃ©cupÃ¨re les zones PLU avec gÃ©omÃ©trie via WFS GÃ©oplateforme bbox.
    Fallback sur API Carto IGN si WFS Ã©choue.
    """
    features = []

    # 1) WFS GÃ©oplateforme par bbox (fonctionne pour PLUi mÃ©tropolitain)
    if lat is not None and lon is not None:
        try:
            features = _fetch_plu_wfs(lat, lon, rayon_deg=0.04)
        except Exception as e:
            print(f"[PLU-DENSIF] WFS bbox Ã©chouÃ©: {e}")

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

    # DÃ©doublonnage par id feature
    seen, unique = set(), []
    for f in features:
        fid = f.get("id") or str(f.get("properties", {}).get("gid", id(f)))
        if fid not in seen:
            seen.add(fid)
            unique.append(f)
    return unique


def _point_in_bbox(lon, lat, bbox):
    """Test rapide point-dans-bbox [minx, miny, maxx, maxy]."""
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


def _centroid(geometry):
    """Calcule le centroÃ¯de approximatif d'une gÃ©omÃ©trie GeoJSON."""
    try:
        geom_type = geometry.get("type", "")
        coords = geometry.get("coordinates", [])
        if geom_type == "Point":
            return coords[0], coords[1]
        if geom_type == "Polygon" and coords:
            ring = coords[0]
            lon = sum(c[0] for c in ring) / len(ring)
            lat = sum(c[1] for c in ring) / len(ring)
            return lon, lat
        if geom_type == "MultiPolygon" and coords:
            ring = coords[0][0]
            lon = sum(c[0] for c in ring) / len(ring)
            lat = sum(c[1] for c in ring) / len(ring)
            return lon, lat
    except:
        pass
    return None, None


def _zone_plu_for_parcelle(parc_geom, plu_features_with_bbox):
    """
    Retourne la zone PLU (typezone, libelle) pour une parcelle via test bbox centroÃ¯de.
    """
    lon, lat = _centroid(parc_geom)
    if lon is None:
        return None, None
    for feat, bbox in plu_features_with_bbox:
        if _point_in_bbox(lon, lat, bbox):
            props = feat.get("properties", {})
            return props.get("typezone", "?"), (props.get("libelong") or props.get("libelle", ""))
    return None, None


@app.route("/api/densification")
def api_densification():
    """
    Analyse le potentiel de densification pour une commune.
    ParamÃ¨tres :
      - commune  : nom ou code INSEE
      - section  : section cadastrale (optionnel, ex: 'AB')
      - surf_min : surface minimale parcelle en mÂ² (dÃ©faut: 300)
    Sources :
      - API Carto IGN /cadastre/parcelle  â†’ gÃ©omÃ©trie + contenance rÃ©elle
      - API Carto IGN /cadastre/batiment  â†’ surface bÃ¢tie rÃ©elle par parcelle
      - GPU GÃ©oportail /zone-urba         â†’ zones PLU avec gÃ©omÃ©trie
    """
    commune  = request.args.get("commune", "").strip()
    section  = request.args.get("section", "").strip().upper()
    surf_min = int(request.args.get("surf_min", 300))

    if not commune:
        return jsonify({"error": "ParamÃ¨tre 'commune' requis"}), 400

    geo = geocode_commune(commune)
    if not geo:
        return jsonify({"error": f"Commune '{commune}' introuvable"}), 404

    code_insee = geo["code_insee"]

    try:
        # â”€â”€ 1. Parcelles cadastrales â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        params_parc = {"code_insee": code_insee, "_limit": 1000}
        if section:
            params_parc["section"] = section
        r_parc = requests.get(
            "https://apicarto.ign.fr/api/cadastre/parcelle",
            params=params_parc, timeout=25
        )
        r_parc.raise_for_status()
        parcelles = r_parc.json().get("features", [])

        if not parcelles:
            return jsonify({
                "commune": geo["nom"], "code_insee": code_insee,
                "nb_parcelles_analysees": 0, "nb_avec_potentiel": 0,
                "note": "Aucune parcelle retournÃ©e par l'API Cadastre IGN."
            })

        # â”€â”€ 2. BÃ¢timents cadastraux rÃ©els (surface bÃ¢tie par parcelle) â”€â”€â”€â”€â”€â”€â”€
        bati_par_parcelle = _fetch_cadastre_batiments(code_insee, section or None)
        bati_source = "API Cadastre IGN /batiment" if bati_par_parcelle else "heuristique (API bÃ¢timent vide)"

        # â”€â”€ 3. Zones PLU avec gÃ©omÃ©trie + bbox prÃ©-calculÃ©e â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        plu_features = _fetch_plu_zones(code_insee, lat=geo['lat'], lon=geo['lon'])
        plu_with_bbox = []
        zones_resume = {}
        for feat in plu_features:
            props = feat.get("properties", {})
            typ = props.get("typezone", "?")
            lib = props.get("libelong", "") or props.get("libelle", "")
            zones_resume[typ] = lib
            geom = feat.get("geometry", {})
            # Calcul bbox de la zone PLU
            coords_flat = []
            if geom.get("type") == "Polygon":
                for ring in geom.get("coordinates", []):
                    coords_flat.extend(ring)
            elif geom.get("type") == "MultiPolygon":
                for poly in geom.get("coordinates", []):
                    for ring in poly:
                        coords_flat.extend(ring)
            if coords_flat:
                lons = [c[0] for c in coords_flat]
                lats = [c[1] for c in coords_flat]
                bbox = [min(lons), min(lats), max(lons), max(lats)]
                plu_with_bbox.append((feat, bbox))

        # â”€â”€ 4. Analyse parcelle par parcelle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        resultats = []
        nb_sans_bati_api = 0

        for feat in parcelles:
            p = feat.get("properties", {})

            # Identifiant parcelle IGN = ex: "01173000AI0551"
            id_parc   = p.get("id", "")
            section_p = p.get("section", "")
            numero_p  = p.get("numero", "")
            surf_parc = float(p.get("contenance", 0) or 0)

            if surf_parc < surf_min:
                continue

            # Surface bÃ¢tie : depuis l'API bÃ¢timent, sinon heuristique avouÃ©e
            surf_bati = bati_par_parcelle.get(id_parc, None)
            if surf_bati is None:
                nb_sans_bati_api += 1
                # Heuristique de dernier recours (clairement Ã©tiquetÃ©e comme telle)
                if surf_parc < 200:   h = 0.7
                elif surf_parc < 500: h = 0.5
                elif surf_parc < 2000: h = 0.3
                else:                  h = 0.15
                surf_bati = surf_parc * h
                bati_source_parc = "heuristique"
            else:
                bati_source_parc = "cadastre"

            surf_libre  = max(0.0, surf_parc - surf_bati)
            taux_libre  = round(surf_libre / surf_parc * 100, 1) if surf_parc > 0 else 0

            if taux_libre < 20:
                continue

            # Zone PLU via test centroÃ¯de
            zone_type, zone_lib = _zone_plu_for_parcelle(feat.get("geometry", {}), plu_with_bbox)

            # ConstructibilitÃ© selon PLU
            constructible = None
            if zone_type:
                zone_norm = zone_type.strip().upper()
                if any(zone_norm.startswith(z) for z in PLU_CONSTRUCTIBLES):
                    constructible = True
                elif any(zone_norm.startswith(z) for z in PLU_NON_CONSTRUCTIBLES):
                    constructible = False

            # Score potentiel : surface libre + zone PLU
            if constructible is True:
                potentiel = "fort" if taux_libre > 60 else ("moyen" if taux_libre > 35 else "faible")
            elif constructible is False:
                potentiel = "interdit_plu"
            else:
                potentiel = "fort" if taux_libre > 70 else ("moyen" if taux_libre > 50 else "faible")

            # Prix de rÃ©fÃ©rence DVF pour estimer la valeur de la surface libre
            dvf_path = os.path.join(DVF_INDEX_DIR, f"{code_insee}.json")
            prix_m2_terrain = None
            if os.path.exists(dvf_path):
                # Lu depuis le cache RAM si disponible
                cached = _cache_load(code_insee)
                if cached:
                    terrains = [m for m in cached
                                if "Terrain" in m.get("type_local","")
                                and m.get("nature_mutation") == "Vente"]
                    vals_t = []
                    for t in terrains:
                        try:
                            v = float(t["valeur_fonciere"]); s = float(t["surface_terrain"])
                            if s > 10 and v > 0: vals_t.append(v/s)
                        except: pass
                    if vals_t:
                        prix_m2_terrain = round(sum(vals_t)/len(vals_t))

            result_item = {
                "id_parcelle": id_parc,
                "section": section_p,
                "numero": numero_p,
                "surface_parcelle_m2": round(surf_parc),
                "surface_batie_m2": round(surf_bati),
                "surface_libre_m2": round(surf_libre),
                "taux_libre_pct": taux_libre,
                "source_bati": bati_source_parc,
                "zone_plu": zone_type,
                "zone_plu_libelle": zone_lib,
                "constructible": constructible,
                "potentiel": potentiel,
            }
            if prix_m2_terrain:
                result_item["valeur_libre_estimee_eur"] = round(surf_libre * prix_m2_terrain)
                result_item["prix_m2_terrain_ref"] = prix_m2_terrain

            resultats.append(result_item)

        # Tri : prioritÃ© aux constructibles avec surface libre maximale
        def sort_key(r):
            bonus = 0 if r["constructible"] is True else (
                -10_000_000 if r["constructible"] is False else 0)
            return r["surface_libre_m2"] + bonus

        resultats.sort(key=sort_key, reverse=True)

        # Statistiques de synthÃ¨se
        nb_constructibles   = sum(1 for r in resultats if r["constructible"] is True)
        nb_non_constructibles = sum(1 for r in resultats if r["constructible"] is False)
        surf_libre_totale   = sum(r["surface_libre_m2"] for r in resultats if r["constructible"] is not False)

        return jsonify({
            "commune": geo["nom"],
            "code_insee": code_insee,
            "departement": geo["departement"],
            "section_filtre": section or "toutes",
            "surface_min_filtre_m2": surf_min,
            "nb_parcelles_analysees": len(parcelles),
            "nb_avec_potentiel": len(resultats),
            "nb_constructibles_plu": nb_constructibles,
            "nb_interdits_plu": nb_non_constructibles,
            "surface_libre_totale_m2": round(surf_libre_totale),
            "source_bati": bati_source,
            "bati_api_couverts": len(bati_par_parcelle),
            "bati_heuristique": nb_sans_bati_api,
            "zones_plu": zones_resume,
            "nb_zones_plu": len(plu_features),
            "parcelles": resultats[:50],
            "note": (
                "Surface bÃ¢tie = API Carto IGN /cadastre/batiment (rÃ©el). "
                "Zone PLU = test centroÃ¯de parcelle dans polygone PLU GPU. "
                "ConstructibilitÃ© = typezone U/AU = oui, A/N = non."
            )
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# â”€â”€â”€ LOADER DFI / SITADEL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_dfi_cache         = None
_dfi_commune_cache = None
_sitadel_cache     = None

DFI_BY_COMMUNE = os.path.join(os.path.dirname(__file__), "cache", "dfi_by_commune.json")

DFI_BY_COMMUNE = os.path.join(os.path.dirname(__file__), "cache", "dfi_by_commune.json")

def get_dfi_index():
    global _dfi_cache
    if _dfi_cache is None:
        path = DFI_BY_COMMUNE if os.path.exists(DFI_BY_COMMUNE) else DFI_INDEX
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                _dfi_cache = json.load(f)
    return _dfi_cache or {}

def get_dfi_by_commune():
    """Index DFI prÃ©-groupÃ© par commune. GÃ©nÃ©rÃ© par build_dfi_index.py."""
    global _dfi_commune_cache
    if _dfi_commune_cache is None:
        if os.path.exists(DFI_BY_COMMUNE):
            with open(DFI_BY_COMMUNE, "r", encoding="utf-8") as f:
                _dfi_commune_cache = json.load(f)
            print(f"[DFI] Index commune chargÃ© : {len(_dfi_commune_cache)} communes")
        else:
            _dfi_commune_cache = {}
            print("[DFI] âš  dfi_by_commune.json absent â€” relancez build_dfi_index.py")
    return _dfi_commune_cache

def get_sitadel_index():
    global _sitadel_cache
    if _sitadel_cache is None and os.path.exists(SITADEL_INDEX):
        with open(SITADEL_INDEX, "r", encoding="utf-8") as f:
            _sitadel_cache = json.load(f)
    return _sitadel_cache or {}


def _parse_id_parcelle(id_parc: str) -> dict:
    """
    Parse l'identifiant parcelle DVF (format Etalab 14 chars).
    Exemple : '59090000BM0415'
      code_commune='59090', section='BM', numero='0415'
      â†’ section_numero='BM0415'  â† clÃ© de matching avec DFI (format court)

    Le DFI stocke les refs au format court : 'BM0415' (2 lettres + 4 chiffres).
    Les 4 derniers chars = numÃ©ro, les 2 avant = section.
    """
    s = id_parc.strip()
    result = {"raw": s}

    if len(s) >= 14:
        code_commune = s[:5]
        numero  = s[-4:]
        section = s[-6:-4]
        result.update({
            "code_commune":   code_commune,
            "section":        section,
            "numero":         numero,
            "section_numero": section + numero,
        })
    elif len(s) >= 6:
        result["section_numero"] = s
    return result


def _build_dvf_index_par_parcelle(mutations_dvf: list) -> dict:
    """
    Construit un index { clÃ©_parcelle: [mutation, ...] } depuis les mutations DVF.
    GÃ©nÃ¨re plusieurs clÃ©s par mutation pour maximiser les chances de matching.
    """
    idx = {}

    def _add(key, item):
        if not key:
            return
        if key not in idx:
            idx[key] = []
        idx[key].append(item)

    for m in mutations_dvf:
        id_parc = m.get("id_parcelle", "").strip()
        if not id_parc:
            continue

        parsed = _parse_id_parcelle(id_parc)

        # Valeur fonciÃ¨re toujours en float
        try:
            valeur = float(str(m.get("valeur_fonciere", "") or "").replace(",", "."))
        except:
            valeur = 0.0

        try:
            surface = float(str(m.get("surface_reelle_bati", "") or
                               m.get("surface_terrain", "") or "").replace(",", "."))
        except:
            surface = 0.0

        item = {
            "date":       m.get("date_mutation", ""),
            "valeur":     valeur,
            "nature":     m.get("nature_mutation", ""),
            "type_local": m.get("type_local", ""),
            "surface":    surface,
            "id_parcelle": id_parc,
            "adresse":    f"{m.get('adresse_numero','')} {m.get('adresse_nom_voie','')}".strip(),
        }

        # ClÃ© brute complÃ¨te
        _add(id_parc, item)
        # ClÃ© section+numero court (matching DFI)
        _add(parsed.get("section_numero"), item)
        # ClÃ© prÃ©fixe+section+numero (matching SITADEL)
        _add(parsed.get("prefixe_section_numero"), item)

    return idx


def _match_sitadel_permis(permis_liste: list, refs_mere: set, refs_filles: set) -> list:
    """
    Matching strict SITADEL : le champ ref_cadastrale doit contenir exactement
    une des refs parcellaires (mere ou fille), pas juste partager la section.
    On compare section+numero complet (6 chars) uniquement.
    """
    resultats = []
    refs_norm = set()
    for ref in refs_mere | refs_filles:
        ref = ref.strip()
        if len(ref) == 6:
            refs_norm.add(ref)
        elif len(ref) > 6:
            refs_norm.add(ref[-6:])

    for p in permis_liste:
        ref_cad = p.get("ref_cadastrale", "").strip()
        if not ref_cad:
            continue
        ref_cad_norm = ref_cad[-6:] if len(ref_cad) >= 6 else ref_cad
        if ref_cad_norm in refs_norm:
            resultats.append(p)
    return resultats


# â”€â”€â”€ MARCHANDS DE BIENS : suivi DFI Ã— SITADEL Ã— DVF â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route("/api/marchands")
def api_marchands():
    """
    Identifie les opÃ©rations de marchands de biens sur une commune :
    achat foncier â†’ division parcellaire (DFI) â†’ permis construire (SITADEL) â†’ revente (DVF).

    AmÃ©liorations v2 :
    - Lookup DFI par commune via dfi_by_commune.json (index prÃ©-construit)
    - Parsing correct de l'id_parcelle DVF (format 14-15 chars Etalab)
    - valeur_fonciere convertie en float systÃ©matiquement
    - Matching SITADEL multi-format (section+numero, ref complÃ¨te)
    - DÃ©tection opÃ©rations sans division (achat gros lot â†’ reventes multiples)

    ParamÃ¨tres :
      - commune        : nom ou code INSEE
      - min_plus_value : filtre minimum de plus-value en â‚¬ (dÃ©faut: 0)
    """
    commune = request.args.get("commune", "").strip()
    min_pv  = int(request.args.get("min_plus_value", 0))

    if not commune:
        return jsonify({"error": "ParamÃ¨tre 'commune' requis"}), 400

    geo = geocode_commune(commune)
    if not geo:
        return jsonify({"error": f"Commune '{commune}' introuvable"}), 404

    code_insee = geo["code_insee"]

    # â”€â”€ 1. Chargement donnÃ©es â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    dfi_commune   = get_dfi_by_commune()
    sitadel       = get_sitadel_index()

    # Divisions DFI pour cette commune (lookup direct O(1))
    # Fallback : chercher dans l'index global si dfi_by_commune absent
    if dfi_commune:
        divisions = dfi_commune.get(code_insee, {})
        # Pour grandes villes â†’ agrÃ©ger arrondissements
        if not divisions and code_insee in ARRONDISSEMENTS:
            for arr_code in ARRONDISSEMENTS[code_insee]:
                divisions.update(dfi_commune.get(arr_code, {}))
        dfi_source = "dfi_by_commune.json"
    else:
        # Fallback sur l'index global (lent sur grandes villes)
        dfi_global = get_dfi_index()
        divisions = {
            k: v for k, v in dfi_global.items()
            if k.startswith(code_insee) or k.startswith(code_insee[2:])
        }
        dfi_source = "dfi_index.json (fallback)"

    # Mutations DVF pour la commune (gere arrondissements Paris/Lyon/Marseille)
    mutations_dvf = _cache_load(code_insee) or []
    if not mutations_dvf:
        codes_dvf = ARRONDISSEMENTS.get(code_insee, [code_insee])
        for code_dvf in codes_dvf:
            dvf_path = os.path.join(DVF_INDEX_DIR, f"{code_dvf}.json")
            if os.path.exists(dvf_path):
                try:
                    with open(dvf_path, "r", encoding="utf-8") as f:
                        mutations_dvf.extend(json.load(f))
                except Exception as e:
                    print(f"[MARCHANDS] Erreur lecture DVF {code_dvf}: {e}")
        if mutations_dvf:
            _cache_save(code_insee, mutations_dvf)

    # Permis SITADEL pour la commune
    permis_commune = sitadel.get(code_insee, [])

    # â”€â”€ 2. Index DVF par rÃ©fÃ©rence parcellaire (multi-clÃ©s) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    dvf_idx = _build_dvf_index_par_parcelle(mutations_dvf)

    def get_ventes(ref: str) -> list:
        """RÃ©cupÃ¨re les mutations DVF pour une rÃ©fÃ©rence parcellaire."""
        parsed = _parse_id_parcelle(ref)
        ventes = []
        seen_ids = set()
        for key in [ref,
                    parsed.get("section_numero", ""),
                    parsed.get("prefixe_section_numero", "")]:
            for v in dvf_idx.get(key, []):
                uid = f"{v['date']}_{v['id_parcelle']}_{v['valeur']}"
                if uid not in seen_ids:
                    seen_ids.add(uid)
                    ventes.append(v)
        return ventes

    # â”€â”€ 3. DÃ©tection d'opÃ©rations via DFI (divisions) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    operations = []

    for ref_mere, enfants in divisions.items():
        ventes_mere   = get_ventes(ref_mere)
        ventes_filles = []
        for enf in enfants:
            ventes_filles.extend(get_ventes(enf))

        if not ventes_mere and not ventes_filles:
            continue

        # Filtre promoteurs : > 20 parcelles filles = programme neuf, pas marchand de biens
        if len(enfants) > 20:
            continue

        # Matching SITADEL
        refs_mere_set   = {ref_mere, _parse_id_parcelle(ref_mere).get("section_numero", "")}
        refs_filles_set = set()
        for enf in enfants:
            refs_filles_set.add(enf)
            refs_filles_set.add(_parse_id_parcelle(enf).get("section_numero", ""))
        refs_filles_set.discard("")

        permis_lies = _match_sitadel_permis(permis_commune, refs_mere_set, refs_filles_set)

        # Calcul crÃ©ation de valeur (valeur dÃ©jÃ  en float depuis _build_dvf_index_par_parcelle)
        achats = [v for v in ventes_mere
                  if v["nature"] in ("Vente", "Adjudication", "Expropriation")]
        reventes = [v for v in ventes_filles if v["nature"] == "Vente"]

        # Tri chronologique
        achats.sort(key=lambda x: x["date"])
        reventes.sort(key=lambda x: x["date"])

        # Valeurs
        prix_achat_total   = sum(v["valeur"] for v in achats)
        prix_revente_total = sum(v["valeur"] for v in reventes)
        creation_valeur    = round(prix_revente_total - prix_achat_total)
        plus_value_pct     = round(creation_valeur / prix_achat_total * 100, 1) if prix_achat_total > 0 else None

        if creation_valeur < min_pv:
            continue

        # DurÃ©e de portage (date achat â†’ date derniÃ¨re revente)
        duree_mois = None
        if achats and reventes:
            try:
                from datetime import datetime
                d_achat   = datetime.strptime(achats[0]["date"][:10], "%Y-%m-%d")
                d_revente = datetime.strptime(reventes[-1]["date"][:10], "%Y-%m-%d")
                duree_mois = round((d_revente - d_achat).days / 30)
            except:
                pass

        operations.append({
            "ref_parcelle_mere":   ref_mere,
            "nb_parcelles_filles": len(enfants),
            "refs_filles":         enfants[:5],
            "dfi_source":          dfi_source,

            "nb_permis":  len(permis_lies),
            "permis":     [{"ref": p.get("ref_dossier",""), "annee": p.get("annee",""),
                            "type": p.get("type_dossier",""), "logements": p.get("nb_logements",0)}
                           for p in permis_lies[:3]],

            "nb_achats":   len(achats),
            "achats":      [{"date": v["date"], "valeur": v["valeur"],
                             "nature": v["nature"], "adresse": v["adresse"]}
                            for v in achats[:3]],

            "nb_reventes":  len(reventes),
            "reventes":    [{"date": v["date"], "valeur": v["valeur"],
                             "type": v["type_local"], "adresse": v["adresse"]}
                            for v in reventes[:5]],

            "prix_achat_total_eur":   round(prix_achat_total),
            "prix_revente_total_eur": round(prix_revente_total),
            "creation_valeur_eur":    creation_valeur,
            "plus_value_pct":         plus_value_pct,
            "duree_portage_mois":     duree_mois,
        })

    # â”€â”€ 4. DÃ©tection complÃ©mentaire : ventes en bloc sans DFI â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Un marchand de biens peut aussi acheter sans diviser â†’ plusieurs reventes
    # depuis la mÃªme id_parcelle sur une mÃªme pÃ©riode
    ops_sans_dfi = []
    for id_parc, ventes_parc in dvf_idx.items():
        if len(id_parc) < 14:
            continue
        achats_bloc = [v for v in ventes_parc
                       if v["nature"] in ("Vente", "Adjudication") and v["valeur"] > 0]
        if len(achats_bloc) < 2:
            continue
        # Filtre coproprietes : > 10 transactions = residence avec lots individuels
        if len(achats_bloc) > 10:
            continue
        achats_bloc.sort(key=lambda x: x["date"])
        # Filtre duree : retournement < 36 mois
        try:
            from datetime import datetime
            d1 = datetime.strptime(achats_bloc[0]["date"][:10], "%Y-%m-%d")
            d2 = datetime.strptime(achats_bloc[-1]["date"][:10], "%Y-%m-%d")
            duree_mois = round((d2 - d1).days / 30)
            if duree_mois > 36:
                continue
        except:
            duree_mois = None
        premiere = achats_bloc[0]
        suivantes = achats_bloc[1:]
        prix_premier  = premiere["valeur"]
        prix_suivants = sum(v["valeur"] for v in suivantes)
        cv = round(prix_suivants - prix_premier)
        # Filtre : plus-value min 10 000 EUR et max 500%
        if cv <= 10_000:
            continue
        pv_pct = round(cv / prix_premier * 100, 1)
        if pv_pct > 500:
            continue
        ops_sans_dfi.append({
            "ref_parcelle":        id_parc,
            "type":                "revente_sans_division",
            "nb_transactions":     len(achats_bloc),
            "duree_portage_mois":  duree_mois,
            "achat":               {"date": premiere["date"], "valeur": premiere["valeur"],
                                    "adresse": premiere["adresse"]},
            "reventes":           [{"date": v["date"], "valeur": v["valeur"],
                                    "type": v["type_local"]} for v in suivantes[:5]],
            "creation_valeur_eur": cv,
            "plus_value_pct":      pv_pct,
        })

    ops_sans_dfi.sort(key=lambda x: x["creation_valeur_eur"], reverse=True)
    operations.sort(key=lambda x: x["creation_valeur_eur"], reverse=True)

    return jsonify({
        "commune":            geo["nom"],
        "code_insee":         code_insee,
        "dfi_disponible":     bool(divisions),
        "sitadel_disponible": bool(sitadel),
        "dfi_source":         dfi_source,
        "nb_divisions_commune":       len(divisions),
        "nb_operations_avec_division": len(operations),
        "nb_operations_sans_division": len(ops_sans_dfi),
        "nb_mutations_dvf":           len(mutations_dvf),
        "nb_permis_sitadel":          len(permis_commune),
        "operations_avec_division":   operations[:20],
        "operations_sans_division":   ops_sans_dfi[:10],
        "note": (
            "ops_avec_division = parcelles DFI divisÃ©es + transactions DVF. "
            "ops_sans_division = mÃªme parcelle vendue plusieurs fois (retournement). "
            "valeur_fonciere = prix total acte (peut couvrir plusieurs lots)."
        ),
    })


from rag_chain import register_rag_routes
register_rag_routes(app)

if __name__ == "__main__":
    app.run(debug=True, port=5001)

