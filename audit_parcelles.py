import json
from pathlib import Path

# Charger quelques mutations DVF du 13 pour inspecter id_parcelle
dvf_path = Path("cache/dvf/13055.json")
if not dvf_path.exists():
    # Prendre le premier arrondissement Marseille dispo
    dvf_path = Path("cache/dvf/13201.json")

mutations = json.loads(dvf_path.read_text(encoding="utf-8"))

print(f"Fichier : {dvf_path}")
print(f"Total mutations : {len(mutations)}")
print()
print("=== Exemples id_parcelle ===")
seen = set()
for m in mutations:
    pid = m.get("id_parcelle", "")
    if pid and pid not in seen:
        seen.add(pid)
        print(f"  '{pid}' (len={len(pid)})")
    if len(seen) >= 20:
        break

# Charger DFI pour voir format cles
dfi_path = Path("cache/dfi_index.json")
if dfi_path.exists():
    dfi = json.loads(dfi_path.read_text(encoding="utf-8"))
    print(f"\n=== Exemples cles DFI ({len(dfi)} parcelles meres) ===")
    for k, v in list(dfi.items())[:20]:
        print(f"  mere='{k}' -> filles={v[:2]}")
else:
    print("\nDFI index absent")
