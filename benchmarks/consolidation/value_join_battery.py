"""Replay battery for the value join (`value_alignment`, G148): does a value said again in other words replace the old
one, and are two real attributes that look alike left apart?

Why: the join is a judgement of Sleep's small judge, and a pair it refuses is never seen again (the newer value is no
longer new). A benchmark run meets the question about once; this replays the product's own `value_alignment.align`
(the same prompts, the person's own words read back from located spans) on invented pages for cents, 20+ repeats.
Every name, value and line below is invented. Two reads: the first as it ships, and, when `align` takes a `reread`
judge, the second reading of the lines the first refused.

    api/.venv/bin/python -m benchmarks.consolidation.value_join_battery --repeats 20 --out /tmp/vjb

Needs ``ANTHROPIC_API_KEY`` in the environment or in ``--key-file`` (never printed). Prints the true joins and false
joins per repeat and, per stage, what the first read proposed and what the check kept.
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

CASES = [
 # --- the first battery's 32 pairs, now with the person's line ---
 ("price per postcard", "4 euros", "I sell my postcards at 4 euros each.", "card price", "5 euros", "I put the price of the cards up to 5 euros.", True),
 ("price per postcard", "4 euros", "I sell my postcards at 4 euros each.", "prix des cartes", "5 euros", "J'ai monté le prix des cartes à 5 euros.", True),
 ("monthly rent", "900 euros", "I pay 900 euros of rent a month.", "alquiler mensual", "950 euros", "Me han subido el alquiler a 950 euros al mes.", True),
 ("number of employees", "12", "We are 12 people at the studio.", "headcount", "15", "Headcount is 15 now, we hired three.", True),
 ("5k personal best", "24:10", "My 5k personal best is 24:10.", "mejor marca en 5 km", "23:50", "Hoy bajé mi mejor marca en 5 km a 23:50.", True),
 ("weight", "80 kg", "I weigh 80 kg right now.", "aktuelles Gewicht", "78 kg", "Mein aktuelles Gewicht ist 78 kg.", True),
 ("team size", "4", "Our team is four people.", "Teamgröße", "6", "Unsere Teamgröße ist jetzt sechs.", True),
 ("launch date", "March", "We plan to launch in March.", "release date", "April", "The release got pushed to April.", True),
 ("annual salary", "50k", "I earn 50k a year.", "yearly pay", "55k", "After the raise my yearly pay is 55k.", True),
 ("city of residence", "Lyon", "J'habite à Lyon.", "lieu de résidence", "Grenoble", "J'ai déménagé, j'habite à Grenoble maintenant.", True),
 ("books read this year", "12", "I have read 12 books this year.", "libros leídos en 2026", "15", "Este año ya llevo 15 libros leídos.", True),
 ("battery life", "10 hours", "The battery lasts about 10 hours.", "autonomie de la batterie", "12 heures", "La batterie tient maintenant 12 heures.", True),
 ("postcard price", "5 euros", "Postcards are 5 euros.", "print price", "18 euros", "My A4 prints go for 18 euros.", False),
 ("trip budget excluding flights", "3500 euros", "The budget for the trip is 3500 euros, not counting flights.", "flight cost", "900 euros", "The flights cost 900 euros.", False),
 ("5k personal best", "24:10", "My 5k personal best is 24:10.", "10k personal best", "51:30", "I ran a 10k personal best of 51:30 today.", False),
 ("goal finish time", "1:45", "I am aiming for 1:45 at the half marathon.", "finish time", "1:47", "I finished the half in 1:47.", False),
 ("monthly rent", "900 euros", "I pay 900 euros of rent a month.", "deposit", "1800 euros", "The deposit was 1800 euros.", False),
 ("number of employees", "12", "We are 12 people at the studio.", "number of offices", "3", "We have three offices now.", False),
 ("age", "34", "I am 34.", "dog age", "5", "My dog is 5 years old.", False),
 ("price", "5 euros", "The ticket price is 5 euros.", "shipping cost", "3 euros", "Shipping costs 3 euros.", False),
 ("maximum participants", "20", "We can take at most 20 participants.", "minimum participants", "8", "We need at least 8 participants to run it.", False),
 ("gross salary", "60k", "My gross salary is 60k.", "net salary", "45k", "I take home 45k net.", False),
 ("launch date", "March", "The product launches in March.", "event date", "April", "The launch party is in April.", False),
 ("weight", "80 kg", "I weigh 80 kg.", "target weight", "75 kg", "I want to get down to 75 kg.", False),
 ("cards sold", "85", "I have sold 85 cards.", "cards printed", "100", "I printed 100 cards in the last run.", False),
 ("revenue 2025", "12k", "Revenue for 2025 was 12k.", "revenue 2026", "15k", "Revenue for 2026 is 15k so far.", False),
 ("battery capacity", "4000 mAh", "The battery is 4000 mAh.", "battery life", "12 hours", "It runs 12 hours on a charge.", False),
 ("altura", "180 cm", "Mido 180 cm.", "altura del edificio", "40 m", "El edificio mide 40 m de altura.", False),
 ("precio por postal", "4 euros", "Vendo las postales a 4 euros.", "precio por cuadro enmarcado", "30 euros", "Los cuadros enmarcados cuestan 30 euros.", False),
 ("temps au 10 km", "52:00", "Je cours le 10 km en 52:00.", "objectif de temps au 10 km", "50:00", "Mon objectif sur 10 km est de 50:00.", False),
 ("books read this year", "12", "I have read 12 books this year.", "books owned", "300", "I own about 300 books.", False),
 ("sales in March", "40", "We sold 40 units in March.", "sales in April", "55", "We sold 55 units in April.", False),
 # --- true, with a change verb or a plain statement, other kinds of value ---
 ("launch date", "the 10th", "The launch is on the 10th.", "release date", "the 12th", "We moved the release to the 12th.", True),
 ("beta users", "80", "We have 80 beta users.", "number of beta testers", "120", "We're at 120 beta testers now.", True),
 ("main language", "Rust with SDL", "Brightloom is written in Rust with SDL.", "core language", "Go", "I rewrote Brightloom's core in Go and dropped the Rust version.", True),
 ("rent", "900 euros", "I pay 900 euros rent.", "Miete", "950 Euro", "Ich zahle jetzt 950 Euro Miete.", True),
 ("prezzo del biglietto", "10 euro", "Il biglietto costa 10 euro.", "ticket price", "12 euros", "I raised the ticket price to 12 euros.", True),
 ("diet", "vegetarian", "I'm vegetarian.", "régime alimentaire", "vegan", "Je suis passé à un régime vegan.", True),
 # --- different things, both lines carry a change verb (the temptation) ---
 ("monthly rent", "900 euros", "I raised the rent to 900 euros.", "deposit", "1900 euros", "I raised the deposit to 1900 euros.", False),
 ("price per postcard", "4 euros", "I raised the price of postcards to 4 euros.", "print price", "18 euros", "I raised the price of my prints to 18 euros.", False),
 ("team size", "4", "We grew the team to four people.", "number of interns", "2", "We took on two more interns this month.", False),
 ("prix des cartes", "4 euros", "J'ai baissé le prix des cartes à 4 euros.", "prix des tirages", "18 euros", "J'ai baissé le prix des tirages à 18 euros.", False),
 ("alquiler", "900 euros", "Subí el alquiler a 900 euros.", "fianza", "1900 euros", "Subí la fianza a 1900 euros.", False),
 ("Miete", "900 Euro", "Ich habe die Miete auf 900 Euro erhöht.", "Kaution", "1900 Euro", "Ich habe die Kaution auf 1900 Euro erhöht.", False),
 ("launch date", "April", "I moved the launch to April.", "event date", "May", "I moved the launch party to May.", False),
 ("beta users", "80", "We are at 80 beta users.", "paying users", "120", "We're at 120 paying users now.", False),
 ("design review date", "the 10th", "The design review is on the 10th.", "demo date", "the 12th", "I moved the demo to the 12th.", False),
 ("5k personal best", "24:10", "I improved my 5k to 24:10.", "10k personal best", "51:30", "I improved my 10k to 51:30.", False),
 ("weight", "80 kg", "I lost some weight, I'm at 80 kg.", "target weight", "75 kg", "I lowered my target weight to 75 kg.", False),
 ("revenue 2025", "12k", "Revenue for 2025 went up to 12k.", "revenue 2026", "15k", "Revenue for 2026 went up to 15k.", False),
 ("hourly rate", "60 euros", "I raised my hourly rate to 60 euros.", "day rate", "400 euros", "I raised my day rate to 400 euros.", False),
 ("annual salary", "50k", "My salary went up to 50k.", "annual bonus", "5k", "My bonus went up to 5k.", False),
 # --- text values (a tool, a place, a name): the shape of the benchmark's missed pairs, other things ---
 ("implementation language", "Python with Pillow", "It is written in Python with Pillow.", "core language", "TypeScript", "I rewrote its core in TypeScript so it runs in the browser, and dropped the Python version entirely.", True),
 ("database", "SQLite", "The app stores everything in SQLite.", "storage backend", "Postgres", "We moved the storage over to Postgres last week.", True),
 ("hosting provider", "a small VPS", "It runs on a small VPS.", "deployment platform", "Fly.io", "I deployed it on Fly.io instead.", True),
 ("code editor", "Vim", "I do all my coding in Vim.", "IDE", "Zed", "These days I code in Zed.", True),
 ("current employer", "a bank", "I work at a bank.", "lugar de trabajo", "a startup", "Cambié de trabajo, ahora estoy en una startup.", True),
 ("phone model", "an old Pixel", "I still use my old Pixel.", "téléphone", "un iPhone", "J'ai enfin changé de téléphone, j'ai un iPhone.", True),
 ("project status", "in planning", "The project is still in planning.", "Projektstand", "in Entwicklung", "Das Projekt ist jetzt in Entwicklung.", True),
 ("preferred coffee", "flat white", "My usual order is a flat white.", "café habitual", "cortado", "Ahora pido siempre un cortado.", True),
 ("sprint length", "two weeks", "Our sprints are two weeks long.", "iteration length", "one week", "We shortened the iterations to one week.", True),
 ("deployment frequency", "monthly", "We deploy once a month.", "release cadence", "weekly", "We release every week now.", True),
 ("frontend language", "TypeScript", "The frontend is in TypeScript.", "backend language", "Go", "The backend is written in Go.", False),
 ("core language", "Rust", "The core is written in Rust.", "scripting language", "Lua", "Plugins are scripted in Lua.", False),
 ("database", "Postgres", "Everything is stored in Postgres.", "cache", "Redis", "We put a Redis cache in front of it.", False),
 ("hosting provider", "Fly.io", "It is hosted on Fly.io.", "domain registrar", "Gandi", "The domain is registered at Gandi.", False),
 ("code editor", "Zed", "I code in Zed.", "terminal", "Ghostty", "My terminal is Ghostty.", False),
 ("lugar de trabajo", "una startup", "Trabajo en una startup.", "lugar de residencia", "Valencia", "Vivo en Valencia.", False),
 ("main language", "French", "My first language is French.", "language I am learning", "Japanese", "I am learning Japanese.", False),
 ("current book", "Dune", "I am reading Dune.", "book I recommend", "Piranesi", "I would recommend Piranesi to anyone.", False),
 ("Projektstand", "in Entwicklung", "Das Projekt ist in Entwicklung.", "Budgetstatus", "überschritten", "Das Budget ist überschritten.", False),
 ("sprint length", "two weeks", "I changed our sprints to two weeks.", "retro length", "one hour", "I changed the retro to one hour.", False),
 # --- adversarial: the new line sounds like a replacement but is another attribute; and true ones said very plainly ---
 ("backend framework", "Django", "The backend runs on Django.", "frontend framework", "Svelte", "I switched the frontend to Svelte instead of React.", False),
 ("postcard price", "5 euros", "Postcards cost 5 euros.", "print price", "18 euros", "Now my prints cost 18 euros, up from 12.", False),
 ("home city", "Lyon", "I live in Lyon.", "work city", "Paris", "I now work in Paris, I moved my office there.", False),
 ("current job title", "engineer", "I'm an engineer.", "previous job title", "analyst", "Before that I was an analyst, I left that role in 2020.", False),
 ("monthly rent", "900 euros", "I pay 900 euros rent.", "utilities", "120 euros", "My utilities went up, now 120 euros a month.", False),
 ("number of employees", "12", "We have 12 employees.", "number of customers", "300", "We now have 300 customers, up from 200.", False),
 ("gym days per week", "3", "I go to the gym three times a week.", "running days per week", "2", "I replaced my second gym day with a run, so I run twice a week.", False),
 ("main database", "Postgres", "Our main database is Postgres.", "analytics database", "ClickHouse", "We replaced our old analytics store with ClickHouse.", False),
 ("coffee order", "flat white", "I always order a flat white.", "tea order", "oolong", "I switched from green tea to oolong.", False),
 ("sleep hours", "7", "I sleep 7 hours a night.", "nap length", "20 minutes", "I cut my nap down to 20 minutes.", False),
 ("annual salary", "50k", "I make 50k a year.", "spouse's annual salary", "62k", "My partner's salary is now 62k.", False),
 ("mortgage rate", "3.1%", "My mortgage rate is 3.1%.", "savings account rate", "2.5%", "The savings rate went up to 2.5%.", False),
 ("number of employees", "12", "We are 12 employees.", "headcount", "15", "We're at 15.", True),
 ("monthly rent", "900 euros", "My rent is 900 euros.", "loyer", "950 euros", "950 maintenant.", True),
 ("preferred editor", "Vim", "I use Vim.", "daily editor", "Zed", "Zed, since last month.", True),
 ("team lead", "Marta", "Marta leads the team.", "responsable de l'équipe", "Samir", "C'est Samir qui dirige l'équipe maintenant.", True),
 ("car", "a diesel Golf", "I drive a diesel Golf.", "vehicle", "an electric Kia", "I traded in the Golf for an electric Kia.", True),
 ("wedding date", "June 14", "The wedding is on June 14.", "fecha de la boda", "June 21", "Hemos movido la fecha de la boda al 21 de junio.", True),
]
# pages with several values (as a real batch): (name, [(attr, value, line, day)] existing, [(attr, value, line, day)] new, {new attr: old attr or None})
PAGES = [
 ("cartolina", [("price per postcard", "4 euros", "I sell my postcards at 4 euros each.", "2026-09-26"), ("cards sold", "20", "I have sold 20 so far.", "2026-10-10"), ("shop platform", "Shopify", "The shop runs on Shopify.", "2026-09-26")],
  [("card price", "5 euros", "I put the price of the cards up to 5 euros.", "2026-11-01"), ("cartes vendues", "85", "J'ai vendu 85 cartes.", "2026-11-11"), ("print price A4", "18 euros", "My A4 prints go for 18 euros.", "2026-11-13"), ("restock quantity", "100", "I'm reordering 100 cards.", "2026-11-11")],
  {"card price": "price per postcard", "cartes vendues": "cards sold", "print price A4": None, "restock quantity": None}),
 ("banking study", [("start date", "2026-10-07", "The study starts on October 7.", "2026-10-02"), ("participants", "8", "We recruited 8 participants.", "2026-10-02")],
  [("readout date", "2026-11", "The readout is in November.", "2026-10-14"), ("participants who failed the transfer flow", "7", "7 participants failed the transfer flow.", "2026-11-05")],
  {"readout date": None, "participants who failed the transfer flow": None}),
 ("japan trip", [("budget excluding flights", "3000 euros", "The budget is 3000 euros without flights.", "2026-10-04"), ("rail pass", "14-day", "I will buy the 14-day rail pass.", "2026-10-04"), ("hotel nights", "10", "We need 10 hotel nights.", "2026-10-04")],
  [("flights total price", "900 euros", "The flights come to 900 euros total.", "2026-11-17"), ("presupuesto sin vuelos", "3500 euros", "Subí el presupuesto sin vuelos a 3500 euros.", "2026-11-08"), ("noches de hotel", "12", "Ahora son 12 noches de hotel.", "2026-11-09"), ("booking status", "not yet booked", "Nothing is booked yet.", "2026-11-17")],
  {"flights total price": None, "presupuesto sin vuelos": "budget excluding flights", "noches de hotel": "hotel nights", "booking status": None}),
 ("race", [("goal finish time", "1:50", "I want to finish in 1:50.", "2026-09-01"), ("registration fee", "40 euros", "Registration is 40 euros.", "2026-09-01"), ("distance", "21.1 km", "It is a half marathon, 21.1 km.", "2026-09-01"), ("start time", "09:00", "The start is at 09:00.", "2026-09-01")],
  [("objectif de temps", "1:45", "Je vise 1:45 maintenant.", "2026-10-20"), ("finish time", "1:47", "I finished in 1:47.", "2026-11-16"), ("frais d'inscription", "45 euros", "L'inscription a augmenté, c'est 45 euros.", "2026-10-22"), ("heure de départ", "08:30", "Le départ a été avancé à 08:30.", "2026-11-01")],
  {"objectif de temps": "goal finish time", "finish time": None, "frais d'inscription": "registration fee", "heure de départ": "start time"}),
]


# Appended 2026-11-24 (the re-read work): plain statements with no change verb, and real attributes that look alike.
CASES += [
 ("job title", "engineer", "I'm an engineer.", "role", "tech lead", "Now I'm the tech lead.", True),
 ("favourite cafe", "Blue Door", "My favourite cafe is Blue Door.", "go-to coffee shop", "Saint Louis", "My go-to coffee shop is Saint Louis now.", True),
 ("bedtime", "11pm", "I go to bed at 11pm.", "hora de dormir", "10pm", "Ahora me acuesto a las 10pm.", True),
 ("budget", "3000 euros", "I set the budget at 3000 euros.", "spending limit", "3500 euros", "The spending limit is now 3500 euros.", True),
 ("website host", "a shared server", "The site is on a shared server.", "where the site is hosted", "Netlify", "The site is hosted on Netlify now.", True),
 ("monthly savings", "300 euros", "I save 300 euros a month.", "ahorro mensual", "400 euros", "Ahora ahorro 400 euros al mes.", True),
 ("main programming language", "Python", "I mostly write Python.", "language I use most", "Go", "These days I write mostly Go.", True),
 ("email provider", "Gmail", "My email is on Gmail.", "mail service", "Fastmail", "I moved my email to Fastmail.", True),
 ("flight departure time", "08:30", "The flight leaves at 08:30.", "departure", "10:15", "It was rescheduled, it leaves at 10:15 now.", True),
 ("price per card", "5 euros", "I charge 5 euros a card.", "price per print", "18 euros", "I charge 18 euros a print.", False),
 ("budget including flights", "5000 euros", "The whole trip budget is 5000 euros, flights included.", "budget excluding flights", "3500 euros", "The budget without the flights is 3500 euros.", False),
 ("study start date", "October 7", "The study starts on October 7.", "study readout date", "November 20", "We read out the results on November 20.", False),
 ("flat rent", "900 euros", "The flat is 900 euros a month.", "garage rent", "80 euros", "The garage is 80 euros a month.", False),
 ("current salary", "50k", "I earn 50k.", "salary offer", "58k", "They offered me 58k at the new place.", False),
 ("headcount this year", "12", "We are 12 this year.", "headcount last year", "9", "Last year we were 9.", False),
 ("battery life, video", "10 hours", "Video playback lasts 10 hours.", "battery life, standby", "40 hours", "Standby lasts 40 hours.", False),
 ("minimum order", "10", "The minimum order is 10 pieces.", "maximum order", "500", "The maximum order is 500 pieces.", False),
]

# More look-alikes (2026-11-24), each a pair of real attributes the second reading must leave apart.
CASES += [
 ("home internet speed", "100 Mbps", "My home internet is 100 Mbps.", "office internet speed", "1 Gbps", "The office was upgraded to 1 Gbps.", False),
 ("daughter's age", "5", "My daughter is 5.", "son's age", "8", "My son just turned 8.", False),
 ("shop opening time", "09:00", "The shop opens at 9.", "shop closing time", "18:00", "It closes at 18:00 now.", False),
 ("current mortgage balance", "200k", "I still owe 200k on the mortgage.", "original mortgage amount", "250k", "We borrowed 250k originally.", False),
 ("outbound flight time", "08:30", "The outbound flight leaves at 08:30.", "return flight time", "19:45", "The return flight is at 19:45 now.", False),
 ("team lead", "Marta", "Marta leads the team.", "product owner", "Samir", "Samir is the product owner now.", False),
 ("commute time", "40 minutes", "My commute takes 40 minutes.", "commute distance", "12 km", "The commute is 12 km.", False),
 ("max heart rate", "190", "My max heart rate is 190.", "resting heart rate", "52", "My resting heart rate dropped to 52.", False),
 ("rent in Lyon", "900 euros", "I paid 900 euros rent in Lyon.", "rent in Paris", "1400 euros", "Rent in Paris is 1400 euros now.", False),
 ("phone storage", "128 GB", "My phone has 128 GB.", "laptop storage", "1 TB", "I upgraded the laptop to 1 TB.", False),
 ("ticket price", "40 euros", "The ticket was 40 euros.", "ticket price with fees", "46 euros", "With the fees the ticket came to 46 euros.", False),
 ("hours worked per week", "40", "I work 40 hours a week.", "hours of meetings per week", "12", "I spend 12 hours a week in meetings now.", False),
]


bank = Path(tempfile.mkdtemp(prefix="vjb-bank-"))
(bank / "episodes").mkdir()
(bank / "entities").mkdir()
_n = [0]


def _episode(day, line):
    """One conversation holding the person's line (and a made-up assistant reply): its id and the line's evidence."""
    from api.services import evidence

    _n[0] += 1
    ep = f"ep_{day}_{_n[0]:04d}"
    (bank / "episodes" / f"{ep}.md").write_text(
        f"---\nid: {ep}\ntimestamp: '{day}T10:00:00+00:00'\nsource: import\nprocessed: true\n---\n\n"
        f"user: {line}\nassistant: Noted, thank you.\n", encoding="utf-8")
    return ep, evidence.verify(bank, ep, line)


def _claim(cid, subj, attr, val, day, line):
    from api.services.claims import Claim, value_predicate

    ep, ev = _episode(day, line)
    return Claim(id=cid, text=f"{subj} {attr}: {val}", subject=subj, predicate=value_predicate(attr), object=val,
                 object_kind="literal", valid_from=day, source_episodes=[ep], evidence=[ev])


class Trace:
    """Wraps a judge: what each call answered, by kind (the first read, the check, the second reading)."""

    def __init__(self, judge):
        self.judge, self.calls = judge, []

    def __call__(self, text):
        reply = self.judge(text)
        kind = ("check" if text.startswith("One person's memory holds two") else
                "first" if text.startswith("One person's memory page") else "other")
        self.calls.append((kind, reply))
        return reply


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--model", default="haiku", help="Sleep's small judge (the first read and the check)")
    ap.add_argument("--reader", default="", help="the second reading's model (default: none, or what align takes)")
    ap.add_argument("--out", default="")
    ap.add_argument("--only", default="", help="substring of the new attribute to run")
    ap.add_argument("--false-only", action="store_true", help="run only the pairs that must stay apart")
    ap.add_argument("--key-file", default="~/.cicada/secrets.env")
    ap.add_argument("--parallel", type=int, default=8)
    args = ap.parse_args(argv)
    os.environ["CICADA_HOME"] = tempfile.mkdtemp(prefix="vjb-home-")
    from benchmarks.engine_parity import read_key_file, settings_for
    from benchmarks.consolidation.run import engine_model
    from api.services import value_alignment as va

    os.environ.setdefault("ANTHROPIC_API_KEY", read_key_file(Path(args.key_file).expanduser()) or "")
    out = Path(args.out).expanduser() if args.out else Path(tempfile.mkdtemp(prefix="vjb-out-"))
    out.mkdir(parents=True, exist_ok=True)
    m = engine_model("key", args.model)
    small = va.judge_for(settings_for("key", out, model=m, judge=m))
    params = inspect.signature(va.align).parameters
    extra = {}
    if "reread" in params and args.reader:
        r = engine_model("key", args.reader)
        extra["reread"] = va.judge_for(settings_for("key", out, model=r, judge=r))

    def run_case(i):
        oa, ov, ol, na, nv, nl, same = CASES[i]
        old = _claim(f"o{i}", "thing", oa, ov, "2026-09-01", ol)
        new = _claim(f"n{i}", "thing", na, nv, "2026-11-01", nl)
        was = new.predicate
        tr = Trace(small)
        kw = dict(extra)
        if "reread" in kw:
            kw["reread"] = Trace(kw["reread"])
        va.align([new], {"thing": [old]}, tr, **({"memory_path": bank} if "memory_path" in params else {}), **kw)
        calls = tr.calls + (kw["reread"].calls if "reread" in kw else [])
        return {"old": oa, "new": na, "should_join": same, "joined": new.predicate != was,
                "stages": [(k, r) for k, r in calls]}

    def run_page(k):
        name, olds, news, truth = PAGES[k]
        existing, incoming, by_attr = [], [], {}
        for i, (a, v, l, d) in enumerate(olds):
            c = _claim(f"po{k}{i}", name, a, v, d, l)
            existing.append(c)
            by_attr[a] = c
        for i, (a, v, l, d) in enumerate(news):
            c = _claim(f"pn{k}{i}", name, a, v, d, l)
            incoming.append(c)
            by_attr[a] = c
        before = {c.id: c.predicate for c in incoming}
        kw = dict(extra)
        va.align(incoming, {name: existing}, small, **({"memory_path": bank} if "memory_path" in params else {}), **kw)
        rows = []
        for (a, v, l, d), c in zip(news, incoming):
            want, got = truth[a], None
            if c.predicate != before[c.id]:
                got = next((oa for oa, oc in by_attr.items() if oc.id != c.id and oc.predicate == c.predicate), "?")
            rows.append({"page": name, "new": a, "want": want, "got": got, "ok": got == want})
        return rows

    idx = [i for i, c in enumerate(CASES) if args.only in c[3] and not (args.false_only and c[6])]
    summary = []
    for rep in range(args.repeats):
        with ThreadPoolExecutor(args.parallel) as ex:
            cases = list(ex.map(run_case, idx))
            pages = [r for rows in ex.map(run_page, range(len(PAGES))) for r in rows]
        (out / f"run{rep + 1}.json").write_text(json.dumps({"cases": cases, "pages": pages}, indent=1, ensure_ascii=False))
        for r in cases:
            if r["joined"] != r["should_join"]:
                print(f"run{rep + 1} BAD {r['old']!r} / {r['new']!r} should_join={r['should_join']} joined={r['joined']}")
        for r in pages:
            if not r["ok"]:
                print(f"run{rep + 1} BAD page [{r['page']}] {r['new']!r} -> {r['got']!r} (want {r['want']!r})")
        T = [r for r in cases if r["should_join"]]
        F = [r for r in cases if not r["should_join"]]
        summary.append(f"run{rep + 1}: true joins {sum(r['joined'] for r in T)}/{len(T)} | false joins "
                       f"{sum(r['joined'] for r in F)} of {len(F)} | page rows right {sum(r['ok'] for r in pages)}/{len(pages)}")
        print(summary[-1], flush=True)
    (out / "summary.txt").write_text("\n".join(summary) + "\n")
    try:
        from benchmarks.engine_parity import _usage_events

        events = _usage_events(Path(os.environ["CICADA_HOME"]))
        print(f"{len(events)} calls, ${sum(e.get('cost_usd') or 0.0 for e in events):.3f} on the key")
    except Exception as exc:  # noqa: BLE001 - the cost line is a convenience
        print(f"(no cost line: {type(exc).__name__})")
    return 1 if any("false joins 0 " not in s for s in summary) else 0


if __name__ == "__main__":
    raise SystemExit(main())
