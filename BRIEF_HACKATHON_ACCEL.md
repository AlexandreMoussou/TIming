# Brief — Accel AI Innovate Paris (Future Founders Hackathon)

Contexte pour Claude Code. Tout ce qui suit vient des slides projetées sur place le 22 octobre 2026 et des pages officielles (Luma, BuilderBase, Aiven).

---

## 1. L'événement

- **Nom** : Accel AI Innovate 2026 — Paris, "Future Founders" hackathon
- **Date** : jeudi 22 octobre 2026, une seule journée
- **Lieu** : Metafore Boétie – St Augustin, 5 rue La Boétie, 75008 Paris
- **Organisateurs** : Accel (VC) + Iterate, tournant sur la plateforme BuilderBase
- **Partenaires affichés sur la slide d'accueil** : Aiven, Lovable, Hackathon Hub, Iterate
- **4ème étape** d'une série de 5 villes européennes (Stockholm le 16 sept, Amsterdam, etc.)
- **Équipes** : de 1 à 5 personnes, présence physique obligatoire toute la journée, pas de remote
- ~339 inscrits sur Luma, sélection à l'entrée ("technical builders with founder intent")

## 2. Planning de la journée (slide "Future Founders")

| Heure | Étape |
|---|---|
| 08:00 | Registration and breakfast |
| 09:00 | Let's go ! (kickoff + hacking) |
| 12:00 | Lunch |
| **15:00** | **Hackathon submissions** (deadline de soumission) |
| 16:00 | Top 8 pitch |
| 17:00 | Winners announced |
| 18:00 | Departures / Off the Record avec Mati Staniszewski (CEO ElevenLabs) |

→ Fenêtre de build réelle : **09:00 → 15:00, soit 6 heures** (déjeuner inclus). Tout ce qui est livrable doit être prêt et uploadé avant 15h.

## 3. Le challenge (slide "The Challenge", texte quasi intégral)

> Build a working product where one or more agents depend on data to deliver value for a specific user. That could mean querying large datasets, reacting to event streams, keeping long-term memory, combining many sources or improving over time from past runs. You choose the customer and the problem.
>
> Use any models, frameworks and tools you like. Deploy your app to our sponsor Aiven's Runtime, and use their managed data infrastructure for your data layer where relevant (PostgreSQL, ClickHouse, Valkey, OpenSearch and more) with free credits for every team.
>
> Strong teams need more than code. Product thinking, design and a credible route to first users all count.

Points à retenir :
- Le mot-clé est **agent(s) + data**. Un wrapper LLM avec une base décorative ne passe pas.
- Le **déploiement sur Aiven Runtime** est explicitement demandé ("Deploy your app to our sponsor Aiven's Runtime").
- La data layer doit être Aiven "where relevant" : PostgreSQL, ClickHouse, Valkey (fork Redis), OpenSearch, Kafka…
- Liberté totale sur le modèle, le framework, les outils.
- Le produit et la go-to-market comptent, pas que le code.

## 4. Livrables à soumettre (slide des 5 cartes)

| # | Livrable | Format attendu |
|---|---|---|
| 1 | **Project name and one-line pitch** | Hosted URL (app déployée, accessible) |
| 2 | **3 minute demo** | MP4 |
| 3 | **The data layer in action** | TXT (fichier texte expliquant comment la data est utilisée) |
| 4 | **Before and after / comparison benchmarks** | Files (fichiers, ex. CSV/MD/PNG avec les chiffres) |
| 5 | **One pitch slide** | Link (lien vers un seul slide) |

Donc 5 artefacts distincts : une URL live, une vidéo, un .txt, des fichiers de benchmark, un lien de slide. Prévoir du temps pour la vidéo (enregistrement + montage) et pour les benchmarks, pas juste pour le code.

## 5. Critères de jugement (slide des 5 critères, texte intégral)

1. **Customer problem & product value** — Is it a real problem for a clear user, and would they adopt the product?
2. **Agent capability** — Does it show advanced agent behaviour, such as multi-step reasoning, autonomy, teamwork or learning, beyond a single LLM call?
3. **Data at the core** — Does the product depend on using data well (freshness, scale, grounding, memory), or is the data just decoration?
4. **Evidence it works** — Is there a measurable result, such as accuracy, cost, latency, success rate or time saved?
5. **Execution & pitch** — Is it a polished, understandable demo with a clear point of difference and a credible route to first users?

Le jury (d'après les autres étapes de la série) privilégie "substance over showmanship" : chaque soumission est revue, les 8 meilleures pitchent en live.

### Traduction en contraintes techniques

- **Critère 2** → il faut une boucle agentique visible : plusieurs étapes, des appels d'outils, de la planification, idéalement plusieurs agents qui coopèrent ou un agent qui apprend de ses runs précédents. Logger les étapes pour pouvoir les montrer.
- **Critère 3** → l'agent doit lire/écrire dans une vraie base (Postgres/ClickHouse/OpenSearch sur Aiven), avec de la fraîcheur (données qui changent) ou de la mémoire (état persisté entre les runs). Le fichier TXT "data layer in action" doit raconter ça concrètement : quelles tables, quelles requêtes, quels flux.
- **Critère 4** → prévoir dès le début une métrique mesurable et un protocole before/after : par ex. temps humain vs temps agent, précision avec/sans grounding data, latence, coût par tâche, taux de succès sur N cas de test. Écrire un petit script de benchmark qui produit un fichier de résultats.
- **Critère 5** → démo courte, un seul slide, une phrase de différenciation, et une réponse à "qui sont les 10 premiers users et comment on les atteint".

## 6. Aiven Runtime — ce qu'il faut savoir

- Aiven Runtime (ex "Aiven Apps") est en **GA depuis le 23 septembre 2026**, lancé avec Aiven DataHub (catalogue de données pour agents).
- Principe : tu déploies un **conteneur** (Containerfile / Docker Compose) **dans le même projet Aiven** que tes services data. Aiven gère réseau, orchestration, et la connexion aux services Aiven se fait "zero configuration".
- Déploiement possible directement depuis un repo Git.
- Cas d'usage mis en avant par Aiven : agents IA sur données live, filtrage temps réel de streams, détection d'anomalies, dashboards internes.
- Services data disponibles : PostgreSQL, ClickHouse, Valkey, OpenSearch, Kafka, MySQL, etc.
- Aiven a aussi un **serveur MCP** pour interagir avec la plateforme depuis Claude/Cursor.
- Démo de référence qu'ils montrent : un agent support client sur Runtime qui query Postgres pour les commandes et lit Kafka pour les événements de livraison.
- Docs : https://aiven.io/docs/products/runtime — Blog de lancement : https://aiven.io/blog/deploy-your-apps-and-agents-where-your-data-lives-with-aiven-runtime

→ Pour l'archi : app conteneurisée (Python/FastAPI ou Node), variables d'env pour les connexions Aiven, une base Postgres au minimum, plus éventuellement ClickHouse pour de l'analytique ou OpenSearch pour du retrieval.

## 7. Crédits disponibles pour chaque équipe

- 100 $ Anthropic
- 100 $ Modal
- 120 $ Vercel AI Gateway
- 110k crédits ElevenLabs
- 25 $ Supabase (1 mois Pro)
- 500 $ Stripe par équipe
- 1 mois n8n Cloud Pro
- Crédits Lovable et Aiven
- 1 mois Miro Enterprise
- 1 mois Lightdash Cloud Pro par équipe
- 50 $ OpenAI

## 8. Prix

- **Cash** : 1 500 € (1er), 1 000 € (2e), 500 € (3e)
- Mentorat avec l'équipe Accel + backpack AI Innovate par gagnant
- **Anthropic** : 5 000 $ de crédits API par équipe gagnante
- **Aiven** : 12 000 $ de crédits + 2h de solutions architect pour le top 3
- **AWS** : 25 000 $ + session 1:1 avec un leader AWS
- **Stripe** : 10k $ / 5k $ / 2k $ de crédits + session pricing 1:1
- **Supabase** : 5 000 $ pour l'équipe gagnante
- **Modal** : 5 000 $ par équipe
- **Vercel** : 12 000 $ AI Gateway
- **ElevenLabs** : 1,1M crédits par membre gagnant
- **n8n** : 1 an Cloud Pro (600 €) par membre gagnant
- **Miro** : 1 an Enterprise pour l'équipe gagnante
- **Lightdash** : 12 mois Cloud Pro
- **Lovable** : crédits + mentorat
- **OpenAI** : grosse dotation de crédits par équipe
- Un device **Pocket** par gagnant

## 9. Checklist de production pour la journée

- [ ] Choisir un **utilisateur précis** et un **problème concret** (critère 1), le formuler en une ligne
- [ ] Provisionner les services Aiven (Postgres + autre si pertinent), noter les URIs
- [ ] Seed de données réalistes (ou source live) pour que la data soit visiblement au cœur
- [ ] Boucle agent multi-étapes avec outils, logs d'exécution lisibles
- [ ] Mémoire / état persisté entre les runs (table dédiée)
- [ ] Script de benchmark → fichier de résultats before/after
- [ ] Containerfile + déploiement sur Aiven Runtime → URL publique
- [ ] Fichier `data_layer.txt` : tables, requêtes, flux, pourquoi la data est indispensable
- [ ] Vidéo démo 3 min (MP4)
- [ ] Un slide de pitch (lien), avec le point de différence et la route vers les premiers users
- [ ] Soumission sur BuilderBase avant **15:00**

## 10. Liens

- Luma (page officielle) : https://luma.com/0v3c010v
- BuilderBase (soumission) : https://builderbase.com/event/accel-ai-innovate-paris
- Hackathon Hub : https://hackathonhub.eu/events/accel-ai-innovate-paris-paris-2026
- Aiven Runtime : https://aiven.io/runtime
- Aiven Runtime docs : https://aiven.io/docs/products/runtime
