import itertools
import unicodedata
from functools import lru_cache
from typing import Any, List, Optional, Set

from anystore.logging import get_logger
from followthemoney import EntityProxy
from followthemoney.schema import Schema
from normality import ascii_text, collapse_spaces
from rigour.names import (
    remove_person_prefixes,
    replace_org_types_compare,
    tokenize_name,
)
from rigour.text import metaphone
from rigour.text.scripts import is_modern_alphabet

from openaleph_search.index.mapping import Field

log = get_logger(__name__)


def _clean_number(val: str) -> str:
    try:
        return str(float(val))
    except ValueError:
        return str(float(val.replace(",", ".")))


def get_geopoints(entity: EntityProxy) -> list[dict[str, str]]:
    """Get lon/lat pairs for indexing to `geo_point` field"""
    points = []
    lons = entity.get("longitude", quiet=True)
    lats = entity.get("latitude", quiet=True)
    for lon, lat in itertools.product(lons, lats):
        try:
            points.append({"lon": _clean_number(lon), "lat": _clean_number(lat)})
        except ValueError:
            pass
    return points


def preprocess_name(name: Optional[str]) -> Optional[str]:
    """Preprocess a name for comparison."""
    if name is None:
        return None
    name = unicodedata.normalize("NFC", name)
    name = name.lower()
    return collapse_spaces(name)


@lru_cache(maxsize=2000)
def clean_tokenize_name(schema: Schema, name: str) -> List[str]:
    """Tokenize a name and clean it up."""
    name = preprocess_name(name) or name
    if schema.name in ("LegalEntity", "Organization", "Company", "PublicBody"):
        name = replace_org_types_compare(name, normalizer=preprocess_name)
    elif schema.name in ("LegalEntity", "Person"):
        name = remove_person_prefixes(name)
    return tokenize_name(name)


def phonetic_names(schema: Schema, names: List[str]) -> Set[str]:
    """Generate phonetic forms of the given names."""
    phonemes: Set[str] = set()
    if schema.is_a("LegalEntity"):  # only include namy things
        for name in names:
            for token in clean_tokenize_name(schema, name):
                if len(token) < 3 or not is_modern_alphabet(token):
                    continue
                if token.isnumeric():
                    continue
                phoneme = metaphone(ascii_text(token))
                if len(phoneme) > 2:
                    phonemes.add(phoneme)
    return phonemes


def index_name_parts(schema: Schema, names: List[str]) -> Set[str]:
    """Generate a list of indexable name parts from the given names."""
    parts: Set[str] = set()
    if schema.is_a("LegalEntity"):  # only include namy things
        for name in names:
            for token in clean_tokenize_name(schema, name):
                if len(token) < 2:
                    continue
                parts.add(token)
                # TODO: put name and company symbol lookups here
                if is_modern_alphabet(token):
                    ascii_token = ascii_text(token)
                    if ascii_token is not None and len(ascii_token) > 1:
                        parts.add(ascii_token)
    return parts


def clean_percolator_names(names: List[str]) -> List[str]:
    """Drop names that are too noisy to percolate.

    - Multi-token names are kept (specific enough for phrase matching).
    - Single-token names are kept only if at least 7 characters long;
      shorter single tokens (e.g. "Doe", "Acme") produce too many false
      positives when percolated against arbitrary text.
    - Empty / whitespace-only entries are dropped.
    """
    cleaned: List[str] = []
    for name in names:
        stripped = (name or "").strip()
        if not stripped:
            continue
        tokens = stripped.split()
        if len(tokens) > 1 or len(tokens[0]) >= 7:
            cleaned.append(stripped)
    return cleaned


def clean_percolator_identifiers(identifiers: List[str]) -> List[str]:
    """Drop identifiers too short or noisy to percolate.

    - Strip whitespace.
    - Drop empty entries.
    - Drop very short identifiers (< 5 characters), which are too generic
      to be useful as percolator triggers (e.g. country codes, stub IDs).
    - Deduplicate while preserving order so the same identifier listed
      under multiple property paths (e.g. registrationNumber AND
      taxNumber) doesn't produce duplicate clauses.
    """
    seen: Set[str] = set()
    cleaned: List[str] = []
    for ident in identifiers:
        stripped = (ident or "").strip()
        if len(stripped) < 5 or stripped in seen:
            continue
        seen.add(stripped)
        cleaned.append(stripped)
    return cleaned


def make_percolator_query(
    names: List[str],
    identifiers: List[str] | None = None,
) -> dict[str, Any] | None:
    """Build a stored percolator query from name + identifier signals.

    Names use `match_phrase` with `slop: 2` — tolerant of inserted
    middle initials (`"Jane Doe"` matches `"Jane A. Doe"`), reversed
    last-name-first variants (`"Doe, Jane"`), and small token gaps.
    Performance is essentially the same as `slop: 1`; both fall off
    the `index_phrases` shingle fast path that `slop: 0` uses, and the
    slop value only affects a constant-time budget check at match time.
    Identifiers use `match_phrase` with `slop: 0` — they must appear
    exactly as stored, no slop tolerated.

    All cleaned name and identifier values become clauses — there is
    no cap. OpenSanctions-style entities with many language variants
    or aliases produce many clauses per stored query, which favours
    recall (every variant a document might use is matchable). The
    downstream app or user is responsible for disambiguating among
    matched entities, e.g. via `entity.topics`, `entity.position`, or
    similar entity-level signals.

    Each clause is tagged with `_name` ("name" or "identifier") so the
    percolate response can surface which clause(s) fired per hit via
    `matched_queries`. ES tracks named queries independently of scoring,
    so this works inside the `constant_score.filter` wrap that
    `PercolatorQuery.get_inner_query` applies.

    No `boost` values: `PercolatorQuery` wraps the query in
    `constant_score`, so server-side relevance scoring is skipped.
    Downstream apps consume `matched_queries` and decide their own
    weighting between name and identifier signals.

    Returns `None` if both cleaned lists are empty, in which case the
    caller should NOT add a percolator field to the entity (so the entity
    stays out of the percolator candidate set).
    """
    cleaned_names = clean_percolator_names(names)
    cleaned_ids = clean_percolator_identifiers(identifiers or [])
    if not cleaned_names and not cleaned_ids:
        return None

    shoulds: List[dict[str, Any]] = []
    for n in cleaned_names:
        shoulds.append(
            {
                "match_phrase": {
                    Field.CONTENT: {
                        "query": n,
                        "slop": 2,
                        "_name": "name",
                    }
                }
            }
        )
    for i in cleaned_ids:
        shoulds.append(
            {
                "match_phrase": {
                    Field.CONTENT: {
                        "query": i,
                        "slop": 0,  # identifiers must match exactly
                        "_name": "identifier",
                    }
                }
            }
        )
    return {"bool": {"minimum_should_match": 1, "should": shoulds}}


def index_name_keys(schema: Schema, names: List[str]) -> Set[str]:
    """Generate a indexable name keys from the given names."""
    keys: Set[str] = set()
    for name in names:
        tokens = clean_tokenize_name(schema, name)
        ascii_tokens: List[str] = []
        for token in tokens:
            if token.isnumeric() or not is_modern_alphabet(token):
                ascii_tokens.append(token)
                continue
            ascii_token = ascii_text(token) or token
            ascii_tokens.append(ascii_token)
        ascii_name = "".join(sorted(ascii_tokens))
        if len(ascii_name) > 5:
            keys.add(ascii_name)
    return keys
