import itertools
import unicodedata
from functools import lru_cache
from typing import Any

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
from openaleph_search.settings import Settings

log = get_logger(__name__)
settings = Settings()


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


def preprocess_name(name: str | None) -> str | None:
    """Preprocess a name for comparison."""
    if name is None:
        return None
    name = unicodedata.normalize("NFC", name)
    name = name.lower()
    return collapse_spaces(name)


@lru_cache(maxsize=2000)
def clean_tokenize_name(schema: Schema, name: str) -> list[str]:
    """Tokenize a name and clean it up."""
    name = preprocess_name(name) or name
    if schema.name in ("LegalEntity", "Organization", "Company", "PublicBody"):
        name = replace_org_types_compare(name, normalizer=preprocess_name)
    elif schema.name in ("LegalEntity", "Person"):
        name = remove_person_prefixes(name)
    return tokenize_name(name)


def phonetic_names(schema: Schema, names: list[str]) -> set[str]:
    """Generate phonetic forms of the given names."""
    phonemes: set[str] = set()
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


def index_name_parts(schema: Schema, names: list[str]) -> set[str]:
    """Generate a list of indexable name parts from the given names."""
    parts: set[str] = set()
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


def clean_percolator_names(names: list[str]) -> list[str]:
    """Drop names that are too noisy to percolate.

    - Multi-token names are always kept (specific enough for phrase matching).
    - Single-token names are kept only when their length is at least
      `settings.percolator_single_token_min_length` (default 10) **and**
      the input list contains no multi-token variant. Short single-token
      names (e.g. "John", "Khan") match too much arbitrary prose even
      with BM25 downweighting; even longer single tokens are skipped
      whenever a more specific multi-token phrase is available, since
      that phrase already covers any document mentioning the bare name.
    - Empty / whitespace-only entries are dropped.
    """
    min_single = settings.percolator_single_token_min_length
    cleaned: set[str] = set()
    single_tokens: set[str] = set()
    for name in names:
        stripped = (name or "").strip()
        if not stripped:
            continue
        tokens = stripped.split()
        if len(tokens) > 1:
            cleaned.add(stripped)
        elif len(stripped) >= min_single:
            single_tokens.add(stripped)
    if cleaned:  # multi-token variants present → drop bare singles
        return list(cleaned)
    return list(single_tokens)


NAME_BOOST = 2.0
OTHER_NAME_BOOST = 0.8


def make_percolator_query(
    names: list[str],
    other_names: list[str] | None = None,
) -> dict[str, Any] | None:
    """Build a stored percolator query from name signals.

    Signals come from three separate lists, each producing its own
    `match_phrase` clauses with a distinct `_name` tag (so downstream
    can tell via `matched_queries` which signal fired):

    - `names` — primary names (`name` property). Boosted by `NAME_BOOST`
      (2.0) so canonical-name matches rank highest. Tagged `_name="name"`.
    - `other_name` — secondary name signals (`previousName`, `alias`).
      Demoted by `OTHER_NAME_BOOST` (0.8). Tagged `_name="other_name"`.

    Net ranking tier: name (2.0) > other_name (0.8).

    Names use `match_phrase` with `slop: 2` — tolerant of inserted
    middle initials (`"Jane Doe"` matches `"Jane A. Doe"`), reversed
    last-name-first variants (`"Doe, Jane"`), and small token gaps.
    Performance is essentially the same as `slop: 1`; both fall off
    the `index_phrases` shingle fast path that `slop: 0` uses, and the
    slop value only affects a constant-time budget check at match time.

    All cleaned values become clauses — there is no cap. OpenSanctions-
    style entities with many language variants or aliases produce many
    clauses per stored query, which favours recall (every variant a
    document might use is matchable). `PercolatorQuery` preserves BM25
    scoring, so more matching clauses and rarer/longer phrases bubble
    up naturally; the name-vs-previous split just tilts that ranking
    toward canonical names when both match.

    Returns `None` if every cleaned list is empty, in which case the
    caller should NOT add a percolator field to the entity (so the entity
    stays out of the percolator candidate set).
    """
    cleaned_names = clean_percolator_names(names)
    cleaned_others = clean_percolator_names(other_names or [])
    if not cleaned_names and not cleaned_others:
        return None

    shoulds: list[dict[str, Any]] = []
    for n in cleaned_names:
        shoulds.append(
            {
                "match_phrase": {
                    Field.CONTENT: {
                        "query": n,
                        "slop": 2,
                        "boost": NAME_BOOST,
                        "_name": "name",
                    }
                }
            }
        )
    for n in cleaned_others:
        shoulds.append(
            {
                "match_phrase": {
                    Field.CONTENT: {
                        "query": n,
                        "slop": 2,
                        "boost": OTHER_NAME_BOOST,
                        "_name": "other_name",
                    }
                }
            }
        )
    return {"bool": {"minimum_should_match": 1, "should": shoulds}}


def index_name_keys(schema: Schema, names: list[str]) -> set[str]:
    """Generate a indexable name keys from the given names."""
    keys: set[str] = set()
    for name in names:
        tokens = clean_tokenize_name(schema, name)
        ascii_tokens: list[str] = []
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
