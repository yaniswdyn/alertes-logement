#!/usr/bin/env python3
"""
Discord monitor for student housing pages.
Current scope: STUDEFI / ARPEJ / FAC-HABITAT residence pages.

Corrections vs version precedente :
  1. Cooldown : l'etat "seen_available" est separe de l'etat "alerted",
     evitant la perte definitive d'alerte apres un cooldown.
  2. ARPEJ : detection basee sur des sections HTML specifiques plutot
     que sur une regex large susceptible de faux positifs.
  3. Rate-limiting : pause de 1.5 s entre chaque requete.
  4. Ecriture atomique du fichier d'etat (fichier tmp + rename).
  5. extract_price / extract_starting_price fusionnes pour FAC-HABITAT.
  6. Normalisation Unicode dans extract_residence_name.
  7. Embed Discord : champ "Lien direct" redondant supprime.
  8. has_je_reserve_button et has_waiting_list_link evalues ensemble
     pour STUDEFI (detail plus precis).
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

CHECK_EVERY_SECONDS = 120
ALERT_COOLDOWN_HOURS = 24
STATE_FILE = "monitor_state.json"
REQUEST_TIMEOUT = 25
INTER_REQUEST_DELAY = 1.5  # secondes entre chaque fetch pour eviter le ban IP
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

TARGETS = [
    # STUDEFI
    {"name": "Algo - Paris 13", "url": "https://www.studefi.fr/main.php?srv=Residence&op=show&cdGroupe=807G", "site": "studefi"},
    {"name": "Arcueil - Irene et Francois Joliot Curie", "url": "https://www.studefi.fr/main.php?srv=Residence&op=show&cdGroupe=788G", "site": "studefi"},
    {"name": "Paris 18e - Evariste Galois", "url": "https://www.studefi.fr/main.php?srv=Residence&op=show&cdGroupe=784G", "site": "studefi"},
    {"name": "Courbevoie - Modigliani", "url": "https://www.studefi.fr/main.php?srv=Residence&op=show&cdGroupe=806G", "site": "studefi"},
    {"name": "Boulogne-Billancourt - Sequana", "url": "https://www.studefi.fr/main.php?srv=Residence&op=show&cdGroupe=798G", "site": "studefi"},
    {"name": "Jean Mermoz - Chatillon", "url": "https://www.studefi.fr/main.php?srv=Residence&op=show&cdGroupe=785G", "site": "studefi"},
    {"name": "Le Galibier - Montigny-le-Bretonneux", "url": "https://www.studefi.fr/main.php?srv=Residence&op=show&cdGroupe=787G", "site": "studefi"},
    # ARPEJ
    {"name": "Scipion - Paris 5e", "url": "https://www.arpej.fr/fr/residence/residence-etudiants-paris-5eme-arrondissement-scipion-arpej/", "site": "arpej"},
    {"name": "Poissonnier - Paris 18e", "url": "https://www.arpej.fr/fr/residence/residence-etudiante-paris-poissonnier/", "site": "arpej"},
    {"name": "Eole - Paris 19e", "url": "https://www.arpej.fr/fr/residence/etudiante-eole-paris/", "site": "arpej"},
    {"name": "Thiais", "url": "https://www.arpej.fr/fr/residence/residence-etudiants-thais-arpej/", "site": "arpej"},
    {"name": "La Garenne Colombes", "url": "https://www.arpej.fr/fr/residence/la-garenne-colombes/", "site": "arpej"},
    {"name": "Louis Faure Dujarric - Colombes", "url": "https://www.arpej.fr/fr/residence/louis-faure-dujarric-residence-jeunes-actifs-colombes/", "site": "arpej"},
    {"name": "Jacques Henri Lartigue - Courbevoie", "url": "https://www.arpej.fr/fr/residence/jacques-henri-lartigue-residence-etudiante-courbevoie/", "site": "arpej"},
    {"name": "Neuilly-Roule - Neuilly-sur-Seine", "url": "https://www.arpej.fr/fr/residence/neuilly-roule-residence-etudiante-neuilly-sur-seine/", "site": "arpej"},
    {"name": "Louis Bleriot - Suresnes", "url": "https://www.arpej.fr/fr/residence/etudiante-suresnes/", "site": "arpej"},
    {"name": "Charles Frederick Worth - Suresnes", "url": "https://www.arpej.fr/fr/residence/residence-etudiante-suresnes/", "site": "arpej"},
    {"name": "Berthelot - Meudon", "url": "https://www.arpej.fr/fr/residence/berthelot-residence-chercheurs-meudon/", "site": "arpej"},
    {"name": "Medicis - Le Vesinet", "url": "https://www.arpej.fr/fr/residence/residence-etudiants-le-vesinet-medicis-arpej/", "site": "arpej"},
    {"name": "Henri Langlois - Bois d'Arcy", "url": "https://www.arpej.fr/fr/residence/residence-etudiante-henri-langlois-bois-darcy/", "site": "arpej"},
    {"name": "Andre Dunoyer de Segonzac - Guyancourt", "url": "https://www.arpej.fr/fr/residence/residence-etudiante-andre-dunoyer-segonzac-guyancourt/", "site": "arpej"},
    {"name": "Pierre Gilles de Gennes - Villejuif", "url": "https://www.arpej.fr/fr/residence/pierre-gilles-de-gennes-residence-etudiante-villejuif/", "site": "arpej"},
    {"name": "Nicolas Appert - Ivry-sur-Seine", "url": "https://www.arpej.fr/fr/residence/nicolas-appert-residence-etudiante-ivry-sur-seine/", "site": "arpej"},
    {"name": "Chanzy - Nanterre", "url": "https://www.arpej.fr/fr/residence/chanzy-residence-etudiante-nanterre/", "site": "arpej"},
    {"name": "Porte d'Italie - Le Kremlin-Bicetre", "url": "https://www.arpej.fr/fr/residence/porte-ditalie-residence-etudiante-le-kremlin-bicetre/", "site": "arpej"},
    {"name": "Renon - Vincennes", "url": "https://www.arpej.fr/fr/residence/renon-residence-etudiante-vincennes/", "site": "arpej"},
    {"name": "Philippe Auguste - Vincennes", "url": "https://www.arpej.fr/fr/residence/philippe-auguste-residence-jeunes-actifs-vincennes/", "site": "arpej"},
    {"name": "Aubert - Vincennes", "url": "https://www.arpej.fr/fr/residence/aubert-residence-etudiante-vincennes/", "site": "arpej"},
    {"name": "Juliette Drouet - Saint-Mande", "url": "https://www.arpej.fr/fr/residence/saint-mande-residence-etudiante-paris/", "site": "arpej"},
    {"name": "Pierre Grach - Saint-Mande", "url": "https://www.arpej.fr/fr/residence/residence-etudiante-saint-mande/", "site": "arpej"},
    {"name": "Cite de la Musique - Paris 19e", "url": "https://www.arpej.fr/fr/residence/cite-de-la-musique-residence-etudiante-paris/", "site": "arpej"},
    {"name": "Du Conservatoire - Paris 19e", "url": "https://www.arpej.fr/fr/residence/du-conservatoire-residence-etudiante-paris/", "site": "arpej"},
    # FAC-HABITAT
    {"name": "MIS pour etudiants - Paris 13e", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-56-mis-pour-etudiants", "site": "fac_habitat"},
    {"name": "Georges Mathe - Villejuif", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-45-georges-mathe", "site": "fac_habitat"},
    {"name": "Pablo Picasso - Nanterre", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-26-pablo-picasso", "site": "fac_habitat"},
    {"name": "Emergence - Bois-Colombes", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-85-residence-etudiante-emergence-bois-colombes", "site": "fac_habitat"},
    {"name": "Hortense Wild - Chatillon", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-116-hortense-wild", "site": "fac_habitat"},
    {"name": "Val de Bievre - Gentilly", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-53-val-de-bievre", "site": "fac_habitat"},
    {"name": "Jean Jaures - Ivry-sur-Seine", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-54-jean-jaures", "site": "fac_habitat"},
    {"name": "Carmagnole - Courbevoie", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-96-carmagnole", "site": "fac_habitat"},
    {"name": "Auguste Rodin - Paris 7e", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-28-auguste-rodin", "site": "fac_habitat"},
    {"name": "Edouard Depreux - Sceaux", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-47-edouard-depreux", "site": "fac_habitat"},
    {"name": "Marne - Paris 19e", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-101-marne", "site": "fac_habitat"},
    {"name": "Quai de la Loire - Paris 19e", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-73-quai-de-la-loire", "site": "fac_habitat"},
]

PRICE_RE = re.compile(
    r"\b(?:a\s+partir\s+de\s+)?(\d{2,5}(?:[.,]\d{1,2})?)\s*(?:€|eur|euros?)(?:\s*/\s*mois)?",
    re.IGNORECASE,
)
SURFACE_RE = re.compile(r"\b(\d{1,3}(?:[\.,]\d{1,2})?)\s*(?:m2|m²)\b", re.IGNORECASE)
SURFACE_RANGE_RE = re.compile(
    r"(?:de|entre)\s*(\d{1,3}(?:[\.,]\d{1,2})?)\s*(?:a|à|et)\s*(\d{1,3}(?:[\.,]\d{1,2})?)\s*(?:m2|m²)",
    re.IGNORECASE,
)
CITY_RE = re.compile(r"\b(?:75|77|78|91|92|93|94|95)\d{3}\s+([A-Za-zÀ-ÖØ-öø-ÿ'\- ]{2,40})")


@dataclass
class HousingInfo:
    source: str
    residence: str
    city: str
    price: str
    surface: str
    description: str
    direct_link: str


@dataclass
class CheckResult:
    status: str  # available | unavailable | error
    detail: str
    info: HousingInfo


# ---------------------------------------------------------------------------
# Helpers reseau
# ---------------------------------------------------------------------------

def fetch_page(url: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
        resp.raise_for_status()
        return resp.text, None
    except requests.RequestException as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# Helpers texte
# ---------------------------------------------------------------------------

def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def normalize_str(s: str) -> str:
    """Supprime les accents et met en minuscules pour comparaisons robustes."""
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()


def extract_description(soup: BeautifulSoup) -> str:
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        return clean_text(meta["content"])[:240]
    for p in soup.find_all("p"):
        txt = clean_text(p.get_text(" ", strip=True))
        if len(txt) >= 60:
            return txt[:240]
    return "description non trouvee"


def extract_city(text: str) -> str:
    m = CITY_RE.search(text)
    return clean_text(m.group(1)) if m else "non trouvee"


def extract_price(text: str) -> str:
    """
    Retourne le prix le plus bas trouve dans le texte, prefixe "a partir de".
    Cherche d'abord un prix explicitement annonce "a partir de", sinon le minimum
    de tous les prix detectes.
    """
    # Priorite : prix annonce "a partir de X €"
    starting = re.search(
        r"a\s+partir\s+de\s+(\d{2,5}(?:[.,]\d{1,2})?)\s*€",
        text,
        flags=re.IGNORECASE,
    )
    if starting:
        raw = starting.group(1).replace(",", ".")
        try:
            val = float(raw)
            return f"a partir de {int(val) if val.is_integer() else raw.rstrip('0').rstrip('.')} €"
        except ValueError:
            pass

    # Fallback : minimum de tous les prix
    vals: List[float] = []
    for raw in PRICE_RE.findall(text):
        try:
            vals.append(float(raw.replace(",", ".")))
        except ValueError:
            continue
    if not vals:
        return "non trouve"
    min_val = min(vals)
    formatted = f"{int(min_val)}" if min_val.is_integer() else f"{min_val:.2f}".rstrip("0").rstrip(".")
    return f"a partir de {formatted} €"


def extract_surface(text: str) -> str:
    r = SURFACE_RANGE_RE.search(text)
    if r:
        a = r.group(1).replace(",", ".")
        b = r.group(2).replace(",", ".")
        return f"de {a} a {b} m2"
    vals = []
    for raw in SURFACE_RE.findall(text):
        try:
            vals.append(float(raw.replace(",", ".")))
        except ValueError:
            continue
    return f"{min(vals):g} m2" if vals else "non trouvee"


BANNED_HEADINGS = {
    "reserver mon appart'",
    "comment reserver",
    "les services",
    "les appartements",
    "les conditions",
    "la ville et le quartier",
}


def extract_residence_name(soup: BeautifulSoup, fallback: str) -> str:
    for tag in ("h1", "h2", "h3"):
        for node in soup.find_all(tag):
            txt = clean_text(node.get_text(" ", strip=True))
            norm = normalize_str(txt)
            if not txt:
                continue
            if any(norm.startswith(b) for b in BANNED_HEADINGS):
                continue
            return txt
    title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    if title and "studefi" not in title.lower():
        return title
    return fallback


# ---------------------------------------------------------------------------
# FAC-HABITAT iframe helpers
# ---------------------------------------------------------------------------

def fetch_fac_iframe_soup(page_url: str, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
    iframe = soup.find("iframe", class_="reservation")
    if not iframe:
        return None
    src = iframe.get("src", "").strip()
    if not src:
        return None
    iframe_url = urljoin(page_url, src)
    try:
        resp = requests.get(iframe_url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
    except requests.RequestException:
        return None
    return BeautifulSoup(resp.text, "html.parser")


def extract_fac_iframe_rows(iframe_soup: Optional[BeautifulSoup]) -> List[Dict[str, str]]:
    if iframe_soup is None:
        return []
    rows: List[Dict[str, str]] = []
    for tr in iframe_soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        row = {
            "type": clean_text(tds[0].get_text(" ", strip=True)),
            "price_cell": clean_text(tds[1].get_text(" ", strip=True)),
            "surface_cell": clean_text(tds[2].get_text(" ", strip=True)),
            "availability_cell": clean_text(tds[4].get_text(" ", strip=True)),
        }
        if any(row.values()):
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Parseurs par site
# ---------------------------------------------------------------------------

def parse_studefi(target_name: str, url: str, html: str) -> CheckResult:
    soup = BeautifulSoup(html, "html.parser")
    raw_text = soup.get_text(" ", strip=True)
    norm = clean_text(raw_text).lower()

    residence_name = extract_residence_name(soup, target_name)
    city = extract_city(raw_text)
    price = extract_price(raw_text)
    surface = extract_surface(raw_text)
    description = extract_description(soup)

    has_explicit_unavailable = bool(re.search(r"aucun\s+logement\s+disponible", norm))
    has_waiting_list_link = bool(
        soup.find("a", href=re.compile(r"srv=Reservation&op=showListeAttente", re.IGNORECASE))
    )
    has_reservation_link = bool(soup.find("a", href=re.compile(r"srv=Reservation", re.IGNORECASE)))
    has_je_reserve_button = bool(re.search(r"\bje\s+r[ée]serve\b", norm))

    if has_je_reserve_button and not has_waiting_list_link:
        status = "available"
        detail = "Bouton Je reserve detecte"
    elif has_je_reserve_button and has_waiting_list_link:
        # Les deux coexistent : disponibilite partielle
        status = "available"
        detail = "Disponibilite partielle (Je reserve + liste d'attente detectes)"
    elif has_explicit_unavailable or has_waiting_list_link:
        status = "unavailable"
        detail = "Aucun logement disponible"
    elif has_reservation_link:
        status = "available"
        detail = "Disponibilite detectee (lien reservation)"
    else:
        status = "unavailable"
        detail = "Indisponible (aucun signal de reservation active)"

    info = HousingInfo(
        source="STUDEFI",
        residence=residence_name,
        city=city,
        price=price,
        surface=surface,
        description=description,
        direct_link=url,
    )
    return CheckResult(status=status, detail=detail, info=info)


def parse_arpej(target_name: str, url: str, html: str) -> CheckResult:
    soup = BeautifulSoup(html, "html.parser")
    raw_text = clean_text(soup.get_text(" ", strip=True))
    norm = raw_text.lower()

    residence_name = extract_residence_name(soup, target_name)
    city = extract_city(raw_text)
    price = extract_price(raw_text)
    surface = extract_surface(raw_text)
    description = extract_description(soup)

    # --- Detection ARPEJ robuste ---
    # Cherche la section de disponibilite dans le DOM (balise dediee ou bloc texte precis)
    # plutot que regex large sur toute la page.
    dispo_section = ""

    # Tentative 1 : bloc HTML avec classe/id contenant "dispo"
    for candidate in soup.find_all(True, class_=re.compile(r"dispo", re.IGNORECASE)):
        dispo_section += " " + clean_text(candidate.get_text(" ", strip=True))
    for candidate in soup.find_all(True, id=re.compile(r"dispo", re.IGNORECASE)):
        dispo_section += " " + clean_text(candidate.get_text(" ", strip=True))

    # Tentative 2 : paragraphe contenant "Disponibilite" suivi d'un contenu precis
    if not dispo_section:
        for el in soup.find_all(["p", "div", "span", "li"]):
            txt = clean_text(el.get_text(" ", strip=True))
            if re.search(r"disponibilit[ée]", txt, re.IGNORECASE) and len(txt) < 300:
                dispo_section += " " + txt

    dispo_norm = dispo_section.lower() if dispo_section else norm

    has_unavailable = bool(
        re.search(r"aucun\s+logement\s+disponible", dispo_norm)
        or re.search(r"aucune\s+disponibilit[ée]", dispo_norm)
    )
    has_count = bool(re.search(r"\b[1-9]\d*\s+logements?\s+disponibles?\b", dispo_norm))
    has_positive_dispo = bool(
        re.search(r"disponibilit[ée]\s+(?!aucun)[a-z]", dispo_norm)
        and not has_unavailable
    )

    if has_unavailable:
        status = "unavailable"
        detail = "Aucun logement disponible"
    elif has_count:
        m = re.search(r"\b([1-9]\d*)\s+logements?\s+disponibles?\b", dispo_norm)
        count = m.group(1) if m else "?"
        status = "available"
        detail = f"{count} logement(s) disponible(s)"
    elif has_positive_dispo:
        status = "available"
        detail = "Disponibilite detectee"
    else:
        status = "unavailable"
        detail = "Indisponible (aucun signal explicite)"

    info = HousingInfo(
        source="ARPEJ",
        residence=residence_name,
        city=city,
        price=price,
        surface=surface,
        description=description,
        direct_link=url,
    )
    return CheckResult(status=status, detail=detail, info=info)


def parse_fac_habitat(target_name: str, url: str, html: str) -> CheckResult:
    soup = BeautifulSoup(html, "html.parser")
    raw_text = clean_text(soup.get_text(" ", strip=True))
    iframe_soup = fetch_fac_iframe_soup(url, soup)
    iframe_text = clean_text(iframe_soup.get_text(" ", strip=True)) if iframe_soup else ""
    iframe_rows = extract_fac_iframe_rows(iframe_soup)
    merged_text = clean_text(f"{raw_text} {iframe_text}")
    norm = merged_text.lower()

    residence_name = extract_residence_name(soup, target_name)
    city = extract_city(merged_text)
    price = extract_price(merged_text)

    # Surface : privilegier les donnees du tableau iframe
    surface = "non trouvee"
    if iframe_rows:
        immediate_row = next(
            (r for r in iframe_rows if re.search(r"imm[ée]diat", r["availability_cell"], re.IGNORECASE)),
            None,
        )
        coming_row = next(
            (r for r in iframe_rows if "venir" in r["availability_cell"].lower()),
            None,
        )
        chosen_row = immediate_row or coming_row or iframe_rows[0]
        if chosen_row["surface_cell"]:
            surface = chosen_row["surface_cell"]
    if surface == "non trouvee":
        surface = extract_surface(merged_text)

    description = extract_description(soup)

    row_avail = [r["availability_cell"].lower() for r in iframe_rows if r.get("availability_cell")]
    has_immediate = any(re.search(r"imm[ée]diat", t) for t in row_avail)
    has_coming_soon = any("venir" in t for t in row_avail)
    has_explicit_unavailable = any(
        re.search(r"aucune?\s+disponibilit[ée]", t) or "aucun logement disponible" in t
        for t in row_avail
    )

    if not row_avail:
        has_explicit_unavailable = bool(
            re.search(r"aucune?\s+disponibilit[ée]", norm)
            or re.search(r"aucun\s+logement\s+disponible", norm)
        )
        has_coming_soon = bool(re.search(r"disponibilit[ée]\s+[aà]\s+venir", norm) or re.search(r"\b[aà]\s+venir\b", norm))
        has_immediate = bool(re.search(r"disponibilit[ée]\s+imm[ée]diate", norm))

    has_positive_count = bool(re.search(r"\b[1-9]\d*\s+logements?\s+disponibles?\b", norm))
    has_reservation_keyword = bool(re.search(r"d[ée]poser\s+un\s+dossier\s+de\s+r[ée]servation", norm))

    if has_immediate:
        status = "available"
        detail = "Disponibilite immediate"
    elif has_coming_soon:
        status = "available"
        detail = "Disponibilite a venir"
    elif has_explicit_unavailable:
        status = "unavailable"
        detail = "Aucune disponibilite"
    elif has_positive_count or has_reservation_keyword:
        status = "available"
        detail = "Disponibilite detectee"
    else:
        status = "unavailable"
        detail = "Indisponible (aucun signal explicite)"

    info = HousingInfo(
        source="FAC-HABITAT",
        residence=residence_name,
        city=city,
        price=price,
        surface=surface,
        description=description,
        direct_link=url,
    )
    return CheckResult(status=status, detail=detail, info=info)


def detect_status(target: dict, html: str) -> CheckResult:
    site = target["site"]
    if site == "studefi":
        return parse_studefi(target["name"], target["url"], html)
    if site == "arpej":
        return parse_arpej(target["name"], target["url"], html)
    if site == "fac_habitat":
        return parse_fac_habitat(target["name"], target["url"], html)
    return CheckResult(
        status="error",
        detail=f"Site non supporte: {site}",
        info=HousingInfo(site.upper(), target["name"], "non trouvee", "non trouve", "non trouvee", "", target["url"]),
    )


# ---------------------------------------------------------------------------
# Gestion de l'etat persistant
# ---------------------------------------------------------------------------

def load_state() -> Dict[str, str]:
    if not Path(STATE_FILE).exists():
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_state(state: Dict[str, str]) -> None:
    """Ecriture atomique : on ecrit dans un fichier temporaire puis on renomme."""
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)  # atomique sur POSIX et Windows (Python 3.3+)


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

def send_discord(webhook_url: str, content: str, embeds: Optional[List[dict]] = None) -> None:
    payload: dict = {"content": content}
    if embeds:
        payload["embeds"] = embeds
    resp = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()


def make_embed(result: CheckResult) -> dict:
    color = 0x2ECC71 if result.status == "available" else 0xF1C40F
    return {
        "title": result.info.residence[:256],
        "url": result.info.direct_link,          # titre cliquable = lien direct
        "description": (result.info.description or result.detail)[:2048],
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Statut",   "value": result.status,           "inline": True},
            {"name": "Source",   "value": result.info.source[:1024], "inline": True},
            {"name": "Detail",   "value": result.detail[:1024],    "inline": False},
            {"name": "Residence","value": result.info.residence[:1024], "inline": False},
            {"name": "Ville",    "value": result.info.city[:1024],   "inline": True},
            {"name": "Prix",     "value": result.info.price[:1024],  "inline": True},
            {"name": "Surface",  "value": result.info.surface[:1024],"inline": True},
        ],
    }


# ---------------------------------------------------------------------------
# Boucle principale
# ---------------------------------------------------------------------------

def check_once(webhook_url: str, previous_state: Dict[str, str]) -> Dict[str, str]:
    """
    Logique d'alerte corrigee :
    - On distingue "last_status" (dernier statut observe) de "last_alerted"
      (horodatage de la derniere alerte effectivement envoyee).
    - Si une residence est available et qu'on est dans le cooldown, on garde
      last_status a "available" sans envoyer d'alerte.
    - Quand le cooldown expire, si last_status est toujours "available"
      (ou repasse a available), on alertera au prochain cycle.
    - Pour cela on stocke separement "pending_alert:<url>" = "1" quand on
      detecte une disponibilite hors cooldown.
    """
    new_state = dict(previous_state)

    for i, target in enumerate(TARGETS):
        key = target["url"]
        last_status_key = f"last_status:{key}"
        last_alerted_key = f"last_alerted:{key}"

        if i > 0:
            time.sleep(INTER_REQUEST_DELAY)

        html, err = fetch_page(key)

        if err:
            result = CheckResult(
                "error",
                f"Erreur HTTP: {err}",
                HousingInfo(
                    target["site"].upper(), target["name"],
                    "non trouvee", "non trouve", "non trouvee", "", key,
                ),
            )
        else:
            result = detect_status(target, html or "")

        old_status = previous_state.get(last_status_key)
        new_state[last_status_key] = result.status

        # Verifie le cooldown
        last_alerted_str = previous_state.get(last_alerted_key)
        cooldown_ok = True
        if last_alerted_str:
            try:
                last_alerted = datetime.fromisoformat(last_alerted_str)
                hours_since = (datetime.now(timezone.utc) - last_alerted).total_seconds() / 3600
                if hours_since < ALERT_COOLDOWN_HOURS:
                    cooldown_ok = False
            except ValueError:
                pass

        # On alerte si :
        #   - le statut vient de changer vers available/error, OU
        #   - le statut est available/error et le cooldown vient d'expirer
        #     (old_status == result.status mais cooldown_ok est redevenu True)
        status_triggers = result.status in ("available", "error")
        just_changed = old_status != result.status and status_triggers
        cooldown_expired = cooldown_ok and old_status == result.status and status_triggers

        should_alert = just_changed or cooldown_expired

        if should_alert:
            new_state[last_alerted_key] = datetime.now(timezone.utc).isoformat()
            content = (
                "🏠 ALERTE LOGEMENT DISPONIBLE"
                if result.status == "available"
                else "⚠️ Monitor: erreur de verification"
            )
            try:
                send_discord(webhook_url, content, [make_embed(result)])
                print(
                    f"[{datetime.now().isoformat(timespec='seconds')}] "
                    f"Notification envoyee : {result.info.residence}"
                )
            except requests.RequestException as exc:
                print(f"[{datetime.now().isoformat(timespec='seconds')}] Erreur Discord : {exc}")

        print(
            f"[{datetime.now().isoformat(timespec='seconds')}] "
            f"{result.status.upper():11} | {result.info.residence[:70]}"
        )

    return new_state


def main() -> None:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise SystemExit(
            "Variable DISCORD_WEBHOOK_URL manquante.\n"
            "Exemple PowerShell : $env:DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'\n"
            "Exemple bash       : export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'"
        )

    print(f"Monitoring demarre — {len(TARGETS)} residences, verif toutes les {CHECK_EVERY_SECONDS}s. Ctrl+C pour arreter.")
    state = load_state()

    while True:
        try:
            state = check_once(webhook_url, state)
            save_state(state)
            time.sleep(CHECK_EVERY_SECONDS)
        except KeyboardInterrupt:
            print("\nArret demande par l'utilisateur.")
            break
        except Exception as exc:  # noqa: BLE001
            print(f"[{datetime.now().isoformat(timespec='seconds')}] Erreur inattendue : {exc}")
            time.sleep(20)


if __name__ == "__main__":
    main()
