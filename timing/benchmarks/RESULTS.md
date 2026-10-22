# Backtest de Timing — hors échantillon, données réelles DVF Paris

`python -m benchmarks.backtest` · détail par cas : `results.csv` · synthèse : `results.json`

**Protocole (leave-one-year-out)** : pour chaque année test 2021-2025, chacun des 20 arrondissements et chaque
typologie (studio/T1, T2, T3+), les indices saisonniers sont recalculés **sans l'année testée**, le mois est choisi
avec la règle de l'app (événements de l'année inclus), puis comparé à ce qui s'est réellement passé cette année-là.
299 cas par intention. Emménagement visé : septembre.

## Location (métrique : volume de logements qui changent de main dans le mois, proxy de l'offre)

| Comparaison | Gain moyen | Cas gagnants |
|---|---:|---:|
| Mois recommandé vs un mois au hasard dans la fenêtre réaliste (juin-août) | **+25,3 %** | **92,3 %** |
| Mois recommandé vs chercher en septembre (le mois de l'emménagement) | +6,7 % (médiane +1,4 %) | 50,5 % |

Lecture : Timing choisit presque toujours le meilleur mois dans la fenêtre où l'on peut réellement chercher. Face à
septembre, le volume est comparable : c'est voulu, la règle évite septembre parce que c'est le pic de concurrence
étudiante (rush de la rentrée), ce que le volume seul ne mesure pas.

## Achat (métrique : prix médian au m² du mois de signature)

| Comparaison | Économie moyenne | Cas gagnants |
|---|---:|---:|
| Mois recommandé vs signer en septembre | +0,8 % | 47,2 % |
| Mois recommandé vs un mois au hasard (mars-septembre) | +0,6 % | 54,2 % |

Lecture honnête : **le mois de signature ne fait pas baisser le prix de vente de façon fiable à Paris** (effet
inférieur à 1 %, proche du hasard). Pour un acheteur, la valeur de Timing tient au choix du quartier et au volume
d'offre, pas à une remise saisonnière. Nous ne revendiquons donc aucune économie de prix liée au mois.

## Limites
- DVF enregistre des ventes signées, pas des annonces de location : le volume est un proxy de la rotation des
  logements, pas un compte d'annonces.
- 5 années complètes (2021-2025), dont 2024 perturbée par les JO et les législatives anticipées.
- La pénalité de concurrence (−12 pts par événement, −15 pts par période creuse) est une hypothèse de réglage.

# Claude seul vs Timing (20 questions, même modèle claude-sonnet-5-5)

`python -m benchmarks.agent_vs_llm` · détail et réponses : `agent_vs_llm.csv` · synthèse : `agent_vs_llm.json`

Chaque chiffre cité dans la réponse est recherché dans les sorties réelles des outils Timing (ClickHouse, Postgres)
pour les mêmes paramètres.

| | Claude seul | Timing (agents + données Aiven) |
|---|---:|---:|
| Réponses dont **tous** les chiffres sont retrouvés dans les données | **0 / 20** | **17 / 20** |
| Chiffres cités retrouvés dans les données | 223 / 314 (71,0 %) | 254 / 257 (98,8 %) |
| Latence médiane | 6,8 s | 14,0 s |
| Tokens moyens par réponse | 831 | 13 638 |
| Appels Claude / requêtes de données par réponse | 1 / 0 | 5,0 / 4,2 |

Lecture : le taux de 71 % de Claude seul est flatteur, car un petit nombre (20, 30 %…) a de bonnes chances
d'apparaître par hasard dans des milliers de valeurs. La métrique robuste est la réponse entièrement sourcée :
0 sur 20 sans données, 17 sur 20 avec Timing. Le prix à payer : deux fois plus de latence et environ 16 fois
plus de tokens.
