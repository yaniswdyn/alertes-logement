#!/usr/bin/env python3
"""
Discord monitor for student housing pages.
Current scope: STUDEFI residence pages provided by the user.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

CHECK_EVERY_SECONDS = 120
ALERT_COOLDOWN_HOURS = 24
STATE_FILE = "monitor_state.json"
REQUEST_TIMEOUT = 25
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Residence-by-residence monitoring (STUDEFI + ARPEJ)
TARGETS = [
    {"name": "Algo - Paris 13", "url": "https://www.studefi.fr/main.php?srv=Residence&op=show&cdGroupe=807G", "site": "studefi"},
    {"name": "Arcueil - Irene et Francois Joliot Curie", "url": "https://www.studefi.fr/main.php?srv=Residence&op=show&cdGroupe=788G", "site": "studefi"},
    {"name": "Paris 18e - Evariste Galois", "url": "https://www.studefi.fr/main.php?srv=Residence&op=show&cdGroupe=784G", "site": "studefi"},
    {"name": "Pontoise - Francois Rabelais", "url": "https://www.studefi.fr/main.php?srv=Residence&op=show&cdGroupe=786G", "site": "studefi"},
    {"name": "Les Fils d'Icare - Velizy", "url": "https://www.studefi.fr/main.php?srv=Residence&op=show&cdGroupe=963G", "site": "studefi"},
    {"name": "Courbevoie - Modigliani", "url": "https://www.studefi.fr/main.php?srv=Residence&op=show&cdGroupe=806G", "site": "studefi"},
    {"name": "Boulogne-Billancourt - Sequana", "url": "https://www.studefi.fr/main.php?srv=Residence&op=show&cdGroupe=798G", "site": "studefi"},
    {"name": "Orsay - Pierre-Gilles de Gennes", "url": "https://www.studefi.fr/main.php?srv=Residence&op=show&cdGroupe=791G", "site": "studefi"},
    {"name": "Scipion", "url": "https://www.arpej.fr/fr/residence/residence-etudiants-paris-5eme-arrondissement-scipion-arpej/", "site": "arpej"},
    {"name": "Poissonnier", "url": "https://www.arpej.fr/fr/residence/residence-etudiante-paris-poissonnier/", "site": "arpej"},
    {"name": "Thiais", "url": "https://www.arpej.fr/fr/residence/residence-etudiants-thais-arpej/", "site": "arpej"},
    {"name": "La Garenne Colombes", "url": "https://www.arpej.fr/fr/residence/la-garenne-colombes/", "site": "arpej"},
    {"name": "Eole Paris", "url": "https://www.arpej.fr/fr/residence/etudiante-eole-paris/", "site": "arpej"},
    {"name": "Millenium Etudiants Velizy", "url": "https://www.arpej.fr/fr/residence/millenium-residence-etudiante-velizy-villacoublay/", "site": "arpej"},
    {"name": "Louis Faure Dujarric Colombes", "url": "https://www.arpej.fr/fr/residence/louis-faure-dujarric-residence-jeunes-actifs-colombes/", "site": "arpej"},
    {"name": "Jacques Henri Lartigue Courbevoie", "url": "https://www.arpej.fr/fr/residence/jacques-henri-lartigue-residence-etudiante-courbevoie/", "site": "arpej"},
    {"name": "Victor Guerreau Velizy", "url": "https://www.arpej.fr/fr/residence/victor-guerreau-residence-etudiante-velizy-villacoublay/", "site": "arpej"},
    {"name": "Millenium Jeunes Actifs Velizy", "url": "https://www.arpej.fr/fr/residence/millenium-residence-jeunes-actifs-velizy-villacoublay/", "site": "arpej"},
    {"name": "Campuseo Etudiants Velizy", "url": "https://www.arpej.fr/fr/residence/campuseo-partie-pour-etudiants-residence-etudiante-velizy-villacoublay/", "site": "arpej"},
    {"name": "Pierre Gilles de Gennes Villejuif", "url": "https://www.arpej.fr/fr/residence/pierre-gilles-de-gennes-residence-etudiante-villejuif/", "site": "arpej"},
    {"name": "Nicolas Appert Ivry-sur-Seine", "url": "https://www.arpej.fr/fr/residence/nicolas-appert-residence-etudiante-ivry-sur-seine/", "site": "arpej"},
    {"name": "Chanzy Nanterre", "url": "https://www.arpej.fr/fr/residence/chanzy-residence-etudiante-nanterre/", "site": "arpej"},
    {"name": "Porte d'Italie Le Kremlin-Bicetre", "url": "https://www.arpej.fr/fr/residence/porte-ditalie-residence-etudiante-le-kremlin-bicetre/", "site": "arpej"},
    {"name": "Renon Vincennes", "url": "https://www.arpej.fr/fr/residence/renon-residence-etudiante-vincennes/", "site": "arpej"},
    {"name": "Philippe Auguste Vincennes", "url": "https://www.arpej.fr/fr/residence/philippe-auguste-residence-jeunes-actifs-vincennes/", "site": "arpej"},
    {"name": "MIS pour etudiants - Paris 13e", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-56-mis-pour-etudiants", "site": "fac_habitat"},
    {"name": "Georges Mathe - Villejuif", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-45-georges-mathe", "site": "fac_habitat"},
    {"name": "Leo Ferre - Orly", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-100-leo-ferre", "site": "fac_habitat"},
    {"name": "Pablo Picasso - Nanterre", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-26-pablo-picasso", "site": "fac_habitat"},
    {"name": "Gondoles - Choisy-le-Roi", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-98-gondoles", "site": "fac_habitat"},
    {"name": "Emergence - Bois-Colombes", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-85-residence-etudiante-emergence-bois-colombes", "site": "fac_habitat"},
    {"name": "Hortense Wild - Chatillon", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-116-hortense-wild", "site": "fac_habitat"},
    {"name": "Val de Bievre - Gentilly", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-53-val-de-bievre", "site": "fac_habitat"},
    {"name": "Jean Jaures - Ivry-sur-Seine", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-54-jean-jaures", "site": "fac_habitat"},
    {"name": "Carmagnole - Courbevoie", "url": "https://www.fac-habitat.com/fr/residences-etudiantes/id-96-carmagnole", "site": "fac_habitat"},
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


def fetch_page(url: str) -> Tuple[str | None, str | None]:
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


def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


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
    if m:
        return clean_text(m.group(1))
    return "non trouvee"


def extract_price(text: str) -> str:
    vals: List[float] = []
    for raw in PRICE_RE.findall(text):
        try:
            vals.append(float(raw.replace(",", ".")))
        except ValueError:
            continue
    if not vals:
        return "non trouve"
    min_val = min(vals)
    if min_val.is_integer():
        return f"a partir de {int(min_val)} €"
    # Keep two decimals max and trim trailing zeros.
    formatted = f"{min_val:.2f}".rstrip("0").rstrip(".")
    return f"a partir de {formatted} €"


def extract_starting_price(text: str) -> str:
    m = re.search(r"a\s+partir\s+de\s+(\d{2,5}(?:[.,]\d{1,2})?)\s*€", text, flags=re.IGNORECASE)
    if not m:
        return "non trouve"
    raw = m.group(1).replace(",", ".")
    try:
        val = float(raw)
    except ValueError:
        return "non trouve"
    if val.is_integer():
        return f"a partir de {int(val)} €"
    return f"a partir de {raw.rstrip('0').rstrip('.')} €"


def fetch_fac_iframe_soup(page_url: str, soup: BeautifulSoup) -> BeautifulSoup | None:
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


def extract_fac_iframe_rows(iframe_soup: BeautifulSoup | None) -> List[Dict[str, str]]:
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
        if row["type"] or row["price_cell"] or row["surface_cell"] or row["availability_cell"]:
            rows.append(row)
    return rows


def extract_surface(text: str) -> str:
    # Prefer explicit ranges: "de 17.9 a 33.6 m2" / "entre 17.9 et 33.6 m2"
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
    if not vals:
        return "non trouvee"
    return f"{min(vals):g} m2"


def extract_residence_name(soup: BeautifulSoup, fallback: str) -> str:
    # STUDEFI residence page: h1 can be generic ("Reserver mon appart'").
    banned = {
        "reserver mon appart'",
        "réserver mon appart'",
        "comment reserver",
        "comment réserver",
    }
    for tag in ("h1", "h2", "h3"):
        for node in soup.find_all(tag):
            txt = clean_text(node.get_text(" ", strip=True))
            low = txt.lower()
            if not txt:
                continue
            if low in banned:
                continue
            if low.startswith("les services") or low.startswith("les appartements"):
                continue
            if low.startswith("les conditions") or low.startswith("la ville et le quartier"):
                continue
            return txt

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    title = clean_text(title)
    if title and "studefi" not in title.lower():
        return title

    return fallback


def parse_studefi(target_name: str, url: str, html: str) -> CheckResult:
    soup = BeautifulSoup(html, "html.parser")
    raw_text = soup.get_text(" ", strip=True)
    norm = clean_text(raw_text).lower()

    residence_name = extract_residence_name(soup, target_name)
    city = extract_city(raw_text)
    price = extract_price(raw_text)
    surface = extract_surface(raw_text)
    description = extract_description(soup)

    # Reliable STUDEFI signals.
    has_explicit_unavailable = bool(re.search(r"aucun\s+logement\s+disponible", norm, flags=re.IGNORECASE))
    has_waiting_list_link = bool(
        soup.find("a", href=re.compile(r"srv=Reservation&op=showListeAttente", re.IGNORECASE))
    )
    has_reservation_link = bool(soup.find("a", href=re.compile(r"srv=Reservation", re.IGNORECASE)))
    has_je_reserve_button = bool(re.search(r"\bje\s+r[ée]serve\b", norm, flags=re.IGNORECASE))

    # User rule: if "Je reserve" button is present, treat as available.
    if has_je_reserve_button:
        status = "available"
        detail = "Bouton Je reserve detecte"
    elif has_explicit_unavailable or has_waiting_list_link:
        status = "unavailable"
        detail = "Aucun logement disponible"
    elif has_reservation_link:
        status = "available"
        detail = "Disponibilite detectee"
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

    # ARPEJ indicator used by user: "Disponibilite ...".
    if re.search(r"disponibilit[ée]\s+aucun\s+logement\s+disponible", norm, flags=re.IGNORECASE) or re.search(
        r"\baucun\s+logement\s+disponible\b", norm, flags=re.IGNORECASE
    ):
        status = "unavailable"
        detail = "Aucun logement disponible"
    else:
        dispo_segment = re.search(r"disponibilit[ée]\s+(.{0,80})", raw_text, flags=re.IGNORECASE)
        if dispo_segment and "aucun" not in dispo_segment.group(1).lower():
            status = "available"
            detail = f"Disponibilite detectee: {dispo_segment.group(1).strip()}"
        elif re.search(r"\b[1-9]\d*\s+logements?\s+disponibles?\b", norm, flags=re.IGNORECASE):
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
    price = extract_starting_price(merged_text)
    if price == "non trouve":
        price = extract_price(merged_text)
    surface = "non trouvee"
    if iframe_rows:
        immediate_row = next(
            (r for r in iframe_rows if "immediat" in r["availability_cell"].lower() or "immédiat" in r["availability_cell"].lower()),
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

    row_availability_texts = [r["availability_cell"].lower() for r in iframe_rows if r.get("availability_cell")]
    has_immediate = any("immediat" in txt or "immédiat" in txt for txt in row_availability_texts)
    has_coming_soon = any("venir" in txt for txt in row_availability_texts)
    has_explicit_unavailable = any(
        ("aucune disponibilite" in txt)
        or ("aucune disponibilité" in txt)
        or ("aucun logement disponible" in txt)
        for txt in row_availability_texts
    )

    # Fallback when iframe table is not readable.
    if not row_availability_texts:
        has_explicit_unavailable = bool(
            re.search(r"aucune\s+disponibilit[ée]", norm, flags=re.IGNORECASE)
            or re.search(r"aucun\s+logement\s+disponible", norm, flags=re.IGNORECASE)
        )
        has_coming_soon = bool(
            re.search(r"disponibilit[ée]\s+[aà]\s+venir", norm, flags=re.IGNORECASE)
            or re.search(r"\b[aà]\s+venir\b", norm, flags=re.IGNORECASE)
        )
        has_immediate = bool(re.search(r"disponibilit[ée]\s+imm[ée]diate", norm, flags=re.IGNORECASE))

    # On fac-habitat, reservation blocks exist even when empty; require absence of explicit unavailable.
    has_reservation_keyword = bool(re.search(r"d[ée]poser\s+un\s+dossier\s+de\s+r[ée]servation", norm, flags=re.IGNORECASE))
    has_positive_count = bool(re.search(r"\b[1-9]\d*\s+logements?\s+disponibles?\b", norm, flags=re.IGNORECASE))

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


def load_state() -> Dict[str, str]:
    if not os.path.exists(STATE_FILE):
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
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send_discord(webhook_url: str, content: str, embeds: List[dict] | None = None) -> None:
    payload = {"content": content}
    if embeds:
        payload["embeds"] = embeds
    resp = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()


def make_embed(result: CheckResult) -> dict:
    color = 0x2ECC71 if result.status == "available" else 0xF1C40F
    return {
        "title": result.info.residence[:256],
        "url": result.info.direct_link,
        "description": (result.info.description or result.detail)[:2048],
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Statut", "value": result.status, "inline": True},
            {"name": "Source", "value": result.info.source[:1024], "inline": True},
            {"name": "Detail", "value": result.detail[:1024], "inline": False},
            {"name": "Residence", "value": result.info.residence[:1024], "inline": False},
            {"name": "Ville", "value": result.info.city[:1024], "inline": True},
            {"name": "Prix", "value": result.info.price[:1024], "inline": True},
            {"name": "Surface", "value": result.info.surface[:1024], "inline": True},
            {"name": "Lien direct", "value": result.info.direct_link[:1024], "inline": False},
        ],
    }


def check_once(webhook_url: str, previous_state: Dict[str, str]) -> Dict[str, str]:
    new_state = dict(previous_state)

    for target in TARGETS:
        key = target["url"]
        html, err = fetch_page(target["url"])

        if err:
            result = CheckResult(
                "error",
                f"Erreur HTTP: {err}",
                HousingInfo(target["site"].upper(), target["name"], "non trouvee", "non trouve", "non trouvee", "", target["url"]),
            )
        else:
            result = detect_status(target, html or "")

        old_status = previous_state.get(key)
        new_state[key] = result.status

        last_alerted_key = key + "_last_alerted"
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

        should_alert = cooldown_ok and (
            (result.status == "available" and old_status != "available") or
            (result.status == "error" and old_status != "error")
        )

        if should_alert:
            new_state[last_alerted_key] = datetime.now(timezone.utc).isoformat()
            content = "ALERTE LOGEMENT" if result.status == "available" else "Monitor: erreur de verification"
            try:
                send_discord(webhook_url, content, [make_embed(result)])
                print(f"[{datetime.now().isoformat(timespec='seconds')}] Notification envoyee: {result.info.direct_link}")
            except requests.RequestException as exc:
                print(f"[{datetime.now().isoformat(timespec='seconds')}] Erreur Discord: {exc}")

        print(f"[{datetime.now().isoformat(timespec='seconds')}] {result.status.upper():11} | {result.info.residence[:70]}")

    return new_state


def main() -> None:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise SystemExit(
            "Variable DISCORD_WEBHOOK_URL manquante. "
            "Exemple PowerShell: $env:DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'")

    print("Monitoring demarre (toutes les 2 minutes). Ctrl+C pour arreter.")
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
            print(f"[{datetime.now().isoformat(timespec='seconds')}] Erreur inattendue: {exc}")
            time.sleep(20)


if __name__ == "__main__":
    main()

