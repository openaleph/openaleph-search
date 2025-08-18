import itertools
import unicodedata
from functools import lru_cache
from typing import List, Optional, Set

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

log = get_logger(__name__)


def get_geopoints(entity: EntityProxy) -> list[dict[str, str]]:
    """Get lon/lat pairs for indexing to `geo_point` field"""
    points = []
    lons = entity.get("longitude", quiet=True)
    lats = entity.get("latitude", quiet=True)
    for lon, lat in itertools.product(lons, lats):
        points.append({"lon": lon, "lat": lat})
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
