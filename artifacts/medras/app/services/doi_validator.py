"""Validate DOIs against the public Crossref API.

`api.crossref.org/works/{doi}` is free, requires no API key, but Crossref
asks for a polite User-Agent. We hit it with a 5-second timeout and cache
results in-process for an hour to avoid hammering them on re-renders.
"""

from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
from threading import Lock
from typing import Any, Dict, Optional, Tuple

from app.services.reference_extractor import _normalise_doi  # type: ignore[attr-defined]

_TIMEOUT_S = 5.0
_CACHE_TTL_S = 60 * 60
_USER_AGENT = "MedRAS/1.0 (mailto:noreply@medras.app)"

_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CACHE_LOCK = Lock()
_DOI_FORMAT_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if not hit: return None
        ts, val = hit
        if time.time() - ts > _CACHE_TTL_S:
            _CACHE.pop(key, None)
            return None
        return val


def _cache_put(key: str, val: Dict[str, Any]) -> None:
    with _CACHE_LOCK:
        if len(_CACHE) > 2000:
            # Drop the 200 oldest entries to keep memory bounded.
            for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:200]:
                _CACHE.pop(k, None)
        _CACHE[key] = (time.time(), val)


def validate_doi(raw_doi: str) -> Dict[str, Any]:
    """Return a dict describing whether a DOI is well-formed and resolvable.

    Shape:
        {
          "input":      original string,
          "normalized": "10.xxxx/yyyy" or "",
          "valid":      bool,           # well-formed AND Crossref says 200
          "format_ok":  bool,           # syntactically valid DOI
          "status":     "ok"|"not_found"|"format_error"|"network_error"|"empty",
          "metadata":   {title, journal, year, doi} when ok, else None
        }
    """
    out: Dict[str, Any] = {
        "input": raw_doi or "",
        "normalized": "",
        "valid": False,
        "format_ok": False,
        "status": "empty",
        "metadata": None,
    }
    norm = _normalise_doi(raw_doi or "")
    if not norm:
        return out
    out["normalized"] = norm
    if not _DOI_FORMAT_RE.match(norm):
        out["status"] = "format_error"
        return out
    out["format_ok"] = True

    cached = _cache_get(norm)
    if cached:
        return {**out, **cached}

    url = "https://api.crossref.org/works/" + urllib.parse.quote(norm, safe="/")
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            if resp.status != 200:
                result = {"valid": False, "status": "not_found", "metadata": None}
                _cache_put(norm, result)
                return {**out, **result}
            import json as _json
            data = _json.loads(resp.read().decode("utf-8", errors="replace"))
            msg = (data or {}).get("message") or {}
            title_arr = msg.get("title") or []
            cont_arr = msg.get("container-title") or []
            issued = ((msg.get("issued") or {}).get("date-parts") or [[None]])[0]
            metadata = {
                "title":   (title_arr[0] if title_arr else "") or "",
                "journal": (cont_arr[0] if cont_arr else "") or "",
                "year":    str(issued[0]) if issued and issued[0] else "",
                "doi":     msg.get("DOI") or norm,
            }
            result = {"valid": True, "status": "ok", "metadata": metadata}
            _cache_put(norm, result)
            return {**out, **result}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            result = {"valid": False, "status": "not_found", "metadata": None}
            _cache_put(norm, result)
            return {**out, **result}
        return {**out, "valid": False, "status": "network_error"}
    except Exception:
        # Network timeout / DNS / etc — don't cache, let it retry next time.
        return {**out, "valid": False, "status": "network_error"}


def find_duplicates(refs):
    """Return a dict {index: reason_str} for each duplicate in `refs`.

    Two refs are considered duplicates if they share a non-empty DOI, OR if
    their normalised titles match (alpha-numeric only, lower-case) AND year
    matches.
    """
    seen_doi: Dict[str, int] = {}
    seen_title: Dict[Tuple[str, str], int] = {}
    flagged: Dict[int, str] = {}
    for i, r in enumerate(refs or []):
        doi = (r.get("doi") or "").strip().lower()
        title_key = re.sub(r"[^a-z0-9]+", "", (r.get("title") or "").lower())
        year = (r.get("year") or "").strip()
        if doi:
            if doi in seen_doi:
                flagged[i] = f"Duplicate DOI of #{seen_doi[doi] + 1}"
                continue
            seen_doi[doi] = i
        if title_key:
            key = (title_key, year)
            if key in seen_title:
                flagged[i] = f"Duplicate of #{seen_title[key] + 1} (same title/year)"
                continue
            seen_title[key] = i
    return flagged
