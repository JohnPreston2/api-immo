"""
retriever.py
============
Module 2 — RAG API Immo
Retrieval hybride : direct textuel + sémantique ChromaDB, fusionnés.

Architecture identique SanteVeille :
  - Scoring direct prioritaire sur metadata quand match fort (commune, code INSEE)
  - Sémantique ChromaDB pour les requêtes conceptuelles (opportunité, rentabilité, DPE...)
  - Filtre dur code_insee si commune détectée → jamais de cross-contamination géo
  - Détection multi-communes → multi-fetch parallèle
  - Retourne les parents complets (depuis rag_parents.json) pour contexte qwen

Usage autonome (debug) :
  python retriever.py "prix appartement Marseille 2024"
  python retriever.py "communes 13 sous 2500€ en croissance"
  python retriever.py "comparer Lyon et Bordeaux rentabilité"
"""

import os, re, json, time, math, logging
from pathlib import Path
from typing import Optional

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent
CACHE_DIR     = BASE_DIR / "cache"
CHROMA_DIR    = CACHE_DIR / "rag_chroma"
PARENTS_STORE = CACHE_DIR / "rag_parents.json"
INSEE_POP_PATH = CACHE_DIR / "insee_pop.json"

# ── Config ───────────────────────────────────────────────────────────────────
EMBED_MODEL   = "all-MiniLM-L6-v2"
CHROMA_COLLECTION = "api_immo"

TOP_K_SEMANTIC   = 12   # candidats sémantiques avant reranking
TOP_K_FINAL      = 8    # parents retournés au LLM (budget tokens)
MAX_COMMUNES_QUERY = 4  # cap multi-commune pour éviter overflow contexte

# Poids fusion hybride (ajustables)
WEIGHT_DIRECT   = 0.65
WEIGHT_SEMANTIC = 0.35

_retriever_st_model = None
log = logging.getLogger("rag_retriever")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ════════════════════════════════════════════════════════════════════════════
# SECTION 1 — DÉTECTEUR GÉOGRAPHIQUE
# Extrait communes, départements, arrondissements depuis la query
# ════════════════════════════════════════════════════════════════════════════

# Grandes villes avec arrondissements
VILLES_ARRONDISSEMENTS = {"paris", "marseille", "lyon"}

# Alias courants → nom normalisé
ALIAS_COMMUNES = {
    "idf":        None,   # région, pas une commune
    "île-de-france": None,
    "paca":       None,
    "aix":        "aix-en-provence",
    "roubaix":    "roubaix",
    "st-etienne": "saint-etienne",
    "saint-ét":   "saint-etienne",
    "boulogne":   "boulogne-billancourt",
}

# Pattern département : "dans le 13", "dep 75", "département 06", "83", "2A"
RE_DEPT = re.compile(
    r"\b(?:d[eé]partement\s+|dep(?:t)?\.?\s+|dans\s+le\s+)?(\d{2,3}|2[AB])\b",
    re.IGNORECASE
)

# Pattern arrondissement : "13e", "13ème", "8ème arrondissement", "Paris 8"
RE_ARR = re.compile(
    r"\b(\d{1,2})\s*(?:e(?:r)?|è(?:r)?me?|ème?)\b(?:\s+arrondissement)?",
    re.IGNORECASE
)

# Pattern code INSEE explicite : "code 13055", "INSEE 75056"
RE_INSEE = re.compile(r"\b(?:code\s+)?(?:insee\s+)?(\d{5})\b", re.IGNORECASE)

# Mots-clés thématiques → thematique ChromaDB metadata
THEME_KEYWORDS = {
    "dvf_appartements": [
        "appartement", "appart", "studio", "t2", "t3", "t4", "f2", "f3",
        "prix m2", "prix au m2", "prix/m2", "m²", "transaction", "vente"
    ],
    "dvf_maisons": [
        "maison", "villa", "pavillon", "individuel"
    ],
    "dvf_terrains": [
        "terrain", "foncier", "parcelle", "constructible"
    ],
    "saisonnalite": [
        "saison", "mois", "période", "meilleur moment", "quand acheter"
    ],
    "score": [
        "opportunité", "investissement", "rentabilité", "rendement",
        "potentiel", "score", "conseil", "recommande"
    ],
    "sitadel": [
        "permis", "construire", "construction", "logement neuf", "promoteur"
    ],
    "identite": [
        "population", "habitants", "démographie", "croissance", "déclin"
    ],
}

# Qualificatifs prix pour filtrage numérique
RE_PRIX_MAX = re.compile(r"(?:sous|moins\s+de|max\s+|inférieur\s+à)\s*(\d[\d\s]*)\s*(?:€|eur)?(?:/m2|/m²)?", re.IGNORECASE)
RE_PRIX_MIN = re.compile(r"(?:plus\s+de|au-dessus\s+de|min\s+|supérieur\s+à)\s*(\d[\d\s]*)\s*(?:€|eur)?(?:/m2|/m²)?", re.IGNORECASE)


def _clean_price_str(s):
    return int(re.sub(r"\s+", "", s))


def detect_geography(query: str) -> dict:
    """
    Analyse la query et extrait :
    - communes : liste de noms détectés
    - codes_insee : codes explicites
    - departements : codes département
    - arrondissements : numéros détectés (contexte ville)
    - themes : thématiques détectées
    - prix_max, prix_min : filtres numériques
    - is_multi_commune : True si comparaison multi-villes
    """
    q = query.lower()

    result = {
        "communes":        [],
        "codes_insee":     [],
        "departements":    [],
        "arrondissements": [],
        "themes":          [],
        "prix_max":        None,
        "prix_min":        None,
        "is_multi_commune": False,
        "raw_query":       query,
    }

    # Codes INSEE explicites
    for m in RE_INSEE.finditer(query):
        code = m.group(1)
        if code not in result["codes_insee"]:
            result["codes_insee"].append(code)

    # Départements
    for m in RE_DEPT.finditer(query):
        dept = m.group(1).lstrip("0") or "0"
        # Éviter faux positifs sur années (2024, 2023...)
        if len(dept) <= 3 and not dept.startswith("20"):
            if dept not in result["departements"]:
                result["departements"].append(dept.zfill(2))

    # Arrondissements
    for m in RE_ARR.finditer(query):
        num = int(m.group(1))
        if 1 <= num <= 20:
            result["arrondissements"].append(num)

    # Communes — liste étendue des villes françaises les plus fréquentes
    # (les vraies communes viendront de l'index ChromaDB metadata)
    VILLES_CONNUES = [
        "paris", "marseille", "lyon", "toulouse", "nice", "nantes", "strasbourg",
        "montpellier", "bordeaux", "lille", "rennes", "reims", "saint-etienne",
        "toulon", "grenoble", "dijon", "angers", "nîmes", "villeurbanne",
        "le havre", "clermont-ferrand", "aix-en-provence", "brest", "limoges",
        "tours", "amiens", "perpignan", "metz", "besançon", "orléans",
        "mulhouse", "rouen", "caen", "nancy", "argenteuil", "montreuil",
        "saint-denis", "vitry-sur-seine", "créteil", "avignon", "poitiers",
        "aubervilliers", "tourcoing", "dunkerque", "versailles", "nanterre",
        "pau", "valenciennes", "antibes", "saint-nazaire", "mérignac",
        "colombes", "cannes", "asnières-sur-seine", "courbevoie", "rueil-malmaison",
        "vitesse", "la rochelle", "lorient", "calais", "troyes", "bayonne",
        "drancy", "issy-les-moulineaux", "valence", "levallois-perret",
        "chambéry", "quimper", "boulogne-billancourt", "sarcelles", "noisy-le-grand",
        "ajaccio", "la seyne-sur-mer", "cergy", "évry", "meaux", "aulnay-sous-bois",
    ]

    detected_villes = []
    for ville in VILLES_CONNUES:
        # Word boundary sur le nom de ville (évite substring)
        pattern = r"\b" + re.escape(ville) + r"\b"
        if re.search(pattern, q, re.IGNORECASE):
            detected_villes.append(ville.title())

    # Alias
    for alias, canonical in ALIAS_COMMUNES.items():
        if re.search(r"\b" + re.escape(alias) + r"\b", q, re.IGNORECASE):
            if canonical:
                detected_villes.append(canonical.title())

    # Déduplication ordre-préservante
    seen = set()
    for v in detected_villes:
        if v.lower() not in seen:
            result["communes"].append(v)
            seen.add(v.lower())

    result["is_multi_commune"] = len(result["communes"]) >= 2

    # Thématiques
    for theme, keywords in THEME_KEYWORDS.items():
        if any(re.search(r"\b" + re.escape(kw) + r"\b", q) for kw in keywords):
            result["themes"].append(theme)

    # Filtres prix
    m_max = RE_PRIX_MAX.search(query)
    if m_max:
        try:
            result["prix_max"] = _clean_price_str(m_max.group(1))
        except:
            pass

    m_min = RE_PRIX_MIN.search(query)
    if m_min:
        try:
            result["prix_min"] = _clean_price_str(m_min.group(1))
        except:
            pass

    return result


# ════════════════════════════════════════════════════════════════════════════
# SECTION 2 — SCORING DIRECT SUR METADATA
# Identique à SanteVeille : \b-boundary, champs pondérés, priorité sur sémantique
# ════════════════════════════════════════════════════════════════════════════

DIRECT_FIELD_WEIGHTS = {
    "code_insee":    10.0,   # match exact → score maximal
    "commune":        8.0,   # nom commune
    "departement":    6.0,   # code département
    "thematique":     6.0,   # dvf_appartements, score, sitadel...
    "prix_m2_moyen":  0.0,   # numérique, géré séparément
}


def score_direct(chunk_meta: dict, geo: dict, query: str) -> float:
    """
    Score direct d'un chunk ChromaDB contre la query analysée.
    Retourne un score normalisé [0, 1].
    
    Logique multi-niveau (comme SanteVeille) :
      1. Match code INSEE explicite → score maximal immédiat
      2. Match commune par nom (word boundary)
      3. Match département
      4. Match thématique
      5. Bonus filtre prix compatible
    """
    score = 0.0
    max_possible = 10.0  # pour normalisation

    meta_commune = chunk_meta.get("commune", "").lower()
    meta_code    = chunk_meta.get("code_insee", "")
    meta_dept    = chunk_meta.get("departement", "")
    meta_theme   = chunk_meta.get("thematique", "")
    meta_prix    = chunk_meta.get("prix_m2_moyen", 0) or 0

    # ── Niveau 1 : code INSEE exact ────────────────────────────────────────
    if geo["codes_insee"] and meta_code in geo["codes_insee"]:
        return 1.0   # court-circuit immédiat

    # ── Niveau 2 : commune par nom (word boundary obligatoire) ────────────
    for commune_query in geo["communes"]:
        pattern = r"\b" + re.escape(commune_query.lower()) + r"\b"
        if re.search(pattern, meta_commune, re.IGNORECASE):
            score += DIRECT_FIELD_WEIGHTS["commune"]
            break

    # ── Niveau 3 : département ────────────────────────────────────────────
    for dept in geo["departements"]:
        if meta_dept == dept or meta_dept == dept.lstrip("0"):
            score += DIRECT_FIELD_WEIGHTS["departement"]
            break

    # ── Niveau 4 : thématique ─────────────────────────────────────────────
    for theme in geo["themes"]:
        if meta_theme == theme:
            score += DIRECT_FIELD_WEIGHTS["thematique"]
            break

    # ── Niveau 5 : compatibilité filtre prix ──────────────────────────────
    if geo["prix_max"] and meta_prix > 0:
        if meta_prix <= geo["prix_max"]:
            score += 2.0  # bonus compatible
        else:
            score -= 3.0  # pénalité incompatible

    if geo["prix_min"] and meta_prix > 0:
        if meta_prix >= geo["prix_min"]:
            score += 2.0

    if geo["themes"] and meta_theme and meta_theme not in geo["themes"]:
        score -= 1.5
    return min(1.0, max(0.0, score / max_possible))


# ════════════════════════════════════════════════════════════════════════════
# SECTION 3 — EMBEDDING QUERY
# ════════════════════════════════════════════════════════════════════════════

def embed_query(query: str):
    """Embedde la query via sentence-transformers (local CPU)."""
    try:
        from sentence_transformers import SentenceTransformer
        global _st_model
        if "_st_model" not in globals() or _st_model is None:
            _st_model = SentenceTransformer("all-MiniLM-L6-v2")
        return _st_model.encode(query).tolist()
    except Exception as e:
        log.error(f"Embedding query echoue : {e}")
        return None


# ════════════════════════════════════════════════════════════════════════════
# SECTION 4 — RETRIEVAL CHROMADB
# ════════════════════════════════════════════════════════════════════════════

_chroma_collection = None

def get_collection():
    global _chroma_collection
    if _chroma_collection is None:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _chroma_collection = client.get_collection(CHROMA_COLLECTION)
    return _chroma_collection


def build_chroma_where(geo: dict, commune_override: str = None) -> Optional[dict]:
    """
    Construit le filtre `where` ChromaDB.
    
    Filtre dur sur code_insee si commune connue → jamais de cross-contamination.
    Filtre département si pas de commune spécifique.
    Filtre prix si spécifié.
    """
    conditions = []

    # Filtre commune spécifique (override pour multi-commune)
    if commune_override:
        conditions.append({"commune": {"$eq": commune_override}})

    # Filtre département (si pas de commune précise)
    elif geo["departements"] and not geo["communes"] and not geo["codes_insee"]:
        dept = geo["departements"][0]
        conditions.append({"departement": {"$eq": dept}})

    # Filtre prix max
    if geo["prix_max"]:
        conditions.append({"prix_m2_moyen": {"$lte": geo["prix_max"]}})

    # Filtre prix min
    if geo["prix_min"]:
        conditions.append({"prix_m2_moyen": {"$gte": geo["prix_min"]}})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def semantic_search(query_vec: list, where: Optional[dict], n_results: int) -> list:
    """
    Recherche sémantique ChromaDB.
    Retourne liste de dicts {id, meta, document, distance}.
    """
    collection = get_collection()
    kwargs = {
        "query_embeddings": [query_vec],
        "n_results": min(n_results, collection.count()),
        "include": ["metadatas", "documents", "distances"],
    }
    if where:
        kwargs["where"] = where

    try:
        results = collection.query(**kwargs)
    except Exception as e:
        log.error(f"ChromaDB query error : {e}")
        return []

    out = []
    ids        = results.get("ids", [[]])[0]
    metas      = results.get("metadatas", [[]])[0]
    docs       = results.get("documents", [[]])[0]
    distances  = results.get("distances", [[]])[0]

    for chunk_id, meta, doc, dist in zip(ids, metas, docs, distances):
        # ChromaDB cosine distance [0,2] → similarity [0,1]
        similarity = 1.0 - (dist / 2.0)
        out.append({
            "id":         chunk_id,
            "meta":       meta,
            "document":   doc,
            "similarity": max(0.0, similarity),
        })

    return out


# ════════════════════════════════════════════════════════════════════════════
# SECTION 5 — FUSION HYBRIDE
# ════════════════════════════════════════════════════════════════════════════

def fuse_and_rerank(candidates: list, geo: dict, query: str) -> list:
    """
    Fusionne les scores direct + sémantique pour chaque chunk candidat.
    Déduplique par parent_id et retourne les TOP_K_FINAL meilleurs parents.
    
    Score final = WEIGHT_DIRECT * score_direct + WEIGHT_SEMANTIC * score_semantic
    
    Si score_direct > 0.7 (match fort commune/INSEE) → priorité absolue.
    """
    scored = []
    for c in candidates:
        s_direct   = score_direct(c["meta"], geo, query)
        s_semantic = c["similarity"]

        # Match fort → boost direct (comme SanteVeille : priorité sur nom/référence)
        if s_direct >= 0.7:
            final_score = 0.85 * s_direct + 0.15 * s_semantic
        else:
            final_score = WEIGHT_DIRECT * s_direct + WEIGHT_SEMANTIC * s_semantic

        scored.append({**c, "score_direct": s_direct, "score_final": final_score})

    # Déduplique par parent_id : garder le meilleur chunk par commune
    best_by_parent = {}
    for c in scored:
        pid = c["meta"].get("parent_id") or c["meta"].get("code_insee", c["id"])
        if pid not in best_by_parent or c["score_final"] > best_by_parent[pid]["score_final"]:
            best_by_parent[pid] = c

    # Trier et prendre TOP_K_FINAL
    ranked = sorted(best_by_parent.values(), key=lambda x: x["score_final"], reverse=True)
    return ranked[:TOP_K_FINAL]


# ════════════════════════════════════════════════════════════════════════════
# SECTION 6 — CHARGEMENT PARENTS
# ════════════════════════════════════════════════════════════════════════════

_parents_store = None

def load_parents():
    global _parents_store
    if _parents_store is None:
        if PARENTS_STORE.exists():
            with open(PARENTS_STORE, "r", encoding="utf-8") as f:
                _parents_store = json.load(f)
            log.info(f"Parents store chargé : {len(_parents_store)} communes")
        else:
            log.warning("rag_parents.json absent — textes parents indisponibles")
            _parents_store = {}
    return _parents_store


def get_parent_text(code_insee: str) -> Optional[str]:
    """Retourne le texte parent complet d'une commune."""
    store = load_parents()
    entry = store.get(code_insee)
    return entry.get("text") if entry else None


# ════════════════════════════════════════════════════════════════════════════
# SECTION 7 — RETRIEVER PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

def retrieve(query: str, top_k: int = TOP_K_FINAL) -> dict:
    """
    Point d'entrée principal du retriever.
    
    Retourne :
    {
      "query": str,
      "geo": dict,               # analyse géographique
      "chunks": list[dict],      # chunks retenus avec scores
      "parents": list[dict],     # textes parents pour le LLM
      "context_text": str,       # contexte assemblé prêt pour le prompt
      "total_tokens_est": int,   # estimation tokens (÷4)
    }
    """
    t0 = time.time()

    # ── 1. Analyse géographique ────────────────────────────────────────────
    geo = detect_geography(query)
    log.info(f"Query: '{query}' | communes={geo['communes']} | dept={geo['departements']} | themes={geo['themes']}")

    # ── 2. Embedding query ─────────────────────────────────────────────────
    query_vec = embed_query(query)
    if query_vec is None:
        return {"error": "Ollama embedding indisponible", "query": query}

    # ── 3. Retrieval sémantique ────────────────────────────────────────────
    all_candidates = []

    if geo["is_multi_commune"]:
        # Multi-commune : fetch séparé par ville (cap MAX_COMMUNES_QUERY)
        communes_to_fetch = geo["communes"][:MAX_COMMUNES_QUERY]
        log.info(f"Mode multi-commune : {communes_to_fetch}")
        VILLE_TO_DEPT = {"Lyon": "69", "Paris": "75", "Marseille": "13"}
        for commune in communes_to_fetch:
            dept_ville = VILLE_TO_DEPT.get(commune)
            if dept_ville:
                where = {"departement": {"$eq": dept_ville}}
            else:
                where = build_chroma_where(geo, commune_override=commune)
            candidates = semantic_search(query_vec, where, n_results=TOP_K_SEMANTIC // 2)
            all_candidates.extend(candidates)
    else:
        # Mono-commune ou requête générale
        where = build_chroma_where(geo)
        all_candidates = semantic_search(query_vec, where, n_results=TOP_K_SEMANTIC)

    if not all_candidates:
        # Fallback sans filtre géo (requête très générale)
        log.info("Aucun candidat avec filtre — fallback sans filtre géo")
        all_candidates = semantic_search(query_vec, None, n_results=TOP_K_SEMANTIC)

    # ── 4. Fusion hybride + reranking ──────────────────────────────────────
    ranked_chunks = fuse_and_rerank(all_candidates, geo, query)

    # ── 5. Chargement parents ──────────────────────────────────────────────
    parents = []
    seen_codes = set()
    for chunk in ranked_chunks:
        code = chunk["meta"].get("code_insee") or chunk["meta"].get("parent_id", "")
        if code and code not in seen_codes:
            parent_text = get_parent_text(code)
            if parent_text:
                parents.append({
                    "code_insee":   code,
                    "commune":      chunk["meta"].get("commune", ""),
                    "score":        round(chunk["score_final"], 3),
                    "score_direct": round(chunk["score_direct"], 3),
                    "similarity":   round(chunk["similarity"], 3),
                    "thematique":   chunk["meta"].get("thematique", ""),
                    "text":         parent_text,
                })
                seen_codes.add(code)

    # ── 6. Assemblage contexte LLM ────────────────────────────────────────
    context_parts = []
    for i, p in enumerate(parents):
        header = f"[SOURCE {i+1}] {p['commune']} (INSEE: {p['code_insee']}) — score: {p['score']}"
        context_parts.append(f"{header}\n{p['text']}")

    context_text = "\n\n" + ("─" * 60) + "\n\n".join(context_parts)
    tokens_est   = len(context_text) // 4  # approximation 4 chars/token

    elapsed = time.time() - t0
    log.info(
        f"Retrieval terminé en {elapsed:.2f}s | "
        f"{len(all_candidates)} candidats → {len(ranked_chunks)} chunks → {len(parents)} parents | "
        f"~{tokens_est} tokens"
    )

    return {
        "query":           query,
        "geo":             geo,
        "chunks":          [
            {
                "id":         c["id"],
                "commune":    c["meta"].get("commune"),
                "thematique": c["meta"].get("thematique"),
                "score_final":  round(c["score_final"], 3),
                "score_direct": round(c["score_direct"], 3),
                "similarity":   round(c["similarity"], 3),
            }
            for c in ranked_chunks
        ],
        "parents":         parents,
        "context_text":    context_text,
        "total_tokens_est": tokens_est,
        "nb_parents":      len(parents),
        "retrieval_ms":    round(elapsed * 1000),
    }


# ════════════════════════════════════════════════════════════════════════════
# SECTION 8 — RÉSUMÉ RETRIEVAL (pour debug / logs OpenClaw)
# ════════════════════════════════════════════════════════════════════════════

def explain_retrieval(result: dict) -> str:
    """Retourne une explication lisible du retrieval (pour debug)."""
    geo = result.get("geo", {})
    lines = [
        f"QUERY : {result['query']}",
        f"Communes détectées : {geo.get('communes', [])}",
        f"Départements : {geo.get('departements', [])}",
        f"Thématiques : {geo.get('themes', [])}",
        f"Filtre prix : max={geo.get('prix_max')} | min={geo.get('prix_min')}",
        f"Multi-commune : {geo.get('is_multi_commune')}",
        "",
        f"Résultats : {result.get('nb_parents', 0)} parents | ~{result.get('total_tokens_est', 0)} tokens",
        "",
        "Chunks retenus :",
    ]
    for c in result.get("chunks", []):
        lines.append(
            f"  {c['commune']:25s} | {c['thematique']:25s} | "
            f"final={c['score_final']:.2f} (direct={c['score_direct']:.2f}, sem={c['similarity']:.2f})"
        )
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════
# CLI DEBUG
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "prix appartement Marseille"

    print(f"\n{'='*60}")
    print(f"TEST RETRIEVER : {query}")
    print('='*60)

    result = retrieve(query)

    if "error" in result:
        print(f"ERREUR : {result['error']}")
    else:
        print(explain_retrieval(result))
        print(f"\n{'─'*60}")
        print(f"Temps retrieval : {result['retrieval_ms']} ms")
        if result["parents"]:
            print(f"\nExtrait premier parent ({result['parents'][0]['commune']}) :")
            print(result["parents"][0]["text"][:800] + "...")
