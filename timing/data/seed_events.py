"""Seed de la table events (PostgreSQL). Les événements à date non officielle sont marqués
'à confirmer' : l'events agent les vérifie par recherche web et met à jour source/updated_at.

Usage : python -m data.seed_events   (depuis timing/)
"""
from datetime import date
from pathlib import Path

import psycopg

from app.config import PG_URI

SCHEMA = Path(__file__).parent / "schema_pg.sql"
SEED = "seed manuel"

# (nom, type, début, fin, périmètre, effet attendu, source)
EVENTS = [
    ("Jeux Olympiques Paris 2024", "sport", date(2024, 7, 26), date(2024, 8, 11), "75",
     "Locations courte durée tirées vers le haut, offre longue durée réduite l'été 2024", SEED),
    ("Jeux Paralympiques Paris 2024", "sport", date(2024, 8, 28), date(2024, 9, 8), "75",
     "Prolonge l'effet JO sur la rentrée 2024", SEED),
    ("Législatives anticipées 2024", "election", date(2024, 6, 30), date(2024, 7, 7), "FR",
     "Attentisme des acheteurs et vendeurs autour du scrutin", SEED),
    ("Municipales 2026", "election", date(2026, 3, 15), date(2026, 3, 22), "FR",
     "Attentisme local avant le scrutin, politiques logement susceptibles de changer", SEED),
    ("Présidentielle 2027", "election", date(2027, 4, 1), date(2027, 5, 31), "FR",
     "Attentisme des vendeurs historiquement observé avant la présidentielle (dates à confirmer)",
     "seed manuel, à confirmer"),
    ("Législatives 2027", "election", date(2027, 6, 1), date(2027, 6, 30), "FR",
     "Prolonge l'attentisme post-présidentielle (dates à confirmer)", "seed manuel, à confirmer"),
]

RECUR = "récurrent, dates approximatives (varient d'une année à l'autre)"

# Événements récurrents : (nom, type, (mois, jour) début, (mois, jour) fin, périmètre, effet, source)
# Une fin antérieure au début signifie que l'événement déborde sur l'année suivante.
RECURRING = [
    # Calendrier légal et loyers
    ("Trêve hivernale", "legal", (11, 1), (3, 31), "FR",
     "Pas d'expulsion : moins de logements libérés en hiver", SEED),
    ("Révision de l'encadrement des loyers Paris", "legal", (7, 1), (7, 1), "75",
     "Nouveaux loyers de référence applicables aux nouveaux baux", SEED),
    ("Publication IRL T4 (Insee)", "legal", (1, 10), (1, 20), "FR",
     "Indexation annuelle des loyers en cours de bail", RECUR),
    ("Publication IRL T1 (Insee)", "legal", (4, 10), (4, 20), "FR",
     "Indexation annuelle des loyers en cours de bail", RECUR),
    ("Publication IRL T2 (Insee)", "legal", (7, 10), (7, 20), "FR",
     "Indexation annuelle des loyers en cours de bail", RECUR),
    ("Publication IRL T3 (Insee)", "legal", (10, 10), (10, 20), "FR",
     "Indexation annuelle des loyers en cours de bail", RECUR),
    ("Échéance taxe foncière", "legal", (10, 1), (10, 20), "FR",
     "Propriétaires sous pression de trésorerie, quelques mises en vente ou en location", RECUR),
    # Calendrier étudiant et mobilités
    ("Rentrée décalée du second semestre", "academic", (1, 5), (2, 10), "FR",
     "Arrivées d'étudiants en échange et de stagiaires : demande ponctuelle sur studios", RECUR),
    ("Début des stages de printemps", "academic", (1, 2), (2, 15), "FR",
     "Demande de courte et moyenne durée (bail mobilité)", RECUR),
    ("Résultats Parcoursup (phase principale)", "academic", (6, 1), (7, 15), "FR",
     "Les admis commencent à chercher : la demande étudiante démarre", RECUR),
    ("Admissions Mon Master", "academic", (6, 1), (6, 30), "FR",
     "Étudiants de master qui changent de ville : demande sur studios et T1", RECUR),
    ("Résultats des concours et admissions des grandes écoles", "academic", (6, 15), (7, 20), "FR",
     "Arrivées d'élèves d'écoles parisiennes en septembre", RECUR),
    ("Fin d'année universitaire", "academic", (6, 1), (7, 15), "FR",
     "Départs d'étudiants et fins de stage : studios et T1 libérés", SEED),
    ("Résultats des mutations de fonctionnaires et d'enseignants", "academic", (6, 10), (7, 10), "FR",
     "Arrivées de familles fin août : demande sur T2 et T3", RECUR),
    ("Rush de la rentrée", "academic", (8, 20), (9, 30), "FR",
     "Pic de demande étudiante, concurrence maximale sur studios et T1", SEED),
    ("Fin des stages d'été", "academic", (8, 15), (9, 5), "FR",
     "Libération de logements en bail mobilité", RECUR),
    # Saisons et calendrier scolaire
    ("Creux estival", "season", (7, 20), (8, 25), "FR",
     "Peu de visites et de signatures, marché au ralenti", SEED),
    ("Fêtes de fin d'année", "season", (12, 20), (1, 3), "FR",
     "Visites rares, peu de nouvelles annonces", RECUR),
    ("Rush des signatures chez les notaires", "season", (12, 1), (12, 22), "FR",
     "Ventes signées avant la fin de l'année fiscale : pic de volume DVF en décembre", RECUR),
    ("Vacances de la Toussaint (zone C)", "season", (10, 19), (11, 3), "75",
     "Marché plus calme, moins de visites", RECUR),
    ("Vacances d'hiver (zone C)", "season", (2, 15), (3, 3), "75",
     "Marché plus calme, moins de visites", RECUR),
    ("Vacances de printemps (zone C)", "season", (4, 12), (4, 28), "75",
     "Marché plus calme, moins de visites", RECUR),
    ("Ponts de mai", "season", (5, 1), (5, 31), "FR",
     "Visites étalées, délais de réponse des propriétaires plus longs", RECUR),
    # Grands événements parisiens (pression sur la location courte durée)
    ("Fashion Week Paris (printemps)", "culture", (2, 24), (3, 5), "75",
     "Location courte durée tendue dans le centre et l'Ouest parisien", RECUR),
    ("Salon international de l'Agriculture", "culture", (2, 21), (3, 2), "75",
     "Pression hôtelière et location courte durée dans le 15e", RECUR),
    ("Roland-Garros", "sport", (5, 24), (6, 8), "75",
     "Location courte durée tendue dans le 16e et l'Ouest", RECUR),
    ("Fashion Week Paris (automne)", "culture", (9, 29), (10, 7), "75",
     "Location courte durée tendue au moment du rush de la rentrée", RECUR),
]

for y in range(2021, 2028):
    for name, kind, (m1, d1), (m2, d2), scope, effect, source in RECURRING:
        end_year = y + 1 if (m2, d2) < (m1, d1) else y
        label = f"{name} {y}-{end_year}" if end_year != y else f"{name} {y}"
        EVENTS.append((label, kind, date(y, m1, d1), date(end_year, m2, d2), scope, effect, source))


def main():
    with psycopg.connect(PG_URI) as conn:
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        conn.execute("DELETE FROM events WHERE source LIKE 'seed manuel%' OR source LIKE 'récurrent%'")
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO events (name, kind, start_date, end_date, scope, expected_effect, source)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (name, start_date) DO UPDATE SET
                     kind = EXCLUDED.kind, end_date = EXCLUDED.end_date, scope = EXCLUDED.scope,
                     expected_effect = EXCLUDED.expected_effect, source = EXCLUDED.source, updated_at = now()""",
                EVENTS,
            )
        print(f"events : {len(EVENTS)} lignes")


if __name__ == "__main__":
    main()
