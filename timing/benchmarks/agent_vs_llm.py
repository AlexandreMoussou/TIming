"""Before / after : Claude seul (sans outils ni données) vs Timing (agents + ClickHouse/Postgres/Valkey).

Pour chacune des 20 questions, on mesure :
- le nombre de chiffres cités et la part retrouvée dans les données réelles (sorties des outils Timing
  pour les mêmes paramètres) : un chiffre non retrouvé est non sourcé (potentiellement inventé) ;
- la latence et les tokens consommés.
Même modèle des deux côtés.

Usage : python -m benchmarks.agent_vs_llm   (depuis timing/)
"""
import csv
import json
import statistics as st
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.agents import orchestrator as orch
from app.agents.tools import compute_window, get_upcoming_events, rank_neighbourhoods

OUT = Path(__file__).parent
TODAY = "2026-10-22"

Q = [
    ("Je dois être installé à Paris en septembre 2027, studio, 900 € max. Quand chercher ?", "louer", "studio_t1", "75", "2027-09-01", 900),
    ("Étudiant, je cherche un studio dans le 11e pour septembre 2027, budget 850 €.", "louer", "studio_t1", "75111", "2027-09-01", 850),
    ("Je cherche un T2 à Paris pour janvier 2027, 1 400 € par mois.", "louer", "t2", "75", "2027-01-01", 1400),
    ("Quand chercher un studio dans le 5e pour la rentrée 2027 ? 1 000 €.", "louer", "studio_t1", "75105", "2027-09-01", 1000),
    ("Jeune actif, T2 dans le 18e pour mars 2027, budget 1 300 €.", "louer", "t2", "75118", "2027-03-01", 1300),
    ("Famille, T3 à Paris pour septembre 2027, 2 200 € par mois.", "louer", "t3plus", "75", "2027-09-01", 2200),
    ("Studio dans le 13e pour février 2027, 800 €.", "louer", "studio_t1", "75113", "2027-02-01", 800),
    ("Je veux louer un T2 dans le 15e pour juillet 2027, 1 500 €.", "louer", "t2", "75115", "2027-07-01", 1500),
    ("Studio à Paris pour octobre 2027, 750 € max, où et quand ?", "louer", "studio_t1", "75", "2027-10-01", 750),
    ("T2 dans le 20e pour juin 2027, budget 1 250 €.", "louer", "t2", "75120", "2027-06-01", 1250),
    ("Je veux acheter un T2 dans le 11e pour septembre 2027, 450 000 €.", "acheter", "t2", "75111", "2027-09-01", 450000),
    ("Acheter un studio à Paris pour juin 2027, budget 250 000 €.", "acheter", "studio_t1", "75", "2027-06-01", 250000),
    ("Achat d'un T3 dans le 15e pour septembre 2027, 800 000 €.", "acheter", "t3plus", "75115", "2027-09-01", 800000),
    ("Acheter un T2 dans le 19e pour mars 2027, 350 000 €.", "acheter", "t2", "75119", "2027-03-01", 350000),
    ("Quand acheter un studio dans le 18e pour fin 2027 ? 230 000 €.", "acheter", "studio_t1", "75118", "2027-12-01", 230000),
    ("Je veux vendre mon T2 dans le 10e d'ici septembre 2027.", "vendre", "t2", "75110", "2027-09-01", None),
    ("Vendre un studio dans le 17e avant juin 2027 : quel mois ?", "vendre", "studio_t1", "75117", "2027-06-01", None),
    ("Vendre un T3 dans le 12e pour fin 2027.", "vendre", "t3plus", "75112", "2027-12-01", None),
    ("Stage à Paris en janvier 2027, je cherche un studio, 900 €.", "louer", "studio_t1", "75", "2027-01-01", 900),
    ("Mutation à Paris en septembre 2027, T3, 2 500 € par mois.", "louer", "t3plus", "75", "2027-09-01", 2500),
]

LLM_ONLY_SYSTEM = ("Tu es un conseiller immobilier à Paris. Aujourd'hui : " + TODAY + ". Réponds en français en 4 à 5 "
                   "phrases : quand chercher, pourquoi (avec des chiffres précis : volumes, prix au m², loyers), "
                   "quels arrondissements pour le budget, quels événements surveiller. Texte brut.")


def ground_truth(intent, typ, zone, move_in, budget):
    w = compute_window(intent, typ, zone, move_in, TODAY)
    r = rank_neighbourhoods(typ, budget, "75", intent)
    e = get_upcoming_events(TODAY, move_in, "75")
    return [w, r, e]


def llm_only(text):
    run = orch.Run()
    t = time.time()
    msg = orch._create(run, model=orch.MODEL, max_tokens=1200, system=LLM_ONLY_SYSTEM,
                       messages=[{"role": "user", "content": text}])
    answer = " ".join(b.text for b in msg.content if b.type == "text")
    return answer, int((time.time() - t) * 1000), run.tokens


def one(q):
    text, intent, typ, zone, move_in, budget = q
    truth = ground_truth(intent, typ, zone, move_in, budget)
    a_text, a_ms, a_tok = llm_only(text)
    a_g = orch.grounding(a_text, truth)
    r = orch.recommend(text, None, TODAY, {"intent": intent, "typology": typ, "zone": zone, "move_in": move_in,
                                           "budget": budget})
    return {
        "question": text,
        "llm_numbers": a_g["numbers"], "llm_grounded": a_g["grounded"], "llm_latency_ms": a_ms,
        "llm_tokens": a_tok["input"] + a_tok["output"], "llm_answer": a_text,
        "timing_numbers": r["grounding"]["numbers"], "timing_grounded": r["grounding"]["grounded"],
        "timing_latency_ms": r["latency_ms"], "timing_tokens": r["usage"]["input"] + r["usage"]["output"],
        "timing_llm_calls": r["usage"]["llm_calls"], "timing_tool_calls": r["usage"]["tool_calls"],
        "timing_mode": r["mode"], "timing_answer": r["advice"], "timing_run_id": r["run_id"],
    }


def main():
    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(one, Q))
    with open(OUT / "agent_vs_llm.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    def side(p):
        n = sum(r[f"{p}_numbers"] for r in rows)
        g = sum(r[f"{p}_grounded"] for r in rows)
        return {"numbers_cited": n, "numbers_found_in_data": g, "grounded_pct": round(100 * g / n, 1) if n else None,
                "answers_fully_grounded": sum(r[f"{p}_numbers"] > 0 and r[f"{p}_grounded"] == r[f"{p}_numbers"]
                                              for r in rows),
                "median_latency_s": round(st.median(r[f"{p}_latency_ms"] for r in rows) / 1000, 1),
                "mean_tokens": round(st.mean(r[f"{p}_tokens"] for r in rows))}
    summary = {"questions": len(rows), "model": orch.MODEL, "claude_alone": side("llm"), "timing": side("timing"),
               "timing_mean_llm_calls": round(st.mean(r["timing_llm_calls"] for r in rows), 1),
               "timing_mean_tool_calls": round(st.mean(r["timing_tool_calls"] for r in rows), 1),
               "timing_modes": sorted({r["timing_mode"] for r in rows})}
    (OUT / "agent_vs_llm.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
