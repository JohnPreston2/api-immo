"""
fix.py - Applique les corrections sur app.py
Lance avec : python fix.py
"""
import re

path = "app.py"
content = open(path, encoding="utf-8").read()
original = content

# ── CORRECTION 1 : _match_sitadel_permis (matching strict) ──────────────────
old1 = '''def _match_sitadel_permis(permis_liste: list, refs_mère: set, refs_filles: set) -> list:
    """
    Cherche les permis SITADEL liés à une opération (parcelle mère ou filles).
    Le champ ref_cadastrale SITADEL peut contenir la section+numéro ou la ref complète.
    """
    resultats = []
    toutes_refs = refs_mère | refs_filles
    for p in permis_liste:
        ref_cad = p.get("ref_cadastrale", "").strip()
        if not ref_cad:
            continue
        # Test si une de nos refs est contenue dans ref_cadastrale ou vice versa
        for ref in toutes_refs:
            if ref and (ref in ref_cad or ref_cad in ref or
                        ref[-6:] == ref_cad[-6:]):
                resultats.append(p)
                break
    return resultats'''

new1 = '''def _match_sitadel_permis(permis_liste: list, refs_mere: set, refs_filles: set) -> list:
    """
    Matching strict SITADEL : le champ ref_cadastrale doit contenir exactement
    une des refs parcellaires (mere ou fille), pas juste partager la section.
    On compare section+numero complet (6 chars) uniquement.
    """
    resultats = []
    refs_norm = set()
    for ref in refs_mere | refs_filles:
        ref = ref.strip()
        if len(ref) == 6:
            refs_norm.add(ref)
        elif len(ref) > 6:
            refs_norm.add(ref[-6:])

    for p in permis_liste:
        ref_cad = p.get("ref_cadastrale", "").strip()
        if not ref_cad:
            continue
        ref_cad_norm = ref_cad[-6:] if len(ref_cad) >= 6 else ref_cad
        if ref_cad_norm in refs_norm:
            resultats.append(p)
    return resultats'''

if old1 in content:
    content = content.replace(old1, new1, 1)
    print("OK correction 1 : _match_sitadel_permis")
else:
    print("SKIP correction 1 : déjà appliquée ou pattern non trouvé")

# ── CORRECTION 2 : ops_sans_dfi (filtres copropriétés + aberrations) ─────────
old2 = '''    ops_sans_dfi = []
    for id_parc, ventes_parc in dvf_idx.items():
        # Garder les clés "brutes" (14 chars) uniquement pour éviter doublons
        if len(id_parc) < 14:
            continue
        achats_bloc  = [v for v in ventes_parc if v["nature"] in ("Vente","Adjudication") and v["valeur"] > 0]
        reventes_bloc = []
        # Simplification : compter les ventes distinctes sur même parcelle
        if len(achats_bloc) >= 2:
            achats_bloc.sort(key=lambda x: x["date"])
            # Si 1ère vente et autres ventes avec intervalle > 0
            premiere = achats_bloc[0]
            suivantes = achats_bloc[1:]
            prix_premier = premiere["valeur"]
            prix_suivants = sum(v["valeur"] for v in suivantes)
            cv = round(prix_suivants - prix_premier)
            if cv > 0 and prix_premier > 0:
                ops_sans_dfi.append({
                    "ref_parcelle":        id_parc,
                    "type":                "revente_sans_division",
                    "nb_transactions":     len(achats_bloc),
                    "achat":               {"date": premiere["date"], "valeur": premiere["valeur"]},
                    "reventes":           [{"date": v["date"], "valeur": v["valeur"]} for v in suivantes[:3]],
                    "creation_valeur_eur": cv,
                    "plus_value_pct":      round(cv / prix_premier * 100, 1),
                })'''

new2 = '''    ops_sans_dfi = []
    for id_parc, ventes_parc in dvf_idx.items():
        if len(id_parc) < 14:
            continue
        achats_bloc = [v for v in ventes_parc
                       if v["nature"] in ("Vente", "Adjudication") and v["valeur"] > 0]
        if len(achats_bloc) < 2:
            continue
        # Filtre coproprietes : > 10 transactions = residence avec lots individuels
        if len(achats_bloc) > 10:
            continue
        achats_bloc.sort(key=lambda x: x["date"])
        # Filtre duree : retournement < 36 mois
        try:
            from datetime import datetime
            d1 = datetime.strptime(achats_bloc[0]["date"][:10], "%Y-%m-%d")
            d2 = datetime.strptime(achats_bloc[-1]["date"][:10], "%Y-%m-%d")
            duree_mois = round((d2 - d1).days / 30)
            if duree_mois > 36:
                continue
        except:
            duree_mois = None
        premiere = achats_bloc[0]
        suivantes = achats_bloc[1:]
        prix_premier  = premiere["valeur"]
        prix_suivants = sum(v["valeur"] for v in suivantes)
        cv = round(prix_suivants - prix_premier)
        # Filtre : plus-value min 10 000 EUR et max 500%
        if cv <= 10_000:
            continue
        pv_pct = round(cv / prix_premier * 100, 1)
        if pv_pct > 500:
            continue
        ops_sans_dfi.append({
            "ref_parcelle":        id_parc,
            "type":                "revente_sans_division",
            "nb_transactions":     len(achats_bloc),
            "duree_portage_mois":  duree_mois,
            "achat":               {"date": premiere["date"], "valeur": premiere["valeur"],
                                    "adresse": premiere["adresse"]},
            "reventes":           [{"date": v["date"], "valeur": v["valeur"],
                                    "type": v["type_local"]} for v in suivantes[:5]],
            "creation_valeur_eur": cv,
            "plus_value_pct":      pv_pct,
        })'''

if old2 in content:
    content = content.replace(old2, new2, 1)
    print("OK correction 2 : ops_sans_dfi")
else:
    print("SKIP correction 2 : déjà appliquée ou pattern non trouvé")

if content != original:
    open(path, "w", encoding="utf-8").write(content)
    print("\napp.py mis à jour avec succès.")
else:
    print("\nAucune modification effectuée.")
