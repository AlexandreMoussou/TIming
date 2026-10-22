# Départ

**Pars au bon moment : l'IA qui te dit quand partir en train ou en avion depuis Paris pour payer moins cher, à partir de dix ans de prix, de trafic et de calendriers.**

Accel AI Innovate Paris, 22 octobre 2026.

## En 30 secondes

| Critère | Preuve |
|---|---|
| Problème et valeur | Tu coches : train ou avion, destination, un mois ou « je suis flexible ». Départ te dit quel mois partir, ce que ça fait gagner, les prix SNCF du trajet, les places TGVmax libres à 30 jours, les vacances et jours fériés à éviter. |
| Agents | Intake (formulaire + mémoire Postgres) → Analyst (tool use) ∥ Calendar → Advisor (Claude). Chaque étape est tracée dans `vg_agent_runs` et visible dans « Voir le raisonnement ». |
| Données | Eurostat (prix HICP train/avion 2016-2025, passagers aériens jusqu'à sept. 2026), SNCF Open Data (régularité TGV par trajet, 36 349 tarifs, 346 810 trains TGVmax à 30 jours), vacances scolaires et jours fériés officiels. ClickHouse, PostgreSQL et Valkey sur Aiven. Chaque chiffre du conseil est vérifié dans les sorties des requêtes. |
| Preuve | Backtest hors échantillon : en avion, quand Départ conseille de décaler, **−9,4 % en moyenne, 89,8 % de cas gagnants** ; en train −2,8 %, 58 %. [`benchmarks/RESULTS.md`](benchmarks/RESULTS.md) |
| Exécution | Interface en une page, 7 tests E2E Playwright sur les vraies bases Aiven. |

## Lancer

```bash
pip install -r requirements.txt
# .env à la racine du dépôt : AIVEN_PG_URI, AIVEN_CH_URI, AIVEN_VALKEY_URI, ANTHROPIC_API_KEY
python -m data.ingest            # données brutes dans data/raw/ (voir les URLs en tête du script)
python -m uvicorn app.main:app --port 8080
npx playwright test
python -m benchmarks.backtest
```

Déploiement : `python voyage/deploy_aiven.py <url du dépôt> <branche>` (service Aiven Runtime `voyage-app`).

## Ce qui est réel, ce qui est supposé

- Réel : toutes les séries ci-dessus, téléchargées depuis les API publiques le 22/10/2026.
- Moyennes : les écarts de prix par mois sont des moyennes historiques nationales, pas le prix d'un vol précis.
- Non couvert : le meilleur moment pour *acheter* (anticipation) n'existe pas en données ouvertes.

Composants : FastAPI, clickhouse-connect, psycopg, redis-py, SDK Anthropic, Playwright. Données sous Licence Ouverte
(Etalab, SNCF) et licence Eurostat (réutilisation autorisée avec mention). Réalisé avec l'aide de Claude Code.
