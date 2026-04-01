"""
rag_chain.py
============
Module 3 — RAG chain + endpoint Flask + worker OpenClaw nocturne

Contient :
  - rag_chain()        : assemble contexte + génère réponse via qwen4b-64k (Ollama)
  - /api/rag           : endpoint Flask (streaming + JSON)
  - openclaw_worker()  : worker autonome pour build nocturne (à lancer avant de dormir)

Ajout dans app.py :
  from rag_chain import register_rag_routes
  register_rag_routes(app)
"""

import os, json, time, logging, threading
from pathlib import Path
from datetime import datetime

log = logging.getLogger("rag_chain")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ── Config ────────────────────────────────────────────────────────────────────
OLLAMA_URL  = "http://localhost:11434"
LLM_MODEL   = "qwen4b-64k"   # modèle custom Ollama (qwen3:4b + 64K ctx + KV Q4)
MAX_TOKENS  = 2048            # réponse max
CTX_BUDGET  = 15_000         # tokens contexte max avant troncature (qwen 4b limite)

BASE_DIR     = Path(__file__).parent
CACHE_DIR    = BASE_DIR / "cache"
PROGRESS_FILE = CACHE_DIR / "rag_progress.json"
WORKER_LOG   = CACHE_DIR / "rag_build.log"


# ════════════════════════════════════════════════════════════════════════════
# SECTION 1 — PROMPT BUILDER
# ════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """Tu es un expert en analyse du marché immobilier français.
Tu réponds en français, avec précision et concision.
Tu bases tes réponses UNIQUEMENT sur les données fournies dans le contexte.
Si une information n'est pas dans le contexte, tu le dis clairement.
Tu cites les communes et les années pour chaque statistique.
Tu utilises les unités : €/m², %, habitants."""


def build_prompt(query: str, context_text: str, tokens_est: int) -> tuple[str, str]:
    """
    Construit le prompt final pour qwen4b-64k.
    Tronque le contexte si dépassement budget tokens.
    Retourne (system_prompt, user_prompt).
    """
    # Troncature contexte si nécessaire
    if tokens_est > CTX_BUDGET:
        # Tronquer à CTX_BUDGET tokens (approx 4 chars/token)
        max_chars = CTX_BUDGET * 4
        context_text = context_text[:max_chars] + "\n\n[Contexte tronqué — budget tokens atteint]"
        log.warning(f"Contexte tronqué : {tokens_est} → {CTX_BUDGET} tokens estimés")

    user_prompt = f"""CONTEXTE DONNÉES IMMOBILIÈRES :
{context_text}

QUESTION : {query}

Réponds en te basant sur les données ci-dessus."""

    return SYSTEM_PROMPT, user_prompt


# ════════════════════════════════════════════════════════════════════════════
# SECTION 2 — LLM CALL (Ollama qwen4b-64k)
# ════════════════════════════════════════════════════════════════════════════

def call_llm(system_prompt: str, user_prompt: str, stream: bool = False):
    """
    Appelle qwen4b-64k via Ollama /api/chat.
    stream=True → générateur de chunks texte
    stream=False → retourne texte complet
    """
    import requests as req

    payload = {
        "model":  LLM_MODEL,
        "stream": stream,
        "options": {
            "num_predict": MAX_TOKENS,
            "temperature": 0.2,
            "top_p": 0.9,
        },
        "think": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
    }

    if stream:
        def _stream_gen():
            with req.post(f"{OLLAMA_URL}/api/chat", json=payload, stream=True, timeout=120) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if line:
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("message", {}).get("content", "")
                            if token:
                                yield token
                            if chunk.get("done"):
                                break
                        except:
                            pass
        return _stream_gen()
    else:
        r = req.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
        r.raise_for_status()
        msg = r.json().get("message", {})
        content = msg.get("content", "").strip()
        # Qwen3 mode thinking : reponse dans "thinking" si content vide
        if not content:
            thinking = msg.get("thinking", "")
            import re as _re
            # Extraire derniere ligne du thinking comme reponse
        # Nettoyer balises think residuelles
        import re as _re2
        content = _re2.sub(r"<think>.*?</think>", "", content, flags=_re2.DOTALL).strip()
        return content


# ════════════════════════════════════════════════════════════════════════════
# SECTION 3 — RAG CHAIN PRINCIPALE
# ════════════════════════════════════════════════════════════════════════════

def rag_chain(query: str, stream: bool = False) -> dict:
    """
    Pipeline RAG complet : query → retrieval → prompt → LLM → réponse.
    
    stream=False → retourne dict avec réponse complète
    stream=True  → retourne dict avec 'stream_gen' générateur
    """
    from retriever import retrieve

    t0 = time.time()

    # ── 1. Retrieval ──────────────────────────────────────────────────────
    retrieval = retrieve(query)

    if "error" in retrieval:
        return {"error": retrieval["error"], "query": query}

    if not retrieval["parents"]:
        return {
            "query":    query,
            "response": "Aucune donnée trouvée pour cette requête. Vérifiez que l'index RAG est bien construit (build_rag_index.py).",
            "parents":  [],
            "geo":      retrieval["geo"],
        }

    # ── 2. Construction prompt ────────────────────────────────────────────
    system_prompt, user_prompt = build_prompt(
        query,
        retrieval["context_text"],
        retrieval["total_tokens_est"]
    )

    # ── 3. LLM ────────────────────────────────────────────────────────────
    try:
        if stream:
            gen = call_llm(system_prompt, user_prompt, stream=True)
            return {
                "query":      query,
                "stream_gen": gen,
                "geo":        retrieval["geo"],
                "chunks":     retrieval["chunks"],
                "parents_meta": [
                    {"commune": p["commune"], "code_insee": p["code_insee"], "score": p["score"]}
                    for p in retrieval["parents"]
                ],
                "retrieval_ms": retrieval["retrieval_ms"],
            }
        else:
            response = call_llm(system_prompt, user_prompt, stream=False)
            # Filtrer le bloc <think>...</think> genere par qwen
            import re as _re
            response = _re.sub(r"<think>.*?</think>", "", response, flags=_re.DOTALL).strip()
            elapsed  = round((time.time() - t0) * 1000)
            return {
                "query":    query,
                "response": response,
                "geo":      retrieval["geo"],
                "chunks":   retrieval["chunks"],
                "parents_meta": [
                    {"commune": p["commune"], "code_insee": p["code_insee"], "score": p["score"]}
                    for p in retrieval["parents"]
                ],
                "retrieval_ms": retrieval["retrieval_ms"],
                "total_ms":     elapsed,
                "tokens_ctx":   retrieval["total_tokens_est"],
            }
    except Exception as e:
        return {"error": f"LLM error : {e}", "query": query}


# ════════════════════════════════════════════════════════════════════════════
# SECTION 4 — ENDPOINT FLASK
# ════════════════════════════════════════════════════════════════════════════

def register_rag_routes(app):
    """
    Enregistre les routes RAG sur l'app Flask existante.
    Appeler depuis app.py : from rag_chain import register_rag_routes
    """
    from flask import request, jsonify, Response

    @app.route("/api/rag")
    def api_rag():
        """
        GET /api/rag?q=prix+appartement+marseille
        GET /api/rag?q=...&stream=1   (Server-Sent Events)
        
        Retourne la réponse RAG avec sources et scores.
        """
        query  = request.args.get("q", "").strip()
        do_stream = request.args.get("stream", "0") == "1"

        if not query:
            return jsonify({"error": "Paramètre 'q' requis. Ex: /api/rag?q=prix+Marseille"}), 400
        if len(query) > 500:
            return jsonify({"error": "Requête trop longue (max 500 chars)"}), 400

        if do_stream:
            def generate():
                result = rag_chain(query, stream=True)
                if "error" in result:
                    yield f"data: {json.dumps({'error': result['error']})}\n\n"
                    return
                # Méta initiale
                meta = {
                    "type":    "meta",
                    "geo":     result["geo"],
                    "sources": result.get("parents_meta", []),
                }
                yield f"data: {json.dumps(meta)}\n\n"
                # Tokens streaming
                for token in result["stream_gen"]:
                    yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"

            return Response(generate(), mimetype="text/event-stream",
                            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        # Mode non-streaming
        result = rag_chain(query, stream=False)
        if "error" in result:
            return jsonify(result), 500
        return jsonify(result)

    @app.route("/api/rag/status")
    def api_rag_status():
        """Statut de l'index RAG."""
        progress_data = {}
        if PROGRESS_FILE.exists():
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                progress_data = json.load(f)

        chroma_count = 0
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(CACHE_DIR / "rag_chroma"))
            col = client.get_collection("api_immo")
            chroma_count = col.count()
        except:
            pass

        parents_count = 0
        parents_path = CACHE_DIR / "rag_parents.json"
        if parents_path.exists():
            with open(parents_path, "r") as f:
                parents_count = len(json.load(f))

        return jsonify({
            "index_ready":      chroma_count > 0,
            "communes_indexees": progress_data.get("done", []),
            "nb_communes":      len(progress_data.get("done", [])),
            "nb_erreurs":       len(progress_data.get("errors", [])),
            "nb_chunks_chroma": chroma_count,
            "nb_parents":       parents_count,
            "started":          progress_data.get("started"),
        })

    log.info("Routes RAG enregistrées : /api/rag, /api/rag/status")


# ════════════════════════════════════════════════════════════════════════════
# SECTION 5 — WORKER OPENCLAW NOCTURNE
# ════════════════════════════════════════════════════════════════════════════

def openclaw_worker(
    dept_filtre: str = None,
    prix_max: int = None,
    limit: int = None,
    batch_size: int = 10,
    pause_sec: float = 2.0,
):
    """
    Worker autonome pour build RAG nocturne.
    Conçu pour tourner pendant que tu dors — robuste, checkpoint, logs détaillés.

    Paramètres :
      dept_filtre : filtrer un département (ex: "13")
      prix_max    : indexer seulement communes sous ce prix/m²
      limit       : cap total communes
      batch_size  : communes par batch avant checkpoint
      pause_sec   : pause entre batches (évite surchauffe GPU/CPU)
    """
    # Import ici pour éviter import circulaire
    from build_rag_index import (
        get_chroma_collection, load_progress, save_progress,
        load_parents_store, save_parents_store, load_insee_pop,
        load_sitadel, get_priority_communes, build_commune
    )

    log.info("=" * 60)
    log.info("OPENCLAW RAG WORKER — DÉMARRAGE")
    log.info(f"Config : dept={dept_filtre}, prix_max={prix_max}, limit={limit}")
    log.info(f"Heure  : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info("=" * 60)

    collection    = get_chroma_collection(reset=False)
    progress      = load_progress()
    parents_store = load_parents_store()
    insee_pop     = load_insee_pop()
    sitadel_data  = load_sitadel()

    already_done = set(progress.get("done", []))

    # Communes à traiter
    communes = get_priority_communes(dept_filtre=dept_filtre, limit=limit)
    communes = [c for c in communes if c not in already_done]
    log.info(f"Communes à indexer : {len(communes)} (déjà faites : {len(already_done)})")

    if not communes:
        log.info("Rien à faire — index déjà à jour.")
        return

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
                elapsed_ms = round((time.time() - t_start) * 1000)
                log.info(f"[{i+1}/{len(communes)}] ✓ {msg} ({elapsed_ms}ms)")
            else:
                progress["errors"].append({"code": code_insee, "reason": msg, "ts": str(datetime.now())})
                err_count += 1
                log.debug(f"[{i+1}/{len(communes)}] ✗ {code_insee} : {msg}")

        except KeyboardInterrupt:
            log.info("Interruption manuelle — sauvegarde checkpoint...")
            save_progress(progress)
            save_parents_store(parents_store)
            log.info(f"Checkpoint sauvegardé. {ok_count} communes traitées.")
            break

        except Exception as e:
            progress["errors"].append({"code": code_insee, "reason": str(e), "ts": str(datetime.now())})
            err_count += 1
            log.error(f"[{i+1}/{len(communes)}] ERREUR {code_insee} : {e}")

        # Checkpoint + ETA toutes les batch_size communes
        if (i + 1) % batch_size == 0:
            save_progress(progress)
            save_parents_store(parents_store)
            elapsed_total = time.time() - t0
            rate = (i + 1) / elapsed_total  # communes/sec
            remaining_communes = len(communes) - i - 1
            eta_min = remaining_communes / rate / 60 if rate > 0 else 0
            eta_heure = datetime.now()
            log.info(
                f"  ── Checkpoint {i+1}/{len(communes)} | "
                f"{rate*60:.1f} communes/min | "
                f"ETA : {eta_min:.0f} min ({eta_heure.strftime('%H:%M')} + {eta_min:.0f}min)"
            )
            time.sleep(pause_sec)

    # Flush final
    save_progress(progress)
    save_parents_store(parents_store)

    total_min = (time.time() - t0) / 60
    log.info("=" * 60)
    log.info(f"WORKER TERMINÉ — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info(f"  ✓ {ok_count} communes indexées")
    log.info(f"  ✗ {err_count} erreurs")
    log.info(f"  Durée totale : {total_min:.1f} min")
    log.info("=" * 60)


# ════════════════════════════════════════════════════════════════════════════
# SECTION 6 — INTÉGRATION app.py (instructions)
# ════════════════════════════════════════════════════════════════════════════

INTEGRATION_INSTRUCTIONS = """
# Ajouter dans app.py (juste avant if __name__ == "__main__":)
# ─────────────────────────────────────────────────────────────
from rag_chain import register_rag_routes
register_rag_routes(app)
# ─────────────────────────────────────────────────────────────
# Endpoints disponibles :
#   GET /api/rag?q=prix+appartement+marseille
#   GET /api/rag?q=...&stream=1    (Server-Sent Events)
#   GET /api/rag/status            (état de l'index)
"""

# ════════════════════════════════════════════════════════════════════════════
# SECTION 7 — SCRIPT DE LANCEMENT NOCTURNE (openclaw_night.py inline)
# Copiez ce bloc dans openclaw_night.py et lancez avant de dormir
# ════════════════════════════════════════════════════════════════════════════

NIGHT_SCRIPT = '''#!/usr/bin/env python3
"""
openclaw_night.py
=================
Lance le build RAG complet pendant la nuit.
Adaptez les paramètres ci-dessous selon vos besoins.

Lancement : python openclaw_night.py
Logs      : cache/rag_build.log  (tail -f pour suivre)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from rag_chain import openclaw_worker

openclaw_worker(
    dept_filtre = None,     # None = toute la France | "13" = Bouches-du-Rhône seul
    prix_max    = None,     # None = tous prix | 5000 = communes < 5000€/m²
    limit       = None,     # None = pas de limite | 1000 = cap 1000 communes
    batch_size  = 10,       # checkpoint toutes les 10 communes
    pause_sec   = 2.0,      # pause entre batches (cooling)
)
'''


if __name__ == "__main__":
    import sys

    # Si lancé directement → afficher instructions + générer openclaw_night.py
    night_script_path = BASE_DIR / "openclaw_night.py"
    if not night_script_path.exists():
        with open(night_script_path, "w", encoding="utf-8") as f:
            f.write(NIGHT_SCRIPT)
        print(f"✓ openclaw_night.py généré dans {BASE_DIR}")

    print(INTEGRATION_INSTRUCTIONS)
    print(f"Pour lancer le build nocturne : python openclaw_night.py")
    print(f"Pour suivre les logs          : tail -f {WORKER_LOG}")
