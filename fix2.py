"""
fix2.py - Ajoute le filtre promoteurs dans app.py
Lance avec : python fix2.py
"""

path = "app.py"
content = open(path, encoding="utf-8").read()
original = content

old = '''        if not ventes_mere and not ventes_filles:
            continue

        # Matching SITADEL'''

new = '''        if not ventes_mere and not ventes_filles:
            continue

        # Filtre promoteurs : > 20 parcelles filles = programme neuf, pas marchand de biens
        if len(enfants) > 20:
            continue

        # Matching SITADEL'''

if old in content:
    content = content.replace(old, new, 1)
    print("OK : filtre promoteurs ajouté")
else:
    print("SKIP : déjà appliqué ou pattern non trouvé")

if content != original:
    open(path, "w", encoding="utf-8").write(content)
    print("app.py mis à jour.")
else:
    print("Aucune modification.")
