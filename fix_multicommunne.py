content = open("retriever.py", encoding="utf-8").read()

# Ajouter alias grandes villes -> noms arrondissements dans le where
old = '        for commune in communes_to_fetch:\n            where = build_chroma_where(geo, commune_override=commune)\n            candidates = semantic_search(query_vec, where, n_results=TOP_K_SEMANTIC // 2)\n            all_candidates.extend(candidates)'
new = '        VILLE_TO_DEPT = {"Lyon": "69", "Paris": "75", "Marseille": "13"}\n        for commune in communes_to_fetch:\n            dept_ville = VILLE_TO_DEPT.get(commune)\n            if dept_ville:\n                where = {"departement": {"$eq": dept_ville}}\n            else:\n                where = build_chroma_where(geo, commune_override=commune)\n            candidates = semantic_search(query_vec, where, n_results=TOP_K_SEMANTIC // 2)\n            all_candidates.extend(candidates)'
content = content.replace(old, new)

open("retriever.py", "w", encoding="utf-8").write(content)
print("OK")
