content = open("retriever.py", encoding="utf-8").read()

# Penalite si thematique demandee mais chunk est mauvais type
old = '    return min(1.0, max(0.0, score / max_possible))'
new = '''    if geo["themes"] and meta_theme and meta_theme not in geo["themes"]:
        score -= 1.5
    return min(1.0, max(0.0, score / max_possible))'''
content = content.replace(old, new)

open("retriever.py", "w", encoding="utf-8").write(content)
print("OK")
