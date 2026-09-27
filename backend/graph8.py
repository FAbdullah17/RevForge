"""Graph8 integration boundary. Only module allowed to talk to graph8.

Two modes (``MOCK_GRAPH8=1`` or no API key selects mock):
* Mock: deterministic in-memory market universe — 320 synthetic companies.
  Same filter in, same companies out, every run. Shapes mirror the live
  API so the execution agent cannot tell the difference.
* Live (``MOCK_GRAPH8=0`` + key): REST calls to ``G8_BASE_URL`` with
  ``Authorization: Bearer <key>`` (see the published OpenAPI spec).

Filter mapping (live open-data search only exposes a subset):
employees range -> employee_count bands; tech / intent / hiring /
leadership-change dimensions are not per-company searchable, so they are
covered by cohort-level signal audiences instead (see get_signals).
Unmappable keys are ignored, never silently treated as matches.

Nothing outside ``agents/execution.py`` and the API layer imports this.
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import MOCK_GRAPH8, G8_API_KEY, G8_BASE_URL

#: Deterministic mock market. Fixed counts keep the demo story stable:
#: the H17 stack matches exactly 86 companies (~103 buyer contacts).
MOCK_SEED = 7
MOCK_MATCHING = 86
MOCK_OTHER = 234

_MKT = ["Acme", "Globex", "Initech", "Hooli", "Stark", "Wayne", "Tyrell", "Aperture"]
_INDUSTRIES = ["SaaS", "Fintech", "HealthTech", "Retail", "Manufacturing"]

_universe_cache: list[dict[str, Any]] | None = None


def _matching_company(rng: random.Random, i: int) -> dict[str, Any]:
    return {
        "id": f"MKT{i:03d}",
        "company": f"{rng.choice(_MKT)}-{i}",
        "industry": rng.choice(["SaaS", "SaaS", "Fintech"]),
        "employees": rng.randint(150, 500),
        "region": "US",
        "tech": "Salesforce",
        "new_vp_sales": True,
        "sdr_openings": rng.randint(3, 6),
        "intent": "high",
    }


def _other_company(rng: random.Random, i: int) -> dict[str, Any]:
    employees = rng.choice([rng.randint(20, 140), rng.randint(150, 500), rng.randint(501, 1200)])
    new_vp = rng.random() < 0.22
    sdr = rng.choices([0, 1, 2, 3, 4, 5], weights=[30, 25, 18, 12, 9, 6])[0]
    tech = rng.choices(["Salesforce", "HubSpot", "Pipedrive", "Other"], weights=[30, 30, 15, 25])[0]
    intent = rng.choices(["high", "medium", "low"], weights=[28, 37, 35])[0]
    if 150 <= employees <= 500 and new_vp and sdr >= 3 and tech == "Salesforce" and intent == "high":
        tech = "HubSpot"  # break the full stack: only the 86 seeded ones match
    return {
        "id": f"MKT{i:03d}",
        "company": f"{rng.choice(_MKT)}-{i}",
        "industry": rng.choice(_INDUSTRIES),
        "employees": employees,
        "region": rng.choice(["US", "EU"]),
        "tech": tech,
        "new_vp_sales": new_vp,
        "sdr_openings": sdr,
        "intent": intent,
    }


def get_universe() -> list[dict[str, Any]]:
    """Deterministic mock buyer-graph universe (cached, 320 companies)."""
    global _universe_cache
    if _universe_cache is None:
        rng = random.Random(MOCK_SEED)
        companies = [_matching_company(rng, i) for i in range(1, MOCK_MATCHING + 1)]
        companies += [_other_company(rng, i) for i in range(MOCK_MATCHING + 1, MOCK_MATCHING + MOCK_OTHER + 1)]
        rng.shuffle(companies)
        _universe_cache = companies
    return _universe_cache


def _matches(company: dict[str, Any], filt: dict[str, Any]) -> bool:
    """Apply a structured filter. Unknown keys are ignored (forward-compat).

    A filter carrying ``exclude_ids`` selects the complement (baseline
    pool); other keys are then ignored so control cohorts sample the
    wider market rather than an empty slice.
    """
    if "exclude_ids" in filt:
        return company["id"] not in filt["exclude_ids"]
    if "employees_min" in filt and company["employees"] < filt["employees_min"]:
        return False
    if "employees_max" in filt and company["employees"] > filt["employees_max"]:
        return False
    if "new_vp_sales" in filt and company["new_vp_sales"] != filt["new_vp_sales"]:
        return False
    if "sdr_min" in filt and company["sdr_openings"] < filt["sdr_min"]:
        return False
    if "tech" in filt and company["tech"] != filt["tech"]:
        return False
    if "intent" in filt and company["intent"] != filt["intent"]:
        return False
    if "exclude_ids" in filt and company["id"] in filt["exclude_ids"]:
        return False
    return True


def _use_mock() -> bool:
    return MOCK_GRAPH8 or not G8_API_KEY


def transport() -> str:
    """Active transport: 'mock' or 'live'. Recorded on experiments."""
    return "mock" if _use_mock() else "live"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# Live REST transport
# --------------------------------------------------------------------------

_TIMEOUT = 25.0

#: Transient network blips (resets, slow TLS) are retried; HTTP error
#: statuses are returned immediately — a 4xx/5xx is an answer, not a blip.
#: DNS failures are not retried here: the shared session below resolves
#: once and pools connections, so a resolution failure is systemic.
_RETRIES = 3

_session: httpx.Client | None = None


def _shared() -> httpx.Client:
    """Process-wide session: one DNS resolution, pooled keep-alive."""
    global _session
    if _session is None:
        _session = httpx.Client(
            base_url=G8_BASE_URL,
            headers={"Authorization": f"Bearer {G8_API_KEY}"},
            timeout=_TIMEOUT,
        )
    return _session


def _live(method: str, path: str, **kwargs: Any) -> Any:
    """One authenticated call. Non-2xx raises with status + body excerpt."""
    last_exc: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            resp = _shared().request(method, path, **kwargs)
            if resp.status_code >= 300:
                raise RuntimeError(
                    f"graph8 {method} {path} -> {resp.status_code}: {resp.text[:300]}"
                )
            return resp.json().get("data")
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt < _RETRIES - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"graph8 {method} {path} unreachable after {_RETRIES} tries: {last_exc}")


#: Size-band vocabulary of the open company index, with midpoints used to
#: keep the normalized ``employees`` field numeric downstream.
_BANDS: list[tuple[str, int, int]] = [
    ("1-10", 1, 10),
    ("11-50", 11, 50),
    ("51-200", 51, 200),
    ("201-500", 201, 500),
    ("501-1000", 501, 1000),
    ("1001-5000", 1001, 5000),
    ("5001-10000", 5001, 10000),
    ("10001+", 10001, 100000),
]


def _bands_for_range(lo: int, hi: int) -> list[str]:
    return [b for b, blo, bhi in _BANDS if blo <= hi and bhi >= lo]


def _band_midpoint(band: str) -> int:
    for b, blo, bhi in _BANDS:
        if b == band:
            return (blo + min(bhi, 10000)) // 2
    return 0


def _live_company_filter(filt: dict[str, Any]) -> list[dict[str, Any]]:
    """Map the structured filter onto open-search field filters."""
    out: list[dict[str, Any]] = []
    if "employees_min" in filt or "employees_max" in filt:
        bands = _bands_for_range(filt.get("employees_min", 0), filt.get("employees_max", 10**9))
        if bands:
            out.append({"field": "employee_count", "operator": "any_of", "value": bands})
    return out


def _norm_company(item: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize an open-search hit. Returns None when unusable (no id/name)."""
    domain = item.get("domain") or item.get("website") or ""
    name = item.get("name") or domain
    if not (domain or name):
        return None
    return {
        "id": domain or name,
        "company": name,
        "industry": item.get("industry") or "",
        "employees": _band_midpoint(item.get("employee_count") or ""),
        "employee_band": item.get("employee_count") or "",
        "region": item.get("country") or "",
        "tech": "unconfirmed",
        "intent": "unknown",
        "domain": domain,
    }


def _live_search_companies(filt: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """Paged open-data search with client-side exclusion."""
    field_filters = _live_company_filter(filt)
    if not field_filters:
        raise ValueError(f"filter {filt!r} maps to no live-searchable field")
    excluded = set(filt.get("exclude_ids") or [])
    found: list[dict[str, Any]] = []
    page = 1
    while len(found) < limit and page <= 8:
        payload = _live("POST", "/search/companies", json={
            "filters": field_filters, "page": page, "limit": min(100, limit),
        })
        items = payload.get("items", payload) if isinstance(payload, dict) else payload
        if not items:
            break
        for item in items:
            row = _norm_company(item)
            if row is None:
                continue
            if row["id"] and row["id"] not in excluded and all(r["id"] != row["id"] for r in found):
                found.append(row)
                if len(found) >= limit:
                    break
        page += 1
    return found


def _live_find_people(company_ids: list[str]) -> list[dict[str, Any]]:
    """Buyer titles at the given company domains (chunked requests)."""
    contacts: list[dict[str, Any]] = []
    titles = ["VP Sales", "VP of Sales", "CRO", "Chief Revenue Officer",
              "Head of Sales", "SVP Sales", "EVP Sales", "Sales Director"]
    for i in range(0, len(company_ids), 20):
        chunk = company_ids[i:i + 20]
        payload = _live("POST", "/search/contacts", json={
            "filters": [
                {"field": "company_domain", "operator": "any_of", "value": chunk},
                {"field": "job_title", "operator": "any_of", "value": titles},
            ],
            "page": 1, "limit": 100,
        })
        items = payload if isinstance(payload, list) else payload.get("items", payload)
        for item in items or []:
            li = item.get("linkedin_url") or ""
            cid = item.get("company_domain") or ""
            contacts.append({
                "id": li or f"{item.get('first_name', '')}-{item.get('last_name', '')}-{cid}",
                "company_id": cid,
                "company": item.get("company_name") or "",
                "title": item.get("job_title") or "",
                "persona": "buyer",
                "email": item.get("work_email") or "",
                "linkedin_url": li,
                "first_name": item.get("first_name") or "",
                "last_name": item.get("last_name") or "",
            })
    return contacts


def _live_enrich(contacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Email-presence verification (workspace PK verification needs CRM ids)."""
    out = []
    for c in contacts:
        row = dict(c)
        email = (c.get("email") or "").strip()
        row["verified"] = bool(email) and "@" in email and "***" not in email
        row["enriched_at"] = _now()
        out.append(row)
    return out


_signal_cache: dict[str, Any] | None = None


def _live_signals(company_ids: list[str]) -> list[dict[str, Any]]:
    """Live signal context: workspace intent state + cohort-level audiences.

    Per-company tech/hiring is not exposed by the open index, so rows
    record the cohort-level audience evidence (Salesforce users, SDR
    hiring) alongside each company instead of inventing per-company facts.
    """
    global _signal_cache
    if _signal_cache is None:
        workspace = _live("GET", "/accounts/intent-signal")
        tech = _live("POST", "/search/signals/preview",
                     json={"type": "tech", "techs": ["Salesforce"], "top_k": 10})
        hiring = _live("POST", "/search/signals/preview",
                       json={"type": "hiring", "roles": ["SDR"], "days": 90, "top_k": 10})
        _signal_cache = {"workspace_intent": workspace, "tech": tech, "hiring": hiring}
    ctx = _signal_cache
    return [
        {"company_id": cid, "intent": "unknown", "tech": "unconfirmed",
         "hiring": "unconfirmed", "market_context": {
             "salesforce_companies": (ctx["tech"] or {}).get("companies"),
             "sdr_hiring_companies": (ctx["hiring"] or {}).get("companies"),
             "workspace_intent": ctx["workspace_intent"],
         }, "observed_at": _now()}
        for cid in company_ids
    ]


def _extract_id(payload: Any, context: str) -> str:
    """Pull an object id out of a create-response, or fail with the body."""
    if isinstance(payload, dict):
        for key in ("id", "audience_id", "campaign_id", "list_id"):
            if payload.get(key) is not None:
                return str(payload[key])
        nested = payload.get("data", payload)
        if isinstance(nested, dict):
            for key in ("id", "audience_id", "campaign_id", "list_id"):
                if nested.get(key) is not None:
                    return str(nested[key])
    raise RuntimeError(f"graph8 create ({context}) returned no id: {str(payload)[:300]}")


def _live_create_list(contact_ids: list[str], name: str) -> dict[str, Any]:
    payload = _live("POST", "/lists", json={
        "title": f"[RevForge TEST] {name}",
        "type": "contacts",
        "description": f"RevForge experiment cohort ({len(contact_ids)} contacts). Safe to delete.",
    })
    return {"list_id": _extract_id(payload, "list"), "n": len(contact_ids)}


def _live_create_campaign(list_id: str, name: str) -> dict[str, Any]:
    payload = _live("POST", "/campaigns", json={
        "name": f"[RevForge TEST] {name}",
        "audience_list_id": list_id,
    })
    return {"campaign_id": _extract_id(payload, "campaign"), "list_id": list_id, "name": name}


def _live_assert_contacts(list_id: int, contacts: list[dict[str, Any]]) -> dict[str, Any]:
    """Import open-search contacts into a workspace list. Returns counts."""
    rows = [{
        "first_name": c.get("first_name") or "",
        "last_name": c.get("last_name") or "",
        "linkedin_url": c.get("linkedin_url") or "",
        "company_domain": c.get("company_id") or "",
        "job_title": c.get("title") or "",
    } for c in contacts]
    payload = _live("PUT", "/contacts/assert/batch",
                    json={"list_id": list_id, "contacts": rows})
    return payload if isinstance(payload, dict) else {}


def _live_unlock_list(list_id: int) -> dict[str, Any]:
    """Unlock contact details for a list. Spends enrichment credits."""
    payload = _live("POST", "/contacts/unlock-info", json={"list_id": list_id})
    return payload if isinstance(payload, dict) else {}


def _live_list_members(list_id: int) -> list[dict[str, Any]]:
    """Workspace contacts of a list (PKs + revealed emails) via xlsx export."""
    import base64
    from io import BytesIO

    import pandas as pd

    payload = _live("GET", f"/lists/{list_id}/download")
    content = (payload or {}).get("content", "")
    df = pd.read_excel(BytesIO(base64.b64decode(content)))
    df.columns = [str(c).strip().lower() for c in df.columns]
    members = []
    for _, row in df.iterrows():
        rec = {k: ("" if pd.isna(v) else v) for k, v in row.items()}
        pk = rec.get("id", rec.get("contact_id", rec.get("pk", "")))
        members.append({
            "pk": pk,
            "email": rec.get("work_email", rec.get("email", "")),
            "linkedin_url": rec.get("linkedin_url", rec.get("linkedin", "")),
            "first_name": rec.get("first_name", ""),
            "last_name": rec.get("last_name", ""),
        })
    return members


def _live_verify_pks(pks: list[Any]) -> dict[Any, bool]:
    """Email verification per workspace PK. Unverifiable PKs map to False."""
    try:
        payload = _live("POST", "/contacts/verify-email", json={"contact_pks": pks})
    except RuntimeError:
        return {pk: False for pk in pks}
    verdicts: dict[Any, bool] = {}
    items = payload if isinstance(payload, list) else (payload or {}).get("items", payload)
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            pk = item.get("contact_id", item.get("id", item.get("pk")))
            status = str(item.get("status", item.get("result", ""))).lower()
            verdicts[pk] = status in ("valid", "verified", "deliverable", "ok")
    return verdicts


def _live_create_sequence(name: str, list_id: int, owner_email: str) -> str:
    payload = _live("POST", "/sequences", json={
        "name": f"[RevForge TEST] {name}",
        "user_email": owner_email,
        "associated_list_id": list_id,
    })
    return _extract_id(payload, "sequence")


def _live_enroll(sequence_id: str, list_id: int, pks: list[Any]) -> None:
    _live("POST", f"/sequences/{sequence_id}/contacts",
          json={"list_id": list_id, "contact_ids": pks})


def _live_sequence_contacts(sequence_id: str) -> list[Any]:
    payload = _live("GET", f"/sequences/{sequence_id}/contact-ids")
    if isinstance(payload, dict):
        return payload.get("contact_ids", [])
    return payload if isinstance(payload, list) else []


def archive_sequence(sequence_id: str) -> dict[str, Any]:
    """Archive a sequence (cleanup helper for test runs)."""
    if _use_mock():
        return {"sequence_id": sequence_id, "status": "archived", "source": "mock"}
    payload = _live("DELETE", f"/sequences/{sequence_id}")
    return payload if isinstance(payload, dict) else {}


# --------------------------------------------------------------------------
# Buyer-graph reads
# --------------------------------------------------------------------------

def search_companies(filt: dict[str, Any], limit: int = 300) -> list[dict[str, Any]]:
    """Return companies matching a structured filter (up to limit)."""
    if _use_mock():
        return [c for c in get_universe() if _matches(c, filt)]
    return _live_search_companies(filt, limit)


def find_people(company_ids: list[str], persona: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Buyer contacts for companies. Mock: 1 buyer each + a 2nd for every 5th."""
    if _use_mock():
        by_id = {c["id"]: c for c in get_universe()}
        contacts: list[dict[str, Any]] = []
        for n, cid in enumerate(company_ids):
            co = by_id.get(cid)
            if co is None:
                continue
            contacts.append({
                "id": f"{cid}-P1", "company_id": cid, "company": co["company"],
                "title": "VP Sales", "persona": "buyer",
            })
            if n % 5 == 0:
                contacts.append({
                    "id": f"{cid}-P2", "company_id": cid, "company": co["company"],
                    "title": "CRO", "persona": "buyer",
                })
        return contacts
    return _live_find_people(company_ids)


def enrich(contacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Verify + complete contacts. Mock: deterministic emails, all verified."""
    if _use_mock():
        out = []
        for c in contacts:
            row = dict(c)
            slug = c["company"].lower().replace(" ", "")
            row["email"] = f"{c['title'].lower().replace(' ', '.')}@{slug}.com"
            row["verified"] = True
            row["enriched_at"] = _now()
            out.append(row)
        return out
    return _live_enrich(contacts)


def get_signals(company_ids: list[str]) -> list[dict[str, Any]]:
    """Current-state signals: separates 'fits' from 'fits right now'."""
    if _use_mock():
        by_id = {c["id"]: c for c in get_universe()}
        return [
            {"company_id": cid, "intent": by_id[cid]["intent"],
             "sdr_openings": by_id[cid]["sdr_openings"],
             "new_vp_sales": by_id[cid]["new_vp_sales"], "observed_at": _now()}
            for cid in company_ids if cid in by_id
        ]
    return _live_signals(company_ids)


# --------------------------------------------------------------------------
# Execution writes (create real workspace objects when live)
# --------------------------------------------------------------------------

def create_list(contact_ids: list[str], name: str = "mock") -> dict[str, Any]:
    """Create a graph8 list. Mock id is deterministic from name + size."""
    if _use_mock():
        return {"list_id": f"list-{name}-{len(contact_ids)}", "n": len(contact_ids)}
    return _live_create_list(contact_ids, name)


def create_campaign(list_id: str, name: str = "revforge") -> dict[str, Any]:
    """Create a graph8 campaign for a list. Mock id deterministic."""
    if _use_mock():
        return {"campaign_id": f"cmp-{name}-{list_id}", "list_id": list_id, "name": name}
    return _live_create_campaign(list_id, name)


def get_outcomes(campaign_id: str) -> dict[str, Any]:
    """Read campaign outcomes for ingested events."""
    if _use_mock():
        return {"campaign_id": campaign_id, "sent": 0, "replies": 0, "source": "mock"}
    raise RuntimeError(
        "live outcomes need a running sequence with engagement; "
        "sequence stats endpoints exist for follow-up, seeded sync stays the demo path"
    )
