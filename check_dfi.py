import json
from pathlib import Path

# Verifier le nouvel index
dfi = json.loads(Path("cache/dfi_index.json").read_text(encoding="utf-8"))
print(f"dfi_index.json : {len(dfi)} cles")
print("Exemples cles :")
for k, v in list(dfi.items())[:5]:
    print(f"  '{k}' -> {v[:2]}")

print()

# Verifier by_commune
by_commune = json.loads(Path("cache/dfi_by_commune.json").read_text(encoding="utf-8"))
print(f"dfi_by_commune.json : {len(by_commune)} communes")

# Tester arrondissements Marseille
for code in ["13201", "13202", "13203", "13204", "13205"]:
    nb = len(by_commune.get(code, {}))
    print(f"  {code} : {nb} parcelles meres")

# Paris arrondissements
for code in ["75101", "75108", "75116"]:
    nb = len(by_commune.get(code, {}))
    print(f"  {code} : {nb} parcelles meres")
