import re

path = "retriever.py"
content = open(path, encoding="utf-8").read()

# Supprimer les constantes Ollama
content = content.replace('OLLAMA_URL    = "http://localhost:11434"\n', "")
content = content.replace('EMBED_MODEL   = "nomic-embed-text"\n', 'EMBED_MODEL   = "all-MiniLM-L6-v2"\n')

# Remplacer embed_query
old = content[content.find("def embed_query"):content.find("\n\n\n# ════", content.find("def embed_query"))]
new = '''def embed_query(query: str):
    """Embedde la query via sentence-transformers (local CPU)."""
    try:
        from sentence_transformers import SentenceTransformer
        global _st_model
        if "_st_model" not in globals() or _st_model is None:
            _st_model = SentenceTransformer("all-MiniLM-L6-v2")
        return _st_model.encode(query).tolist()
    except Exception as e:
        log.error(f"Embedding query echoue : {e}")
        return None'''

content = content.replace(old, new)
open(path, "w", encoding="utf-8").write(content)
print("OK")
