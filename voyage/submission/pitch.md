# Départ — pitch

**One line:** Départ tells you which month to travel by train or plane from Paris to pay less, from ten years of
real fares, traffic and calendars.

**Live:** https://01a16375-1a1b-73cb-9a26-fb1059c94d09-8080.eur-1.aiven.app
**Slide:** https://claude.ai/artifact/7BB3RttjhGJwek4E1N7YYV (to share before submitting)

## 3-minute video script (live app)

| Time | On screen | Voice-over (FR) |
|---|---|---|
| 0:00-0:15 | Home page, scroll slowly: plane takes off, train moves | « Le même billet ne coûte pas le même prix selon le mois. Personne ne te dit quand partir. » |
| 0:15-0:35 | Black section, numbers count up: +24 %, −11 %, −5 % | « En avion, juillet coûte 24 % de plus que la moyenne de l'année, janvier 11 % de moins. Dix ans de données Eurostat. » |
| 0:35-0:50 | « Quatre agents. Une seule réponse. » tiles | « Quatre agents Claude travaillent sur nos données Aiven : intake, analyst, calendar, advisor. » |
| 0:50-1:20 | Configurator: Avion, New York, juillet 2027 → « Trouver le meilleur moment » | « Je veux aller à New York en juillet. Je coche, sans rien écrire. » Result: « Pars en septembre 2027 » with the advice and « N/N chiffres retrouvés dans les données ». |
| 1:20-1:45 | Scroll: 3 key figures, month cards (juillet « À éviter », septembre « Le meilleur ») | « Septembre : billets environ 8 % moins chers que la moyenne, contre +24 % en juillet. Chaque mois a son verdict et sa raison. » |
| 1:45-2:10 | Back up: Train, Genève or Lyon → result, « Ton trajet » card with SNCF fares and TGVmax bars | « En train, il me donne les prix SNCF du trajet et les places TGVmax libres sur les 30 prochains jours, données SNCF du jour. » |
| 2:10-2:25 | Same handle twice → « Je me souviens » ; open « Voir le raisonnement » | « Il se souvient de moi, et chaque étape des agents est tracée : outils, requêtes, durées. » |
| 2:25-2:45 | `voyage/benchmarks/RESULTS.md` | « Testé hors échantillon sur dix ans : quand Départ décale un vol, on paie 9,4 % de moins en moyenne, 9 fois sur 10. En train l'effet est faible, et on le dit. » |
| 2:45-3:00 | Slide | « Eurostat, SNCF, calendriers officiels, sur ClickHouse, Postgres, Valkey et Runtime chez Aiven. Départ : pars au bon moment. » |

## Route to first users

1. Students and young workers who go home or on holiday: student unions, Crous, TikTok (team account).
2. Travel newsletters and deal communities: a monthly « when to go » post generated from the same data.
3. Freemium: free answer; paid « your window opens » alert; affiliate links to ticket sellers and SNCF Connect.
