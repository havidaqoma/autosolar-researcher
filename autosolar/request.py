"""Stage S0: question to site. Units in names."""
import json
import math
from dataclasses import dataclass
from typing import Any, Optional


PARSE_INSTRUCTIONS = (
    "You turn a user question into a JSON object. Return only the JSON object, no prose, no code fence.\n"
    "Keys:\n"
    '  "site_name": the place the question is about, as written by the user (string, or null if none),\n'
    '  "country": the country of that place in English (string, or null if unknown),\n'
    '  "question_type": "pv_battery_for_diesel_grid" if the user asks whether or how much solar PV and/or '
    'battery storage to add to a power system, else "other",\n'
    '  "language": the ISO 639-1 code of the question.\n'
    "Do not guess coordinates. Do not add other keys."
)
QUESTION_TYPES = ("pv_battery_for_diesel_grid", "other")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "AutoSolarResearcher/0.1 (+https://github.com/havidaqoma/autosolar-researcher)"
INDONESIA_BBOX_DEG = (-11.5, 6.5, 94.5, 141.5)


class ParseError(ValueError):
    """Bad model JSON text."""


class SiteNotFound(ValueError):
    """Geocoder found nothing."""


class GeocodeError(RuntimeError):
    """Geocoder service failure."""


class UnsupportedQuestion(ValueError):
    """Question out of scope."""


@dataclass(frozen=True)
class StudyRequest:
    """Parsed user question. cost_usd in USD."""

    question: str
    site_name: Optional[str]
    country: Optional[str]
    question_type: str
    language: str
    model: str
    cost_usd: float


@dataclass(frozen=True)
class Site:
    """Geocoded site. lat_deg and lon_deg in degrees."""

    query: str
    name: str
    display_name: str
    lat_deg: float
    lon_deg: float
    osm_type: str
    osm_id: int
    addresstype: str
    n_candidates: int
    source: str


def _is_two_lower_ascii(value: Any) -> bool:
    """Check two lowercase ASCII letters."""
    if not isinstance(value, str):
        return False
    if len(value) != 2:
        return False
    for ch in value:
        if not ("a" <= ch <= "z"):
            return False
    return True


def parse_question(question: Any, client: Any, run_id: Any, *, estimate_usd: float = 0.01) -> StudyRequest:
    """Parse question via model client. estimate_usd in USD."""
    if not isinstance(question, str):
        raise ValueError("question must be a string")
    question_stripped = question.strip()
    if not (1 <= len(question_stripped) <= 2000):
        raise ValueError("question must hold 1 to 2000 characters after strip")
    messages = [
        {"role": "system", "content": PARSE_INSTRUCTIONS},
        {"role": "user", "content": question_stripped},
    ]
    result = client.respond(run_id, "S0_parse", messages, estimate_usd=estimate_usd)
    raw_text = result.text
    if not isinstance(raw_text, str):
        raise ParseError("model text is not a string")
    text_stripped = raw_text.strip()
    parse_text = text_stripped
    if parse_text.startswith("```"):
        lines = parse_text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        parse_text = "\n".join(lines)
    try:
        data = json.loads(parse_text)
    except Exception:
        raise ParseError("invalid JSON: " + raw_text[:300])
    if not isinstance(data, dict):
        raise ParseError("not an object: " + raw_text[:300])
    if set(data.keys()) != {"site_name", "country", "question_type", "language"}:
        raise ParseError("bad keys: " + raw_text[:300])
    site_raw = data["site_name"]
    country_raw = data["country"]
    qtype_raw = data["question_type"]
    lang_raw = data["language"]
    if site_raw is not None:
        if not isinstance(site_raw, str):
            raise ParseError("bad site_name: " + raw_text[:300])
        if not site_raw.strip():
            raise ParseError("bad site_name: " + raw_text[:300])
        site_name = site_raw.strip()
    else:
        site_name = None
    if country_raw is not None:
        if not isinstance(country_raw, str):
            raise ParseError("bad country: " + raw_text[:300])
        country = country_raw.strip()
    else:
        country = None
    if qtype_raw not in QUESTION_TYPES:
        raise ParseError("bad question_type: " + raw_text[:300])
    if not _is_two_lower_ascii(lang_raw):
        raise ParseError("bad language: " + raw_text[:300])
    return StudyRequest(
        question=question_stripped,
        site_name=site_name,
        country=country,
        question_type=qtype_raw,
        language=lang_raw,
        model=result.model,
        cost_usd=result.cost_usd,
    )


def check_request(req: StudyRequest) -> None:
    """Raise UnsupportedQuestion when out of scope, else None."""
    if req.question_type != "pv_battery_for_diesel_grid":
        raise UnsupportedQuestion("unsupported question_type: %s" % (req.question_type,))
    if req.site_name is None:
        raise UnsupportedQuestion("missing site_name")
    country = req.country
    if country is None or not isinstance(country, str) or country.strip().lower() != "indonesia":
        raise UnsupportedQuestion("country is not Indonesia: %s" % (country,))
    return None


def geocode(site_name: Any, http_get: Any, *, country_code: str = "id", timeout_s: float = 30.0) -> Site:
    """Geocode with Nominatim. timeout_s in seconds, degrees out."""
    if not isinstance(site_name, str) or not site_name.strip():
        raise ValueError("site_name must be a non-empty string")
    if not _is_two_lower_ascii(country_code):
        raise ValueError("country_code must be two lowercase ASCII letters")
    site_stripped = site_name.strip()
    resp = http_get(
        NOMINATIM_URL,
        params={"q": site_stripped, "format": "jsonv2", "limit": 3, "countrycodes": country_code},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout_s,
    )
    status_code = getattr(resp, "status_code", None)
    if status_code != 200:
        raise GeocodeError("geocode status %s for query %s" % (status_code, site_stripped))
    try:
        payload = resp.json()
    except Exception as exc:
        raise GeocodeError("geocode bad JSON for query %s: %s" % (site_stripped, exc))
    if not isinstance(payload, list):
        raise GeocodeError("geocode bad payload for query %s" % (site_stripped,))
    if len(payload) == 0:
        raise SiteNotFound("site not found: %s" % (site_stripped,))
    hit = payload[0]
    if not isinstance(hit, dict):
        raise GeocodeError("geocode bad hit for query %s" % (site_stripped,))
    for key in ("name", "display_name", "lat", "lon", "osm_type", "osm_id", "addresstype"):
        if key not in hit:
            raise GeocodeError("geocode missing %s for query %s" % (key, site_stripped))
    name_raw = hit["name"]
    if isinstance(name_raw, str):
        name = name_raw.strip() if name_raw.strip() else site_stripped
    else:
        raise GeocodeError("geocode bad name for query %s" % (site_stripped,))
    display_raw = hit["display_name"]
    if not isinstance(display_raw, str):
        raise GeocodeError("geocode bad display_name for query %s" % (site_stripped,))
    osm_type_raw = hit["osm_type"]
    if not isinstance(osm_type_raw, str):
        raise GeocodeError("geocode bad osm_type for query %s" % (site_stripped,))
    addr_raw = hit["addresstype"]
    if not isinstance(addr_raw, str):
        raise GeocodeError("geocode bad addresstype for query %s" % (site_stripped,))
    try:
        lat_deg = float(hit["lat"])
        lon_deg = float(hit["lon"])
    except Exception:
        raise GeocodeError("geocode bad coordinates for query %s" % (site_stripped,))
    if not (math.isfinite(lat_deg) and math.isfinite(lon_deg)):
        raise GeocodeError("geocode non-finite coordinates for query %s" % (site_stripped,))
    try:
        osm_id = int(hit["osm_id"])
    except Exception:
        raise GeocodeError("geocode bad osm_id for query %s" % (site_stripped,))
    if country_code == "id":
        lat_min, lat_max, lon_min, lon_max = INDONESIA_BBOX_DEG
        if not (lat_min <= lat_deg <= lat_max and lon_min <= lon_deg <= lon_max):
            raise ValueError("point outside Indonesia for query %s" % (site_stripped,))
    return Site(
        query=site_stripped,
        name=name,
        display_name=display_raw,
        lat_deg=lat_deg,
        lon_deg=lon_deg,
        osm_type=osm_type_raw,
        osm_id=osm_id,
        addresstype=addr_raw,
        n_candidates=len(payload),
        source="OpenStreetMap Nominatim",
    )
