# Plan d'intégration OpenClaw × Api Immo
## Architecture complète — de zéro à un système autonome de veille foncière

---

## 1. Vue d'ensemble de l'architecture cible

```
Telegram / WhatsApp
        │
        ▼
┌─────────────────────────────────────────────────────┐
│              OpenClaw Gateway (:18789)              │
│                                                     │
│  ┌──────────────────┐   ┌────────────────────────┐  │
│  │  Agent "immo"    │   │  Agent "scraper"       │  │
│  │  (orchestrateur) │   │  (browser automation)  │  │
│  │  Qwen 9B local   │   │  Claude Sonnet         │  │
│  │  0€/requête      │   │  ~0.003€/scrape        │  │
│  └────────┬─────────┘   └──────────┬─────────────┘  │
│           │  sessions_spawn         │                │
│           │◄────────────────────────┘                │
│           │                                          │
│  ┌────────▼─────────────────────────────────────┐   │
│  │              Cron Jobs                       │   │
│  │  • 07h00 : rapport quotidien Marseille       │   │
│  │  • 09h00 : scrape leboncoin nouvelles annonces│   │
│  │  • 18h00 : alerte si prix < seuil            │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│              Api Immo Flask (:5001)                 │
│  GET /api/dvf?commune=...                           │
│  GET /api/densification?commune=...                 │
│  GET /api/marchands?commune=...                     │
│  GET /api/score?commune=...                         │
│  GET /api/opportunites?departement=13               │
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│           Chrome (profil "immo-scraper")            │
│  • leboncoin.fr/annonces/vente/                     │
│  • seloger.com                                      │
│  • pap.fr                                           │
└─────────────────────────────────────────────────────┘
```

**Principe clé** : Qwen 9B pour tout ce qui est analyse/raisonnement (0€), Claude Sonnet uniquement pour le browser control (anti-bot robustesse).

---

## 2. Installation étape par étape

### 2.1 Installer OpenClaw

```bash
# Windows (PowerShell admin)
npm install -g openclaw

# Onboarding wizard
openclaw onboard
# → Choisir "Local providers" (Ollama)
# → Choisir "Telegram" comme canal (ou WhatsApp)
# → Entrer le bot token Telegram
```

### 2.2 Configurer Ollama comme provider principal

Fichier `~/.openclaw/openclaw.json` :

```json5
{
  models: {
    providers: {
      ollama: {
        baseUrl: "http://127.0.0.1:11434",
        apiKey: "ollama-local",
        api: "ollama"   // NATIF, pas /v1 — tool calling fiable
      },
      // Claude uniquement pour le browser (scraping anti-bot)
      anthropic: {
        apiKey: "sk-ant-..."
      }
    }
  },
  agents: {
    defaults: {
      model: {
        primary: "ollama/qwen-fast",  // ton modèle custom
        fallbacks: ["anthropic/claude-sonnet-4-6"]
      },
      subagents: {
        model: "ollama/qwen-fast",   // sous-agents en local
        maxConcurrent: 3,
        maxSpawnDepth: 2
      }
    }
  },
  browser: {
    enabled: true,
    defaultProfile: "openclaw",
    headless: false,
    executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    profiles: {
      openclaw: { cdpPort: 18800 },
      "immo-scraper": { cdpPort: 18801 }
    }
  }
}
```

**Point critique** : utiliser `api: "ollama"` (URL native, pas `/v1`) pour que le tool calling fonctionne avec Qwen. Le mode `/v1` casse le tool calling — bug documenté dans la communauté (#21).

### 2.3 Structure des agents

```bash
# Créer les deux agents
openclaw agents add immo       # orchestrateur principal
openclaw agents add scraper    # browser automation
```

---

## 3. Workspace de l'agent "immo"

### `~/.openclaw/agents/immo/workspace/IDENTITY.md`

```markdown
Tu es un analyste immobilier expert sur le marché français.
Tu as accès à Api Immo (Flask :5001) qui expose DVF, DPE, PLU, 
densification et marchands de biens.

Quand on te demande une analyse, tu appelles TOUJOURS les endpoints
Flask en premier, puis tu raisonnes sur les données.

Tu réponds en français, de manière concise et structurée.
Tu identifies les opportunités d'investissement et les alertes de marché.
```

### `~/.openclaw/agents/immo/workspace/TOOLS.md`

```markdown
Tu peux utiliser :
- exec : pour appeler curl vers l'API Flask locale
- web fetch : pour vérifier des données complémentaires
- sessions_spawn : pour déléguer le scraping à l'agent "scraper"
```

### `~/.openclaw/agents/immo/workspace/HEARTBEAT.md`

```markdown
Toutes les 4 heures pendant les heures actives (7h-22h) :
1. Appelle GET http://localhost:5001/api/opportunites?departement=13&prix_max=3000&limit=5
2. Si de nouvelles opportunités apparaissent (score > 75), notifie l'utilisateur
3. Sinon, silence total
```

### `~/.openclaw/agents/immo/workspace/SOUL.md`

```markdown
# Mémoire des alertes actives
Surveille :
- Marseille 13e, 14e, 15e : marchands de biens actifs
- Communes > score 80 dans le 13 : nouveau potentiel
- Prix sous 1500€/m² avec transactions croissantes

# Historique des analyses
[mis à jour automatiquement par l'agent]
```

---

## 4. Workspace de l'agent "scraper"

### `~/.openclaw/agents/scraper/workspace/IDENTITY.md`

```markdown
Tu es un agent spécialisé dans la navigation web pour collecter
des annonces immobilières françaises.

Quand on te donne une tâche de scraping :
1. Tu ouvres le browser avec le profil "immo-scraper"
2. Tu navigues vers le site cible
3. Tu extrais les annonces (titre, prix, surface, localisation, date)
4. Tu retournes un JSON structuré

Tu opères toujours avec le profil browser "immo-scraper" (isolé).
```

Configurer l'agent scraper pour utiliser Claude Sonnet (browser robustesse) :

```json5
// Dans openclaw.json, section agents.list
{
  agents: {
    list: [
      {
        id: "scraper",
        model: {
          primary: "anthropic/claude-sonnet-4-6"
        }
      }
    ]
  }
}
```

---

## 5. Cron Jobs

### 5.1 Rapport quotidien 7h

```bash
openclaw cron add \
  --name "rapport-marseille" \
  --cron "0 7 * * *" \
  --tz "Europe/Paris" \
  --session immo \
  --message "Génère le rapport quotidien : appelle /api/opportunites?departement=13, /api/score?commune=Marseille, /api/marchands?commune=Marseille. Résume en 5 bullet points les points clés du marché marseillais. Envoie-moi uniquement s'il y a une alerte ou une opportunité score > 75." \
  --announce
```

### 5.2 Scraping leboncoin 9h

```bash
openclaw cron add \
  --name "scrape-leboncoin" \
  --cron "0 9 * * *" \
  --tz "Europe/Paris" \
  --session immo \
  --message "Délègue à l'agent scraper : scrape leboncoin.fr/c/ventes_immobilieres pour Marseille, filtre appartements < 150000€, surface > 40m². Retourne les 10 dernières annonces. Compare avec les prix DVF via /api/dvf?commune=Marseille. Alerte si une annonce est > 15% sous le prix médian." \
  --announce
```

### 5.3 Alerte prix bas 18h

```bash
openclaw cron add \
  --name "alerte-prix" \
  --cron "0 18 * * 1-5" \
  --tz "Europe/Paris" \
  --session immo \
  --message "Vérifie /api/opportunites?departement=13&prix_max=2000&limit=10. Si score_opportunite > 80 pour une commune non encore notifiée cette semaine, envoie une alerte détaillée." \
  --announce
```

---

## 6. Skill personnalisée "api-immo"

Créer `~/.openclaw/agents/immo/workspace/skills/api-immo.md` :

```markdown
# Skill : Api Immo

## Endpoints disponibles (Flask :5001)

### Analyses de marché
- GET /api/dvf?commune={nom}
  → prix/m² moyen, médian, transactions récentes

- GET /api/score?commune={nom}
  → score_global 0-100, volume, tendance, accessibilité, dynamisme

- GET /api/opportunites?departement={dep}&prix_max={prix}&limit={n}
  → classement communes par score d'opportunité

- GET /api/demographie?commune={nom}
  → historique population, variation %, conseil investissement

### Outils fonciers
- GET /api/densification?commune={nom}&section={AB}
  → parcelles avec surface libre, potentiel fort/moyen/faible

- GET /api/marchands?commune={nom}
  → opérations détectées : achat parcelle → division → revente

### Données complémentaires
- GET /api/dpe?commune={nom}
  → distribution DPE, passoires thermiques %

- GET /api/dvf/arrondissements?commune=Marseille&type=Appartement
  → prix/m² par arrondissement

## Pattern d'appel (exec)

```bash
curl -s "http://localhost:5001/api/dvf?commune=Marseille" | python -m json.tool
```

## Interprétation des scores

| Score | Interprétation |
|-------|---------------|
| > 80  | 🟢 Forte opportunité — agir rapidement |
| 60-80 | 🟡 Opportunité modérée — surveiller |
| < 60  | 🔴 Marché mature ou en déclin |

## Marchands de biens : signaux d'alerte

Un résultat /api/marchands avec :
- nb_operations_detectees > 5 → zone active de promoteurs
- plus_value_pct > 40 → marges élevées, concurrence forte
- nb_permis > 10 → secteur en mutation rapide
```

---

## 7. Scraping leboncoin — script Lobster

Le moteur Lobster (workflow déterministe d'OpenClaw) est plus fiable que laisser le LLM décider de la séquence. Créer `~/.openclaw/agents/scraper/workspace/skills/scrape-leboncoin.lobster` :

```yaml
name: scrape-leboncoin-marseille
steps:
  - id: navigate
    command: browser navigate https://www.leboncoin.fr/c/ventes_immobilieres
    
  - id: filter-location
    command: browser snapshot --interactive
    # L'agent lit le snapshot et remplit les filtres
    
  - id: set-marseille
    command: browser wait "#location-input" --timeout-ms 5000
    
  - id: extract
    command: browser snapshot --format ai
    
  - id: parse
    command: llm-task
    input: $extract.stdout
    prompt: |
      Extrais toutes les annonces visibles.
      Retourne un JSON array avec : titre, prix, surface_m2, 
      localisation, date_publication, url.
      Filtre : prix < 200000, surface > 35.
    schema:
      type: array
      items:
        type: object
        properties:
          titre: {type: string}
          prix: {type: number}
          surface_m2: {type: number}
          localisation: {type: string}
          date_publication: {type: string}
          url: {type: string}
```

---

## 8. Problèmes connus et solutions

### Problème 1 : Qwen + tool calling

Qwen 9B avec OpenClaw peut avoir des soucis si `reasoning` est activé (envoie le prompt comme `developer` au lieu de `system`, non supporté par Ollama).

**Fix** dans `openclaw.json` :
```json5
{
  models: {
    providers: {
      ollama: {
        models: [{
          id: "qwen-fast",
          compat: {
            supportsDeveloperRole: false  // Fix critique
          }
        }]
      }
    }
  }
}
```

### Problème 2 : DataDome sur leboncoin

Leboncoin utilise DataDome. Avec le profil browser `immo-scraper` isolé (pas ton Chrome perso), les sessions sont propres mais DataDome peut quand même bloquer.

**Stratégie** :
1. Se logger manuellement une fois via `browser-login` pour stocker les cookies
2. Utiliser `browser set geo 43.2965 5.3698` (Marseille) pour paraître local
3. Espacer les requêtes (le Lobster peut inclure des `wait`)
4. Fallback : pap.fr et bienici.com ont une protection bien plus légère

### Problème 3 : Qwen 9B context window (2048)

Le système prompt d'OpenClaw est lourd (IDENTITY + SOUL + TOOLS + AGENTS). Avec ctx=2048, Qwen déborde.

**Fix** : Augmenter légèrement le context dans le Modelfile :
```
FROM qwen3.5:9b
PARAMETER num_gpu 33
PARAMETER num_ctx 4096    # 4096 au lieu de 2048
PARAMETER num_thread 2
```
Tester que ça tient en VRAM (RTX 2070 8GB) — probablement OK.

---

## 9. Flux complet : du message Telegram à la réponse

```
[Toi sur Telegram] : "analyse opportunités Bouches-du-Rhône prix max 2000€"
            │
            ▼
[OpenClaw Gateway] reçoit le message
            │
            ▼
[Agent "immo" — Qwen 9B local] 
  → lit IDENTITY.md + SOUL.md + skill api-immo.md
  → décide d'appeler exec :
    curl http://localhost:5001/api/opportunites?departement=13&prix_max=2000&limit=20
  → reçoit JSON (communes triées par score)
  → raisonne sur les données
  → formate réponse : top 5 communes avec score, prix, tendance
            │
            ▼
[Telegram] : réponse structurée avec emojis et données concrètes
```

Coût de cette opération : **0€** (Qwen local + Flask local)

---

## 10. Flux scraping : quand l'agent décide de scraper

```
[Agent "immo" — Qwen] : detecte que les données DVF ont 6 mois
  → appelle sessions_spawn vers agent "scraper"
  → message : "scrape leboncoin Marseille apparts < 150k€"
            │
            ▼
[Agent "scraper" — Claude Sonnet]
  → browser navigate leboncoin
  → browser snapshot → voit les annonces
  → browser act : filtre Marseille + prix max
  → browser snapshot → extrait résultats
  → retourne JSON structuré à l'agent "immo"
            │
            ▼
[Agent "immo" — Qwen reprend]
  → compare prix scraping vs DVF médian
  → calcule écart : annonce X est 18% sous le marché
  → alerte Telegram : "🚨 OPPORTUNITÉ : 3 pièces Marseille 13e, 125k€, médian DVF = 148k€"
```

Coût de cette opération : **~0.005€** (Claude Sonnet pour le browser, ~2000 tokens)

---

## 11. Roadmap de déploiement (ordre recommandé)

### Semaine 1 — Fondations
- [ ] `npm install -g openclaw`
- [ ] `openclaw onboard` → Telegram + Ollama
- [ ] Tester `qwen-fast` dans OpenClaw (fix `supportsDeveloperRole: false`)
- [ ] Créer agent "immo" + IDENTITY + skill api-immo
- [ ] Valider : message Telegram → appel Flask → réponse

### Semaine 2 — Automation
- [ ] Configurer les 3 cron jobs
- [ ] Tester HEARTBEAT (alerte si score > 75)
- [ ] Peaufiner SOUL.md (mémoire des communes surveillées)

### Semaine 3 — Scraping
- [ ] Créer agent "scraper" + Claude Sonnet
- [ ] Browser login sur leboncoin (cookies manuels)
- [ ] Tester scraping PAP.fr (plus simple pour commencer)
- [ ] Intégrer comparaison scraping × DVF

### Semaine 4 — Production
- [ ] Lobster workflow scraping déterministe
- [ ] Alertes prix sous médian DVF
- [ ] Rapport PDF hebdomadaire (agent immo appelle le script Python existant)

---

## 12. Commandes de référence rapide

```bash
# Status général
openclaw gateway status
openclaw models status

# Logs agents
openclaw agents logs immo --follow
openclaw agents logs scraper --follow

# Crons
openclaw cron list
openclaw cron run rapport-marseille  # force run immédiat

# Browser debug
openclaw browser --browser-profile immo-scraper status
openclaw browser --browser-profile immo-scraper open https://leboncoin.fr
openclaw browser --browser-profile immo-scraper snapshot --interactive

# Tester Qwen tool calling
openclaw agent --session test --message "appelle curl http://localhost:5001/api/dvf?commune=Marseille et résume"

# Switch model pour une session
/model ollama/qwen-fast
```
