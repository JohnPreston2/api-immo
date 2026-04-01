"""
build_rag_index.py
==================
Module 1 — RAG API Immo
Transforme les données DVF/INSEE/DPE en documents textuels narratifs,
les découpe en child chunks, les embedde via sentence-transformers (local CPU),
et les insère dans ChromaDB persistent local.

Architecture parent-child (identique SanteVeille) :
  - Parent : fiche synthèse commune complète (~8-12K chars)
  - Child  : blocs thématiques courts (~400-600 tokens) pour embedding sémantique

Usage :
  python build_rag_index.py                     # build toutes communes prioritaires
  python build_rag_index.py --dept 13           # filtrer un département
  python build_rag_index.py --limit 500         # cap nombre de communes
  python build_rag_index.py --reset             # repartir de zéro (efface ChromaDB)

Prérequis :
  pip install chromadb requests
  pip install sentence-transformers
"""

import os, json, time, argparse, re, math, logging
from datetime import datetime
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
CACHE_DIR      = BASE_DIR / "cache"
DVF_INDEX_DIR  = CACHE_DIR / "dvf"
INSEE_POP_PATH = CACHE_DIR / "insee_pop.json"
SITADEL_PATH   = CACHE_DIR / "sitadel_index.json"
CHROMA_DIR     = CACHE_DIR / "rag_chroma"
PARENTS_STORE  = CACHE_DIR / "rag_parents.json"
PROGRESS_FILE  = CACHE_DIR / "rag_progress.json"
LOG_FILE       = CACHE_DIR / "rag_build.log"

CHROMA_DIR.mkdir(parents=True, exist_ok=True)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("rag_builder")

# ── Config ───────────────────────────────────────────────────────────────────
EMBED_MODEL      = "all-MiniLM-L6-v2"   # sentence-transformers, 22MB, CPU rapide
CHROMA_COLLECTION = "api_immo"
MIN_VENTES       = 20          # ignorer communes trop peu actives
MAX_PARENT_CHARS = 12_000      # cap parent doc (comme SanteVeille)
CHUNK_TARGET_TOKENS = 450      # taille cible child chunk
BATCH_EMBED      = 50          # communes par batch avant flush ChromaDB (augmenté car embed rapide)
PAUSE_BETWEEN_BATCHES = 0.0    # pas de pause nécessaire (CPU, pas GPU)

# ── Modèle embedding (chargé une seule fois) ──────────────────────────────────
_embed_model = None

def get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        log.info(f"Chargement modèle embedding : {EMBED_MODEL}")
        _embed_model = SentenceTransformer(EMBED_MODEL)
        log.info("Modèle embedding prêt.")
    return _embed_model


# ════════════════════════════════════════════════════════════════════════════
# SECTION 1 — SYNTHÉTISEUR DVF → TEXTE NARRATIF
# ════════════════════════════════════════════════════════════════════════════

ARRONDISSEMENTS = {
    "69123": [f"693{i:02d}" for i in range(81, 90)],
    "75056": [f"751{i:02d}" for i in range(1, 21)],
    "13055": [f"13{200+i}" for i in range(1, 17)],
}

ARRONDISSEMENT_NOMS = {
    **{f"693{i:02d}": f"Lyon {i-80}e" for i in range(81, 90)},
    **{f"751{i:02d}": f"Paris {i}e" for i in range(1, 21)},
    **{f"13{200+i}": f"Marseille {i}e" for i in range(1, 17)},
}

MOIS_NOMS = ["jan","fév","mar","avr","mai","jun","jul","aoû","sep","oct","nov","déc"]


def _safe_float(val, default=None):
    try:
        v = float(str(val).replace(",", ".").strip())
        return v if math.isfinite(v) else default
    except:
        return default


def _prix_stats(vals):
    """Retourne dict stats prix/m² depuis une liste de valeurs."""
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    return {
        "count":   n,
        "moyen":   round(sum(s) / n),
        "median":  round(s[n // 2]),
        "p10":     round(s[max(0, n // 10)]),
        "p90":     round(s[min(n-1, n * 9 // 10)]),
        "min":     round(s[0]),
        "max":     round(s[-1]),
    }


def compute_dvf_stats(mutations):
    """
    Calcule les statistiques DVF depuis la liste de mutations brutes.
    Retourne un dict structuré avec stats par type, évolution annuelle, saisonnalité.
    """
    apparts, maisons, terrains = [], [], []
    par_annee = {}
    par_mois  = {i: [] for i in range(1, 13)}
    recentes  = []

    for m in mutations:
        if m.get("nature_mutation") != "Vente":
            continue

        type_local = m.get("type_local", "")
        date_str   = m.get("date_mutation", "")
        vf         = _safe_float(m.get("valeur_fonciere"))
        srb        = _safe_float(m.get("surface_reelle_bati"))
        st         = _safe_float(m.get("surface_terrain"))

        # Prix/m² bati
        pm2 = None
        if vf and srb and srb > 5 and vf > 0:
            pm2_candidate = vf / srb
            if 500 <= pm2_candidate <= 25000:
                pm2 = pm2_candidate

        if pm2 and type_local == "Appartement":
            apparts.append(pm2)
        elif pm2 and type_local == "Maison":
            maisons.append(pm2)
        elif type_local and "Terrain" in type_local and vf and st and st > 0:
            terrains.append(vf / st)

        # Évolution annuelle
        if pm2 and date_str and len(date_str) >= 4:
            annee = date_str[:4]
            par_annee.setdefault(annee, []).append(pm2)
            mois = int(date_str[5:7]) if len(date_str) >= 7 else None
            if mois:
                par_mois[mois].append(pm2)

        # Transactions récentes
        if vf and date_str:
            recentes.append({
                "date": date_str,
                "type": type_local,
                "valeur": int(vf),
                "surface": int(srb or st or 0),
            })

    # Évolution annuelle texte
    evolution_annee = {}
    for annee, vals in sorted(par_annee.items()):
        if vals:
            evolution_annee[annee] = round(sum(vals) / len(vals))

    # Tendance : variation entre première et dernière année
    tendance_pct = None
    annees_sorted = sorted(evolution_annee.keys())
    if len(annees_sorted) >= 2:
        p_debut = evolution_annee[annees_sorted[0]]
        p_fin   = evolution_annee[annees_sorted[-1]]
        if p_debut > 0:
            tendance_pct = round((p_fin - p_debut) / p_debut * 100, 1)

    # Saisonnalité (mois le moins/plus cher)
    mois_stats = {}
    for mois, vals in par_mois.items():
        if len(vals) >= 3:
            mois_stats[mois] = round(sum(vals) / len(vals))

    recentes_top = sorted(recentes, key=lambda x: x["date"], reverse=True)[:10]

    return {
        "appartements": _prix_stats(apparts),
        "maisons":      _prix_stats(maisons),
        "terrains":     _prix_stats(terrains),
        "evolution_annuelle": evolution_annee,
        "tendance_pct": tendance_pct,
        "mois_stats":   mois_stats,
        "transactions_recentes": recentes_top,
        "total_mutations": len(mutations),
    }


def synthesize_commune_to_text(code_insee, nom_commune, dvf_stats, insee_pop, sitadel_data):
    """
    Transforme les données structurées d'une commune en texte narratif riche
    pour l'embedding sémantique. Organisé en sections thématiques.
    Retourne (parent_text, list_of_child_chunks).
    """
    sections = []

    # ── Section 1 : Identité commune ─────────────────────────────────────────
    dept = code_insee[:2] if len(code_insee) >= 2 else "?"
    historique_pop = insee_pop.get(code_insee, {})
    annees_pop = sorted(historique_pop.keys())
    pop_actuelle = historique_pop.get(annees_pop[-1]) if annees_pop else None

    variation_pop = None
    tendance_demo = "inconnue"
    if len(annees_pop) >= 2:
        p0 = int(historique_pop[annees_pop[0]])
        p1 = int(historique_pop[annees_pop[-1]])
        if p0 > 0:
            variation_pop = round((p1 - p0) / p0 * 100, 1)
            tendance_demo = "croissance" if variation_pop > 3 else ("déclin" if variation_pop < -3 else "stable")

    id_lines = [
        f"COMMUNE : {nom_commune} (code INSEE {code_insee}, département {dept})",
    ]
    if pop_actuelle:
        id_lines.append(f"Population : {int(pop_actuelle):,} habitants ({annees_pop[-1]})".replace(",", " "))
    if variation_pop is not None:
        id_lines.append(
            f"Démographie : {tendance_demo} — variation {'+' if variation_pop >= 0 else ''}{variation_pop}% "
            f"entre {annees_pop[0]} et {annees_pop[-1]}"
        )
    if len(annees_pop) >= 2:
        hist_str = " | ".join(f"{a}: {int(historique_pop[a]):,}".replace(",", " ") for a in annees_pop)
        id_lines.append(f"Historique population : {hist_str}")

    sections.append(("identite", "\n".join(id_lines)))

    # ── Section 2 : DVF Appartements ─────────────────────────────────────────
    appt = dvf_stats.get("appartements")
    if appt:
        lines = [
            f"MARCHÉ APPARTEMENTS — {nom_commune}",
            f"Nombre de ventes analysées : {appt['count']}",
            f"Prix au m² moyen : {appt['moyen']:,} €/m²".replace(",", " "),
            f"Prix au m² médian : {appt['median']:,} €/m²".replace(",", " "),
            f"Fourchette : {appt['p10']:,} €/m² (10e percentile) à {appt['p90']:,} €/m² (90e percentile)".replace(",", " "),
            f"Extrêmes observés : {appt['min']:,} €/m² minimum, {appt['max']:,} €/m² maximum".replace(",", " "),
        ]
        ev = dvf_stats.get("evolution_annuelle", {})
        if ev:
            ev_str = " → ".join(f"{a}: {p:,}€".replace(",", " ") for a, p in sorted(ev.items()))
            lines.append(f"Évolution prix/m² annuelle : {ev_str}")
        tp = dvf_stats.get("tendance_pct")
        if tp is not None:
            signe = "+" if tp >= 0 else ""
            qualif = "hausse" if tp > 5 else ("légère hausse" if tp > 0 else ("baisse" if tp < -5 else "légère baisse"))
            lines.append(f"Tendance générale : {qualif} de {signe}{tp}% sur la période")
        sections.append(("dvf_appartements", "\n".join(lines)))

    # ── Section 3 : DVF Maisons ───────────────────────────────────────────────
    mais = dvf_stats.get("maisons")
    if mais:
        lines = [
            f"MARCHÉ MAISONS — {nom_commune}",
            f"Nombre de ventes : {mais['count']}",
            f"Prix au m² moyen : {mais['moyen']:,} €/m²".replace(",", " "),
            f"Prix au m² médian : {mais['median']:,} €/m²".replace(",", " "),
            f"Fourchette : {mais['p10']:,} à {mais['p90']:,} €/m²".replace(",", " "),
        ]
        sections.append(("dvf_maisons", "\n".join(lines)))

    # ── Section 4 : DVF Terrains ──────────────────────────────────────────────
    terr = dvf_stats.get("terrains")
    if terr:
        lines = [
            f"MARCHÉ TERRAINS — {nom_commune}",
            f"Nombre de ventes terrain : {terr['count']}",
            f"Prix au m² moyen terrain : {terr['moyen']:,} €/m²".replace(",", " "),
        ]
        sections.append(("dvf_terrains", "\n".join(lines)))

    # ── Section 5 : Saisonnalité ──────────────────────────────────────────────
    mois_stats = dvf_stats.get("mois_stats", {})
    if len(mois_stats) >= 6:
        mois_sorted = sorted(mois_stats.items(), key=lambda x: x[1])
        mois_bas = mois_sorted[0]
        mois_haut = mois_sorted[-1]
        lines = [
            f"SAISONNALITÉ MARCHÉ — {nom_commune}",
            f"Mois le moins cher pour acheter : {MOIS_NOMS[mois_bas[0]-1]} ({mois_bas[1]:,} €/m²)".replace(",", " "),
            f"Mois le plus cher : {MOIS_NOMS[mois_haut[0]-1]} ({mois_haut[1]:,} €/m²)".replace(",", " "),
            "Prix moyens par mois : " + " | ".join(
                f"{MOIS_NOMS[m-1]}: {p:,}".replace(",", " ") for m, p in sorted(mois_stats.items())
            ),
        ]
        sections.append(("saisonnalite", "\n".join(lines)))

    # ── Section 6 : Score opportunité ────────────────────────────────────────
    score_lines = [f"SCORE OPPORTUNITÉ INVESTISSEMENT — {nom_commune}"]
    prix_ref = appt["moyen"] if appt else (mais["moyen"] if mais else None)

    score_global = None
    if prix_ref and tendance_demo:
        s_demo  = 100 if tendance_demo == "croissance" else (50 if tendance_demo == "stable" else 10)
        s_prix  = min(100, max(0, 100 - (prix_ref - 1000) / 60))
        tp      = dvf_stats.get("tendance_pct") or 0
        s_trend = min(100, max(0, 50 + tp * 2))
        score_global = round(s_demo * 0.4 + s_prix * 0.35 + s_trend * 0.25)
        score_lines.append(f"Score global : {score_global}/100")
        score_lines.append(f"  Démographie ({s_demo:.0f}/100) : {tendance_demo}")
        score_lines.append(f"  Accessibilité prix ({s_prix:.0f}/100) : {prix_ref:,} €/m² moyen".replace(",", " "))
        score_lines.append(f"  Tendance prix ({s_trend:.0f}/100) : {'+' if tp >= 0 else ''}{tp}%")

        # Conseil narratif
        if tendance_demo == "croissance" and prix_ref < 3000:
            conseil = "Opportunité : commune en croissance démographique avec prix encore accessibles. Fort potentiel de valorisation."
        elif tendance_demo == "croissance" and prix_ref >= 3000:
            conseil = "Marché porteur mais prix élevés. Demande soutenue, risque de stagnation à court terme."
        elif tendance_demo == "stable":
            conseil = "Marché stable. Faible risque, rendement locatif prévisible. Idéal pour investissement sécurisé."
        else:
            conseil = "Population en déclin. Risque de dépréciation à moyen terme. Rendement locatif à analyser finement."
        score_lines.append(f"Conseil : {conseil}")

    sections.append(("score", "\n".join(score_lines)))

    # ── Section 7 : SITADEL (permis) ─────────────────────────────────────────
    permis_liste = sitadel_data.get(code_insee, [])
    if permis_liste:
        par_type  = {}
        par_annee = {}
        nb_logts  = 0
        for p in permis_liste:
            t = p.get("type_dossier", "PC")
            par_type[t] = par_type.get(t, 0) + 1
            a = str(p.get("annee", ""))[:4]
            if a.isdigit():
                par_annee[a] = par_annee.get(a, 0) + 1
            nb_logts += int(p.get("nb_logements", 0) or 0)

        lines = [
            f"PERMIS DE CONSTRUIRE (SITADEL) — {nom_commune}",
            f"Total dossiers : {len(permis_liste)}",
        ]
        if nb_logts:
            lines.append(f"Logements créés : {nb_logts:,}".replace(",", " "))
        types_str = " | ".join(f"{t}: {n}" for t, n in sorted(par_type.items()))
        lines.append(f"Types : {types_str}")
        annee_str = " | ".join(f"{a}: {n}" for a, n in sorted(par_annee.items()) if a >= "2018")
        if annee_str:
            lines.append(f"Par année (depuis 2018) : {annee_str}")
        sections.append(("sitadel", "\n".join(lines)))

    # ── Section 8 : Transactions récentes ────────────────────────────────────
    recentes = dvf_stats.get("transactions_recentes", [])
    if recentes:
        lines = [f"TRANSACTIONS RÉCENTES — {nom_commune}"]
        for t in recentes[:8]:
            surf_str = f"{t['surface']}m²" if t["surface"] else "?"
            lines.append(
                f"  {t['date']} | {t['type'] or '?'} | {surf_str} | {t['valeur']:,}€".replace(",", " ")
            )
        sections.append(("transactions_recentes", "\n".join(lines)))

    # ── Assemblage parent doc ─────────────────────────────────────────────────
    parent_text = "\n\n".join(text for _, text in sections)
    if len(parent_text) > MAX_PARENT_CHARS:
        parent_text = parent_text[:MAX_PARENT_CHARS] + "\n[tronqué]"

    # ── Child chunks (un par section thématique) ──────────────────────────────
    # Chaque child est enrichi avec nom commune + code pour ancrage sémantique
    child_chunks = []
    for theme, text in sections:
        # Enrichissement identité dans chaque chunk (comme SanteVeille enrichit classification)
        enriched = f"Commune : {nom_commune} | Code INSEE : {code_insee} | Département : {dept}\n{text}"
        child_chunks.append({
            "theme":   theme,
            "text":    enriched,
            "chars":   len(enriched),
        })

    return parent_text, child_chunks, score_global


# ════════════════════════════════════════════════════════════════════════════
# SECTION 2 — EMBEDDING via sentence-transformers (local, CPU)
# ════════════════════════════════════════════════════════════════════════════

def embed_texts(texts):
    """
    Embedde une liste de textes via sentence-transformers (100% local, CPU).
    Batch natif → ~0.01s/chunk, aucune dépendance réseau.
    """
    model = get_embed_model()
    try:
        vectors = model.encode(texts, batch_size=4, show_progress_bar=False)
        return [v.tolist() for v in vectors]
    except Exception as e:
        log.warning(f"Embedding batch échoué : {e}")
        return [None] * len(texts)


# ════════════════════════════════════════════════════════════════════════════
# SECTION 3 — CHROMADB
# ════════════════════════════════════════════════════════════════════════════

def get_chroma_collection(reset=False):
    """Initialise et retourne la collection ChromaDB."""
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    if reset:
        try:
            client.delete_collection(CHROMA_COLLECTION)
            log.info("Collection ChromaDB réinitialisée.")
        except:
            pass
    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"}
    )
    return collection


def insert_commune_chunks(collection, code_insee, nom_commune, dept,
                           child_chunks, embeddings, score_global, dvf_stats):
    """Insère les child chunks d'une commune dans ChromaDB."""
    docs, metas, ids, embeds = [], [], [], []

    appt = dvf_stats.get("appartements") or {}
    prix_m2 = appt.get("moyen", 0) or 0
    nb_ventes = dvf_stats.get("total_mutations", 0)
    tendance = dvf_stats.get("tendance_pct") or 0

    for i, (chunk, vec) in enumerate(zip(child_chunks, embeddings)):
        if vec is None:
            continue
        chunk_id = f"{code_insee}_{chunk['theme']}_{i}"
        docs.append(chunk["text"])
        metas.append({
            "commune":          nom_commune,
            "code_insee":       code_insee,
            "departement":      dept,
            "thematique":       chunk["theme"],
            "prix_m2_moyen":    prix_m2,
            "score_opportunite": score_global or 0,
            "nb_ventes":        nb_ventes,
            "tendance_pct":     tendance,
            "parent_id":        code_insee,
        })
        ids.append(chunk_id)
        embeds.append(vec)

    if docs:
        collection.upsert(
            documents=docs,
            metadatas=metas,
            ids=ids,
            embeddings=embeds,
        )
    return len(docs)


# ════════════════════════════════════════════════════════════════════════════
# SECTION 4 — CHECKPOINT
# ════════════════════════════════════════════════════════════════════════════

def load_progress():
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"done": [], "errors": [], "started": str(datetime.now())}


def save_progress(progress):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def load_parents_store():
    if PARENTS_STORE.exists():
        with open(PARENTS_STORE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_parents_store(store):
    with open(PARENTS_STORE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, separators=(",", ":"))


# ════════════════════════════════════════════════════════════════════════════
# SECTION 5 — PRIORISATION COMMUNES
# ════════════════════════════════════════════════════════════════════════════

def get_priority_communes(dept_filtre=None, limit=None):
    """
    Retourne la liste des communes à indexer, triées par volume de données.
    Priorité : communes avec le plus de mutations DVF.
    """
    if not DVF_INDEX_DIR.exists():
        log.error(f"Répertoire DVF index introuvable : {DVF_INDEX_DIR}")
        return []

    communes = []
    for json_file in DVF_INDEX_DIR.glob("*.json"):
        code = json_file.stem
        if dept_filtre and not code.startswith(dept_filtre):
            continue
        taille = json_file.stat().st_size
        communes.append((code, taille))

    # Trier par taille décroissante (proxy du volume de données)
    communes.sort(key=lambda x: x[1], reverse=True)

    # Filtrer communes trop petites (estimation : 1 mutation ≈ 200 bytes)
    communes = [(c, t) for c, t in communes if t > MIN_VENTES * 150]

    if limit:
        communes = communes[:limit]

    log.info(f"Communes prioritaires : {len(communes)} (filtre dept={dept_filtre or 'tous'}, min={MIN_VENTES} ventes)")
    return [c for c, _ in communes]


# ════════════════════════════════════════════════════════════════════════════
# SECTION 6 — BUILD PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

def load_insee_pop():
    if INSEE_POP_PATH.exists():
        with open(INSEE_POP_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    log.warning("insee_pop.json absent — démographie désactivée. Lancez build_insee_pop_index.py")
    return {}


def load_sitadel():
    if SITADEL_PATH.exists():
        with open(SITADEL_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    log.warning("sitadel_index.json absent — permis désactivés. Lancez build_sitadel_index.py")
    return {}


def get_nom_commune(code_insee, mutations):
    """Extrait le nom de commune depuis les mutations DVF."""
    for m in mutations:
        nom = m.get("nom_commune", "")
        if nom:
            return nom.title()
    # Fallback arrondissement
    return ARRONDISSEMENT_NOMS.get(code_insee, code_insee)


def build_commune(code_insee, collection, parents_store, insee_pop, sitadel_data):
    """
    Pipeline complet pour une commune :
    1. Charger mutations DVF
    2. Calculer stats
    3. Synthétiser en texte
    4. Embedder chunks
    5. Insérer ChromaDB
    6. Sauvegarder parent
    """
    dvf_path = DVF_INDEX_DIR / f"{code_insee}.json"
    if not dvf_path.exists():
        return False, "fichier DVF absent"

    try:
        with open(dvf_path, "r", encoding="utf-8") as f:
            mutations = json.load(f)
    except Exception as e:
        return False, f"lecture DVF : {e}"

    if len(mutations) < MIN_VENTES:
        return False, f"trop peu de mutations ({len(mutations)})"

    nom_commune = get_nom_commune(code_insee, mutations)
    dept = code_insee[:2]

    # Calcul stats
    dvf_stats = compute_dvf_stats(mutations)

    # Synthèse texte
    parent_text, child_chunks, score_global = synthesize_commune_to_text(
        code_insee, nom_commune, dvf_stats, insee_pop, sitadel_data
    )

    if not child_chunks:
        return False, "aucun chunk généré"

    # Embedding
    texts_to_embed = [c["text"] for c in child_chunks]
    embeddings = embed_texts(texts_to_embed)

    if not any(e is not None for e in embeddings):
        return False, "tous les embeddings ont échoué"

    # Insert ChromaDB
    n_inserted = insert_commune_chunks(
        collection, code_insee, nom_commune, dept,
        child_chunks, embeddings, score_global, dvf_stats
    )

    # Sauvegarder parent
    parents_store[code_insee] = {
        "nom": nom_commune,
        "code_insee": code_insee,
        "departement": dept,
        "score": score_global,
        "text": parent_text,
        "nb_chunks": n_inserted,
        "indexed_at": str(datetime.now()),
    }

    return True, f"{nom_commune} | {n_inserted} chunks | score={score_global}"


def main():
    parser = argparse.ArgumentParser(description="Build RAG index API Immo")
    parser.add_argument("--dept",  type=str, default=None, help="Filtrer par département (ex: 13)")
    parser.add_argument("--limit", type=int, default=None, help="Nombre max de communes")
    parser.add_argument("--reset", action="store_true",    help="Réinitialiser ChromaDB")
    parser.add_argument("--skip-done", action="store_true", default=True,
                        help="Sauter les communes déjà indexées (défaut: True)")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("BUILD RAG INDEX — API IMMO")
    log.info(f"Démarré : {datetime.now()}")
    log.info(f"Config  : dept={args.dept}, limit={args.limit}, reset={args.reset}")
    log.info("=" * 60)

    # Vérifier sentence-transformers + pré-charger le modèle
    try:
        get_embed_model()
    except Exception as e:
        log.error(f"Impossible de charger le modèle embedding : {e}")
        log.error("Installez : pip install sentence-transformers")
        return

    # Init
    collection    = get_chroma_collection(reset=args.reset)
    progress      = load_progress() if not args.reset else {"done": [], "errors": [], "started": str(datetime.now())}
    parents_store = load_parents_store() if not args.reset else {}
    insee_pop     = load_insee_pop()
    sitadel_data  = load_sitadel()

    already_done = set(progress.get("done", []))
    log.info(f"Déjà indexées : {len(already_done)} communes")

    # Liste des communes à traiter
    communes = get_priority_communes(dept_filtre=args.dept, limit=args.limit)
    if args.skip_done:
        communes = [c for c in communes if c not in already_done]
    log.info(f"À indexer : {len(communes)} communes")

    # Build
    ok_count  = 0
    err_count = 0
    t0        = time.time()

    for i, code_insee in enumerate(communes):
        t_start = time.time()
        try:
            success, msg = build_commune(
                code_insee, collection, parents_store, insee_pop, sitadel_data
            )
            if success:
                progress["done"].append(code_insee)
                ok_count += 1
                elapsed = time.time() - t_start
                log.info(f"[{i+1}/{len(communes)}] ✓ {msg} ({elapsed:.1f}s)")
            else:
                progress["errors"].append({"code": code_insee, "reason": msg})
                err_count += 1
                log.debug(f"[{i+1}/{len(communes)}] ✗ {code_insee} : {msg}")

        except Exception as e:
            progress["errors"].append({"code": code_insee, "reason": str(e)})
            err_count += 1
            log.error(f"[{i+1}/{len(communes)}] ERREUR {code_insee} : {e}")

        # Checkpoint + flush tous les BATCH_EMBED communes
        if (i + 1) % BATCH_EMBED == 0:
            save_progress(progress)
            save_parents_store(parents_store)
            elapsed_total = time.time() - t0
            rate = (i + 1) / elapsed_total * 60
            remaining = (len(communes) - i - 1) / (rate / 60) / 60 if rate > 0 else 0
            log.info(f"  ── Checkpoint {i+1}/{len(communes)} | {rate:.1f} communes/min | ~{remaining:.0f} min restantes")
            time.sleep(PAUSE_BETWEEN_BATCHES)

    # Flush final
    save_progress(progress)
    save_parents_store(parents_store)

    total_time = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info(f"BUILD TERMINÉ en {total_time:.1f} min")
    log.info(f"  ✓ {ok_count} communes indexées")
    log.info(f"  ✗ {err_count} erreurs")
    log.info(f"  ChromaDB : {CHROMA_DIR}")
    log.info(f"  Parents  : {PARENTS_STORE}")
    log.info(f"  Log      : {LOG_FILE}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
