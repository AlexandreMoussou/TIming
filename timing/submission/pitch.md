# Timing — pitch

**One line:** Timing tells students and young workers *when* and *where* to look for a flat in Paris, from 1.4 M real
sales, rents and the city's calendar.

**Live:** https://01a16333-5ca2-7cae-9130-3d31a4ac634f-8080.eur-1.aiven.app

## 3-minute video script (demo on the live app)

| Time | On screen | Voice-over |
|---|---|---|
| 0:00-0:20 | Home page, Paris illustration | « Léa vit à Clermont. Elle doit être à Paris en septembre, avec 900 € par mois. Quand chercher ? Où ? Personne ne lui dit. » |
| 0:20-0:45 | Tick: Louer, Studio, Tout Paris, septembre 2027, 900 €, pseudo `lea` → « Trouver le bon moment » | « Elle coche six cases. Quatre agents Claude se mettent au travail sur nos données Aiven. » (show the moving-truck progress) |
| 0:45-1:20 | Result: « Cherche en juillet 2027 », 3 key figures, month-by-month calendar | « Juillet : 30 % de logements en plus qu'un mois moyen, avant le rush de la rentrée. Août est à éviter, septembre est pris d'assaut. Chaque chiffre est vérifié dans les données : 6 sur 6. » |
| 1:20-1:40 | « Où ton budget passe » cards + « Ce qui va jouer » | « Le 19e, le 20e, le 18e entrent dans son budget, sous le plafond de l'encadrement. Et elle voit ce qui arrive : Parcoursup, la révision des loyers, les élections. » |
| 1:40-1:55 | Switch to « Pas de date, je suis flexible » | « Sans date imposée, Timing trouve le meilleur moment des 12 prochains mois : mars. » |
| 1:55-2:15 | Same handle, T2 → « Je me souviens » + « Voir le raisonnement » | « Timing se souvient d'elle. Et on peut ouvrir le raisonnement : chaque agent, chaque requête ClickHouse, chaque durée. » |
| 2:15-2:40 | `benchmarks/RESULTS.md` | « On l'a testé hors échantillon sur 5 ans : dans 92 % des 299 cas, le mois choisi bat un mois au hasard. Et face au même modèle sans nos données : 17 réponses sur 20 entièrement sourcées, contre 0. On dit aussi ce qui ne marche pas : pour un achat, le mois ne fait pas baisser le prix. » |
| 2:40-3:00 | Slide | « 1,4 million de ventes, ClickHouse, Postgres, Valkey et Runtime sur Aiven. Premiers utilisateurs : les BDE, le Crous, les groupes logement. Timing : le bon moment, au bon endroit. » |

## Route to first users

1. Student unions and housing offices (ESILV, Pôle Léonard de Vinci, Crous): a link in the welcome pack for
   admitted students, from June.
2. Facebook "logement étudiant Paris" groups and TikTok (team account): short "when to search" videos per month.
3. Freemium: free answer; paid "the window opens" alert and weekly follow-up; partnerships with rental guarantors
   (Garantme, Visale) who need students to sign at the right time.
