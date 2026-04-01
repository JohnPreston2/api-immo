content = open("retriever.py", encoding="utf-8").read()

# Fix 1 : cache modele au niveau module (pas dans globals())
old = """_st_model = None
        if "_st_model" not in globals() or _st_model is None:
            _st_model = SentenceTransformer("all-MiniLM-L6-v2")
        return _st_model.encode(query).tolist()"""

new = """if _retriever_st_model is None:
            _retriever_st_model = SentenceTransformer("all-MiniLM-L6-v2")
        return _retriever_st_model.encode(query).tolist()"""

content = content.replace(old, new)

# Ajouter variable globale en haut apres les imports
content = content.replace(
    "log = logging.getLogger",
    "_retriever_st_model = None\nlog = logging.getLogger"
)

# Fix 2 : booster score thematique (4.0 -> 6.0)
content = content.replace(
    '"thematique":     4.0,   # dvf_appartements, score, sitadel...',
    '"thematique":     6.0,   # dvf_appartements, score, sitadel...'
)

open("retriever.py", "w", encoding="utf-8").write(content)
print("OK")
