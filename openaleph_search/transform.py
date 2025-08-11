"""
Transform an EntityProxy to a search document
"""

from followthemoney import EntityProxy
from rigour.names import Name, tag_person_name
from rigour.names.tokenize import normalize_name


def make_symbols(entity: EntityProxy) -> set[str]:
    symbols: set[str] = set()
    if not entity.schema.is_a("Person"):
        return symbols
    for name in entity.names:
        for symbol in tag_person_name(Name(name), normalize_name).symbols:
            symbols.add(str(symbol.id))
    return symbols
