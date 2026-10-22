# Départ — backtest hors échantillon

`python -m benchmarks.backtest` · synthèse : `results.json`

**Protocole (leave-one-year-out)** : pour chaque année test (2016-2025, hors 2020-2021) et chacun des 12 mois visés,
la saisonnalité des prix est recalculée **sans l'année testée** ; Départ recommande le mois le moins cher entre
deux mois avant et deux mois après le mois visé ; on compare ensuite, sur les prix réels de l'année testée (indice
Eurostat HICP France), le mois recommandé au mois visé. 96 cas par mode.

| Mode | Cas où Départ conseille de décaler | Économie moyenne quand on décale | Cas gagnants | Un mois au hasard dans la même fenêtre |
|---|---:|---:|---:|---:|
| Avion | 88 / 96 | **−9,4 %** | **89,8 %** | +1,0 % (plus cher) |
| Train | 88 / 96 | −2,8 % | 58,0 % | +0,1 % |

Lecture : en avion, décaler son départ de un ou deux mois selon Départ fait économiser en moyenne 9,4 % sur le
prix, et ça marche 9 fois sur 10. En train, l'effet existe mais reste faible ; Départ le dit à l'écran.

Limites : l'indice Eurostat mesure le prix moyen des billets en France (national et international confondus pour
l'avion), pas le prix d'un vol précis ; la date d'achat (anticipation) n'est pas couverte par les données ouvertes.

# Va-t-il monter ou baisser ? Prévision à 14 jours sur de vrais billets

`python -m benchmarks.price_forecast` · détail : `price_forecast.json`

Données : 22 historiques de prix réels Google Flights (environ 60 jours chacun, via SerpApi) sur des trajets
Paris → monde. Quatre règles ont été comparées ; la règle est **choisie sur 11 trajets** et **évaluée sur les 11
autres**. Une variation de plus de 2 % en 14 jours compte comme une hausse ou une baisse.

| Sur les trajets de test | Taux de bonnes prévisions | Quand la règle annonce une hausse |
|---|---:|---:|
| Toujours « stable » (référence) | 48,5 % | — |
| Retour à la médiane de 30 jours | 50,5 % | **59,0 % de hausses réelles** (39 alertes) |

Ce que Départ en fait : il n'affiche qu'un signal, « devrait remonter, réserve maintenant », quand le billet est
au moins 5 % sous sa médiane des 30 derniers jours, avec son taux de réussite mesuré (59 %). Annoncer une baisse
ne marche pas sur ces données (4 % de réussite) : Départ ne promet jamais qu'un prix va baisser.
