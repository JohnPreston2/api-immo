# API IMMO — Observatoire Foncier

Application Flask de croisement de données immobilières publiques françaises.

## Sources de données

| API | URL | Données |
|-----|-----|---------|
| DVF (Demandes Valeurs Foncières) | `https://api.cquest.org/dvf` | Transactions depuis 2014 |
| DPE ADEME | `https://data.ademe.fr/data-fair/api/v1/datasets/dpe-v2-logements-existants/lines` | Diagnostics énergétiques |
| GPU / IGN | `https://wxs.ign.fr/urbanisme/geoportail/wfs` | PLU, zonages urbanisme |
| API Adresse (geocodage) | `https://api-adresse.data.gouv.fr/search/` | Code INSEE communes |

## Installation

```bash
pip install -r requirements.txt
python app.py
```

App disponible sur http://localhost:5001

## Endpoints API

| Route | Paramètre | Description |
|-------|-----------|-------------|
| `GET /api/dvf` | `?commune=Marseille` | Transactions DVF + stats |
| `GET /api/dpe` | `?commune=Marseille` | DPE ADEME distribution |
| `GET /api/croisement/prime-verte` | `?commune=Marseille` | Prix/m² par classe DPE |
| `GET /api/plu` | `?commune=Marseille` | Zones PLU Géoportail |
| `GET /api/croisement/dvf-plu` | `?commune=Marseille` | DVF + zones brutes |

## Croisements réalisés

### 1. DVF (transactions réelles)
- Prix/m² moyen et médian par type (appart / maison / terrain)
- 20 dernières transactions avec détail
- Statistiques depuis 2014

### 2. DPE ADEME
- Distribution A→G avec pourcentages
- % passoires thermiques (F+G)
- Consommation EP/m² moyenne
- Répartition par type de bâtiment

### 3. Prime verte DVF × DPE ⭐
- Matching statistique par surface arrondie (±5m²)
- Prix/m² moyen par classe énergétique
- Calcul de la "prime verte" : différence A-C vs E-G

### 4. PLU Géoportail Urbanisme
- Zones U, AU, A, N depuis le WFS IGN
- Features GeoJSON brutes pour analyse SIG

## Déploiement VPS

```bash
# Sur ton VPS
git clone ... && cd api_immo
pip install -r requirements.txt
# Avec gunicorn
gunicorn -w 4 -b 0.0.0.0:5001 app:app

# Ou derrière nginx (port 80)
# Configurer proxy_pass vers localhost:5001
```

## Prochaines étapes possibles

- [ ] Croisement exact DVF × DPE par adresse normalisée BAN
- [ ] Jointure spatiale DVF × PLU (PostGIS / GeoPandas)
- [ ] Historique des prix par commune (évolution annuelle)
- [ ] Export CSV/Excel des résultats
- [ ] Intégration carte Leaflet avec heatmap prix
