from flask import Flask, render_template, jsonify, request
import requests, csv, io, json, os, time, threading
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ─── ENDPOINTS ─────────────────────────────────────────────────────────────────
# DVF : fichiers locaux (téléchargés depuis data.gouv.fr)
DVF_BASE   = "https://files.data.gouv.fr/geo-dvf/latest/csv"  # fallback réseau
DVF_LOCAL  = {
    "2022": os.path.join(os.path.dirname(__file__), "Data", "full (2).csv.gz"),
    "2023": os.path.join(os.path.dirname(__file__), "Data", "full (1).csv.gz"),
    "2024": os.path.join(os.path.dirname(__file__), "Data", "full.csv.gz"),
    "2025": os.path.join(os.path.dirname(__file__), "Data", "full (3).csv.gz"),
}
# DPE ADEME : dataset dpe03existant (logements existants depuis juillet 2021)
DPE_API    = "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines"
# API Carto GPU → endpoint simplifié par code INSEE
GPU_API    = "https://apicarto.ign.fr/api/gpu/zone-urba"
GEOCODE_API  = "https://api-adresse.data.gouv.fr/search/"
# API Carto cadastre IGN (parcelles + bâti)
CADELSTRE_API = "https://apicarto.ign.fr/api/cadastre"
# DFI index local (généré par build_dfi_index.py)
DFI_INDEX     = os.path.join(os.path.dirname(__file__), "cache", "dfi_index.json")
# SITADEL index local (généré par build_sitadel_index.py)
SITADEL_INDEX = os.path.join(os.path.dirname(__file__), "cache", "sitadel_index.json")

# ─── UTILS ────────────────────────────────────────────────────────────────────
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
    dep = props.get("citycode", "")[:2]  # 2 premiers chiffres = département
    return {
        "lat": lat, "lon": lon,
        "code_insee": props.get("citycode", ""),
        "departement": dep,
        "nom": props.get("label", "")
    }

# ─── CACHE DVF ──────────────────────────────────────────────────────────────────────
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
    """Charge depuis RAM, puis fichier, sinon None"""
    with _cache_lock:
        if code_insee in _mem_cache:
            return _mem_cache[code_insee]
    path = _cache_path(code_insee)
    if _cache_valid(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        with _cache_lock:
            _mem_cache[code_insee] = data
        return data
    return None

def _cache_save(code_insee, mutations):
    """Sauvegarde en fichier JSON et en RAM"""
    path = _cache_path(code_insee)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mutations, f, ensure_ascii=False)
    with _cache_lock:
        _mem_cache[code_insee] = mutations

# Grandes villes découpées en arrondissements
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
    """Lit les fichiers JSON pré-indexés par commune (build_dvf_index.py). Cache RAM."""
    # 1. Cache RAM
    cached = _cache_load(code_insee)
    if cached is not None:
        return cached

    # Codes à chercher (arrondissements ou commune simple)
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

# ─── ROUTE PRINCIPALE ─────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

# ─── DVF PAR ARRONDISSEMENT ──────────────────────────────────────────────────
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
        return jsonify({"error": f"{geo['nom']} n'est pas découpée en arrondissements"}), 400
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
            if v <= 0 or s <= 5: continue  # surface minimum 5m²
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

# ─── DVF ──────────────────────────────────────────────────────────────────────
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
        return jsonify({"error": f"Pas de données DVF pour {geo['nom']} (dep {geo['departement']})"}), 404

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

# ─── DPE ──────────────────────────────────────────────────────────────────────
@app.route("/api/dpe")
def api_dpe():
    commune = request.args.get("commune", "").strip()
    if not commune:
        return jsonify({"error": "commune manquante"}), 400

    geo = geocode_commune(commune)
    if not geo:
        return jsonify({"error": f"Commune '{commune}' introuvable"}), 404

    try:
        # Champs réels du dataset dpe03existant (minuscules)
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

# ─── PRIME VERTE DVF × DPE ────────────────────────────────────────────────────
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
        "methode": "matching par surface arrondie ±5m²",
        "prix_par_classe_dpe": result_classes,
        "prime_verte_estimee": {
            "valeur_eur_m2": prime,
            "description": "Différence prix/m² entre biens A-C vs E-G"
        }
    })

# ─── PLU ──────────────────────────────────────────────────────────────────────
@app.route("/api/plu")
def api_plu():
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
    })

# ─── DVF × PLU ────────────────────────────────────────────────────────────────
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
        "note": "Croisement spatial DVF×PLU nécessite PostGIS. Données brutes disponibles.",
        "plu_zones_sample": [f.get("properties",{}) for f in plu_features[:10]]
    })

# ─── SAISONNALITÉ DVF ────────────────────────────────────────────────────────
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

    # Agrégation par mois (toutes années confondues)
    MOIS_NOMS = ["Jan","Fév","Mar","Avr","Mai","Juin","Juil","Août","Sep","Oct","Nov","Déc"]
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

    # Agrégation par trimestre et année
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


# ─── SCORE ATTRACTIVITÉ ───────────────────────────────────────────────────────
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
        return jsonify({"error": "Pas assez de données"}), 404

    # Score volume (nb transactions normalisé)
    score_volume = min(100, len(ventes) / 50)  # 5000 ventes = 100

    # Score tendance prix (variation 2022 → 2024)
    par_annee = {}
    for v in ventes:
        par_annee.setdefault(v["annee"], []).append(v["pm2"])
    prix_annee = {a: round(sum(p)/len(p)) for a, p in par_annee.items() if p}
    annees = sorted(prix_annee.keys())
    if len(annees) >= 2:
        variation = (prix_annee[annees[-1]] - prix_annee[annees[0]]) / prix_annee[annees[0]] * 100
    else:
        variation = 0
    score_tendance = min(100, max(0, 50 + variation * 2))  # centré sur 0%

    # Score accessibilité prix (inverse du prix — plus c'est cher, moins c'est accessible)
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


# ─── RADAR COMPARATIF ─────────────────────────────────────────────────────────
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


# ─── CHARGEMENT INDEX INSEE POPULATION ───────────────────────────────────────
_INSEE_POP = None
_INSEE_POP_PATH = os.path.join(os.path.dirname(__file__), "cache", "insee_pop.json")

def get_insee_pop():
    """Charge l'index population INSEE en mémoire (lazy load)."""
    global _INSEE_POP
    if _INSEE_POP is None:
        if os.path.exists(_INSEE_POP_PATH):
            with open(_INSEE_POP_PATH, "r", encoding="utf-8") as f:
                _INSEE_POP = json.load(f)
            print(f"[INSEE] Index chargé : {len(_INSEE_POP)} communes")
        else:
            _INSEE_POP = {}
            print("[INSEE] ⚠ cache/insee_pop.json absent — lancez build_insee_pop_index.py")
    return _INSEE_POP


# ─── DÉMOGRAPHIE INSEE (version enrichie) ─────────────────────────────────────
@app.route("/api/demographie")
def api_demographie():
    commune = request.args.get("commune", "").strip()
    if not commune:
        return jsonify({"error": "commune manquante"}), 400
    geo = geocode_commune(commune)
    if not geo:
        return jsonify({"error": f"Commune '{commune}' introuvable"}), 404

    code_insee = geo["code_insee"]

    # ── 1. Infos de base (geo.api.gouv.fr) ─────────────────────────────────────
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

    # ── 2. Historique population INSEE (index local) ────────────────────────────
    insee_index = get_insee_pop()
    historique_raw = insee_index.get(code_insee, {})

    # Trier les années et calculer la tendance
    historique = {}
    for annee, pop in sorted(historique_raw.items()):
        try:
            historique[annee] = int(pop)
        except:
            pass

    # Tendance démographique
    tendance = None
    variation_pop = None
    if len(historique) >= 2:
        annees_triees = sorted(historique.keys())
        pop_debut = historique[annees_triees[0]]
        pop_fin   = historique[annees_triees[-1]]
        if pop_debut > 0:
            variation_pop = round((pop_fin - pop_debut) / pop_debut * 100, 1)
            tendance = "croissance" if variation_pop > 3 else ("déclin" if variation_pop < -3 else "stable")
        if not population_actuelle:
            population_actuelle = pop_fin

    # ── 3. DVF — pression immobilière ──────────────────────────────────────────
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

    # ── 4. Score opportunité investissement ────────────────────────────────────
    score_opp = None
    if tendance and prix_moyen:
        s_croissance = 100 if tendance == "croissance" else (50 if tendance == "stable" else 10)
        s_prix = min(100, max(0, 100 - (prix_moyen - 1000) / 60))
        score_opp = round(s_croissance * 0.6 + s_prix * 0.4)

    # ── 5. Conseil narratif ─────────────────────────────────────────────────────
    conseil = None
    if tendance and prix_moyen:
        if tendance == "croissance" and prix_moyen < 3000:
            conseil = "🟢 Opportunité : commune en croissance avec prix abordables. Potentiel de valorisation élevé."
        elif tendance == "croissance" and prix_moyen >= 3000:
            conseil = "🟡 Marché porteur mais déjà cher. Demande soutenue, risque de stagnation à court terme."
        elif tendance == "stable":
            conseil = "🔵 Marché stable. Faible risque, rendement locatif prévisible."
        elif tendance == "déclin":
            conseil = "🔴 Population en baisse. Risque de dépréciation à moyen terme — rendement locatif à surveiller."

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
            "source": "INSEE populations légales" if historique else "geo.api.gouv.fr",
        },
        "immobilier": {
            "nb_ventes_2022_2025": len(ventes),
            "prix_m2_moyen": prix_moyen,
            "ventes_pour_1000_hab": pression,
        },
        "score_opportunite": score_opp,
        "conseil": conseil,
    })


# ─── OPPORTUNITÉS : communes en croissance avec prix bas ─────────────────────
@app.route("/api/opportunites")
def api_opportunites():
    """
    Classe les communes par score d'opportunité investissement.
    Paramètres :
      - departement : filtrer par département (ex: "13", "83", "06")
      - prix_max    : prix/m² max (défaut: 4000)
      - limit       : nb de résultats (défaut: 20, max: 50)
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
        # Si 1 seule année : variation inconnue, on considère stable
        if len(annees) >= 2:
            variation = round((pop_fin - pop_debut) / pop_debut * 100, 1)
        else:
            variation = 0.0  # tendance stable par défaut

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
            "tendance": "croissance" if variation > 3 else ("stable" if variation > -3 else "déclin"),
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


# ─── DENSIFICATION : potentiel constructible par parcelle ────────────────────
@app.route("/api/densification")
def api_densification():
    """
    Analyse le potentiel de densification pour une commune.
    Paramètres :
      - commune : nom ou code INSEE
      - section : section cadastrale (optionnel, ex: 'AB')
    Source : API Carto cadastre IGN (parcelles + bâti) × GPU (PLU)
    """
    commune  = request.args.get("commune", "").strip()
    section  = request.args.get("section", "").strip().upper()

    if not commune:
        return jsonify({"error": "Paramètre 'commune' requis"}), 400

    # Résolution commune → code INSEE + coords
    geo = geocode_commune(commune)
    if not geo:
        return jsonify({"error": f"Commune '{commune}' introuvable"}), 404

    code_insee = geo["code_insee"]
    lat, lon   = geo["lat"], geo["lon"]

    try:
        # 1) Parcelles cadastrales de la commune (API Carto IGN)
        params_parc = {"code_insee": code_insee, "_limit": 500}
        if section:
            params_parc["section"] = section
        r_parc = requests.get(
            "https://apicarto.ign.fr/api/cadastre/parcelle",
            params=params_parc, timeout=20
        )
        r_parc.raise_for_status()
        parcelles = r_parc.json().get("features", [])

        # 2) Pas d'endpoint batiment sur API Carto IGN
        # On utilise la surface de contenance de la parcelle vs surface batie
        # estimee depuis le champ arpente (non disponible) -> on se base sur
        # le ratio contenance vs surface calculee depuis la geometrie GeoJSON
        bati_par_parcelle = {}
        for feat in parcelles:
            p = feat.get("properties", {})
            ref = p.get("id", "") or p.get("numero", "")
            # Estimation surface batie : contenance - surface geometrie libre
            # Sans donnee bati, on estime 30% de bati moyen par defaut
            # Les parcelles sans bati auront contenance = surface totale
            surf_parc = p.get("contenance", 0) or 0
            # Heuristique : petites parcelles (<500m2) = souvent 60% bati
            # grandes parcelles (>2000m2) = souvent 20% bati
            if surf_parc < 200:
                ratio_bati = 0.7
            elif surf_parc < 500:
                ratio_bati = 0.5
            elif surf_parc < 2000:
                ratio_bati = 0.3
            else:
                ratio_bati = 0.15
            bati_par_parcelle[ref] = round(surf_parc * ratio_bati)

        # 3) Zonage PLU pour la commune
        try:
            r_plu = requests.get(
                GPU_API,
                params={"code_insee": code_insee, "_limit": 50},
                timeout=15
            )
            zones_plu = r_plu.json().get("features", []) if r_plu.ok else []
        except:
            zones_plu = []

        # Résumé zones PLU
        zones_resume = {}
        for z in zones_plu:
            p = z.get("properties", {})
            lib = p.get("libelle", "") or p.get("libelong", "")
            typ = p.get("typezone", "")
            zones_resume[typ] = lib

        # 4) Analyse potentiel densification
        resultats = []
        for feat in parcelles[:200]:  # cap à 200 pour la perf
            p = feat.get("properties", {})
            ref_parc    = p.get("id", "") or p.get("numero", "")
            surf_parc   = p.get("contenance", 0) or 0   # m² parcelle
            surf_bati   = bati_par_parcelle.get(ref_parc, 0)
            surf_libre  = max(0, surf_parc - surf_bati)
            ratio_libre = round(surf_libre / surf_parc * 100, 1) if surf_parc > 0 else 0

            # Filtre : parcelles significatives avec du libre
            if surf_parc < 200 or ratio_libre < 30:
                continue

            section_parc = p.get("section", "")
            numero_parc  = p.get("numero", "")
            ref_cadastre = f"{code_insee[:2]}{code_insee[2:]}{section_parc}{numero_parc}"

            potentiel = "fort" if ratio_libre > 70 else ("moyen" if ratio_libre > 50 else "faible")

            resultats.append({
                "ref_parcelle": ref_parc,
                "ref_cadastrale": ref_cadastre,
                "section": section_parc,
                "surface_parcelle_m2": surf_parc,
                "surface_bati_m2": round(surf_bati),
                "surface_libre_m2": round(surf_libre),
                "taux_libre_pct": ratio_libre,
                "potentiel": potentiel,
            })

        resultats.sort(key=lambda x: x["surface_libre_m2"], reverse=True)

        return jsonify({
            "commune": geo["nom"],
            "code_insee": code_insee,
            "departement": geo["departement"],
            "section_filtre": section or "toutes",
            "nb_parcelles_analysees": len(parcelles),
            "nb_avec_potentiel": len(resultats),
            "zones_plu": zones_resume,
            "parcelles": resultats[:50],
            "note": "Potentiel calculé sur ratio surface libre / surface totale parcelle. Vérifier PLU local."
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── LOADER DFI / SITADEL ────────────────────────────────────────────────────
_dfi_cache      = None
_sitadel_cache  = None

def get_dfi_index():
    global _dfi_cache
    if _dfi_cache is None and os.path.exists(DFI_INDEX):
        with open(DFI_INDEX, "r", encoding="utf-8") as f:
            _dfi_cache = json.load(f)
    return _dfi_cache or {}

def get_sitadel_index():
    global _sitadel_cache
    if _sitadel_cache is None and os.path.exists(SITADEL_INDEX):
        with open(SITADEL_INDEX, "r", encoding="utf-8") as f:
            _sitadel_cache = json.load(f)
    return _sitadel_cache or {}


# ─── MARCHANDS DE BIENS : suivi DFI × SITADEL × DVF ─────────────────────────
@app.route("/api/marchands")
def api_marchands():
    """
    Identifie les opérations de marchands de biens sur une commune :
    achat foncier → division parcellaire (DFI) → permis construire (SITADEL) → revente (DVF).
    Paramètres :
      - commune : nom ou code INSEE
    """
    commune = request.args.get("commune", "").strip()
    if not commune:
        return jsonify({"error": "Paramètre 'commune' requis"}), 400

    geo = geocode_commune(commune)
    if not geo:
        return jsonify({"error": f"Commune '{commune}' introuvable"}), 404

    code_insee = geo["code_insee"]
    dfi       = get_dfi_index()
    sitadel   = get_sitadel_index()

    # Mutations DVF pour la commune
    dvf_path = os.path.join(DVF_INDEX_DIR, f"{code_insee}.json")
    mutations_dvf = []
    if os.path.exists(dvf_path):
        try:
            with open(dvf_path, "r", encoding="utf-8") as f:
                mutations_dvf = json.load(f)
        except:
            pass

    # Index DVF par référence parcellaire courte (format DFI = 6 derniers chars de id_parcelle)
    # id_parcelle DVF = 14 chars : CCCCC + PPPP + SS + NNNN  ex: 01173000AI0551
    # format DFI = section+numero : AI0551 (6 derniers chars)
    dvf_par_parcelle = {}
    for m in mutations_dvf:
        id_parc = m.get("id_parcelle", "").strip()
        if id_parc and len(id_parc) >= 6:
            # Cle courte = 6 derniers chars (section 1-2 lettres + numero 4 chiffres)
            ref_court = id_parc[-6:].lstrip("0") or id_parc[-6:]
            # Aussi stocker la version brute pour matching exact
            refs = {id_parc[-6:], id_parc[8:] if len(id_parc) >= 14 else ""}
            refs.discard("")
        else:
            refs = set()

        for ref in refs:
            if not ref:
                continue
            if ref not in dvf_par_parcelle:
                dvf_par_parcelle[ref] = []
            dvf_par_parcelle[ref].append({
                "date": m.get("date_mutation", ""),
                "valeur": m.get("valeur_fonciere", 0),
                "nature": m.get("nature_mutation", ""),
                "type_local": m.get("type_local", ""),
                "surface": m.get("surface_reelle_bati", 0) or m.get("surface_terrain", 0),
                "id_parcelle": id_parc,
            })

    # DFI pour la commune (divisions)
    divisions_commune = {
        k: v for k, v in dfi.items()
        if k.startswith(code_insee) or k.startswith(code_insee[2:])
    }

    # SITADEL pour la commune
    permis_commune = sitadel.get(code_insee, [])

    # Croisement : parcelles avec division + permis + ventes
    operations = []
    for ref_mere, enfants in divisions_commune.items():
        # Chercher ventes sur parcelle mère
        ventes_mere = dvf_par_parcelle.get(ref_mere, [])
        # Chercher ventes sur parcelles filles
        ventes_filles = []
        for enf in enfants:
            ventes_filles.extend(dvf_par_parcelle.get(enf, []))
        # Chercher permis sur la zone
        permis_lies = [p for p in permis_commune
                       if any(ref_mere in (p.get("ref_cadastrale", "")) for _ in [1])]

        # Filtre : au moins 1 vente mère + 1 vente fille = opération détectée
        if not ventes_mere and not ventes_filles:
            continue

        # Calcul création valeur
        prix_achat  = sum(v["valeur"] for v in ventes_mere if v["valeur"]) or 0
        prix_revente = sum(v["valeur"] for v in ventes_filles if v["valeur"]) or 0
        creation_valeur = round(prix_revente - prix_achat)
        plus_value_pct  = round((creation_valeur / prix_achat * 100), 1) if prix_achat > 0 else None

        operations.append({
            "ref_parcelle_mere": ref_mere,
            "nb_parcelles_filles": len(enfants),
            "refs_filles": enfants[:5],
            "nb_permis": len(permis_lies),
            "permis": [{"ref": p.get("ref_dossier",""), "annee": p.get("annee",""), "type": p.get("type_dossier","")} for p in permis_lies[:3]],
            "achats": [{"date": v["date"], "valeur": v["valeur"], "nature": v["nature"]} for v in sorted(ventes_mere, key=lambda x: x["date"])[:3]],
            "reventes": [{"date": v["date"], "valeur": v["valeur"], "type": v["type_local"]} for v in sorted(ventes_filles, key=lambda x: x["date"])[:5]],
            "prix_achat_total": prix_achat,
            "prix_revente_total": prix_revente,
            "creation_valeur_eur": creation_valeur,
            "plus_value_pct": plus_value_pct,
        })

    operations.sort(key=lambda x: abs(x["creation_valeur_eur"]), reverse=True)

    dfi_disponible    = bool(dfi)
    sitadel_disponible = bool(sitadel)

    return jsonify({
        "commune": geo["nom"],
        "code_insee": code_insee,
        "dfi_disponible": dfi_disponible,
        "sitadel_disponible": sitadel_disponible,
        "nb_divisions_trouvees": len(divisions_commune),
        "nb_operations_detectees": len(operations),
        "nb_mutations_dvf": len(mutations_dvf),
        "operations": operations[:20],
        "note": "Opération = parcelle mère divisée (DFI) avec transactions DVF sur mère et/ou filles. Buildez dfi_index.json et sitadel_index.json pour résultats complets."
    })


if __name__ == "__main__":
    app.run(debug=True, port=5001)
