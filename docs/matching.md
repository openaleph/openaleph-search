# Entity Matching

Find similar entities across datasets by comparing names, identifiers, and properties. The matching system helps identify potential duplicates and related entities using sophisticated name processing and multiple comparison strategies.

## Quick Start

### Basic Usage

```python
from openaleph_search.query.queries import MatchQuery
from openaleph_search.parse.parser import SearchQueryParser

# Create entity to match against
entity = make_entity({
    "id": "person-123",
    "schema": "Person",
    "properties": {
        "name": ["John Smith"],
        "nationality": ["us"],
        "email": ["john@example.com"]
    }
})

# Find similar entities
parser = SearchQueryParser([])
query = MatchQuery(parser, entity)
result = query.search()
```

### Common Use Cases

```bash
# Find similar companies
/search?facet_significant=names  # Use with company entities

# Cross-language matching via name symbols
# "Vladimir Putin" matches "Владимир Путин"

# Sound-alike matching via phonetic encoding
# "Smith" matches "Smythe"
```

## Name Field Types

OpenAleph-Search uses four different name field types for comprehensive matching:

### 1. `name` - Original Entity Names

**Field Type:** `text`
**Purpose:** Exact entity names and captions as they appear in source data

```python
# Example values
"name": ["John Smith", "Mr. John Smith", "J. Smith"]
```

**Characteristics:**

- Preserves original formatting and punctuation
- Used for full-text search with boosting (`^4` in search)
- Analyzed with ICU tokenizer for Unicode support
- Stored for highlighting display

### 2. `names` - Normalized Name Keywords

**Field Type:** `keyword` with `name-kw-normalizer`
**Purpose:** Normalized keywords for exact matching and aggregation

```python
# Example transformation
"John Smith & Associates Ltd." → "john smith associates ltd"
```

**Normalization Process:**

- Convert to lowercase
- Remove special characters and HTML
- Collapse multiple spaces
- ASCII folding for diacritics

**Usage:**

- Facet aggregation
- Exact name matching with fuzziness
- High boost factor (`^3` in search)

### 3. `name_symbols` - Name Symbols from Rigour.Names

**Field Type:** `keyword`
**Purpose:** Symbolic representations for cross-language matching

Name symbols are generated using the [Rigour Names](http://rigour.followthemoney.tech/names/) library, which creates standardized symbolic representations:

```python
# Example symbol generation
"Vladimir Putin" → [NAME:47200243]
"Владимир Путин" → [NAME:47200243] # Same symbol!
```

**Features:**

- Cross-language entity matching
- Consistent symbols for name variants
- Language-independent matching
- Generated from entity names using `ftmq.util.get_name_symbols()`

### 4. `name_phonetic` - Metaphone Phonetic Encoding

**Field Type:** `keyword`
**Purpose:** Sound-alike matching using Double Metaphone algorithm

```python
# Example phonetic encoding
"Smith" → "SM0"
"Smythe" → "SM0"  # Same phonetic code
"John" → "JN"
"Jon" → "JN"      # Same phonetic code
```

**Implementation Details:**
- Uses `rigour.text.metaphone` for encoding
- Minimum 3 character tokens
- Only modern alphabet characters
- ASCII conversion before phonetic encoding
- Boost factor of `0.8` (lower than exact matching)

## Name Processing Pipeline

The name processing pipeline in `openaleph_search/transform/util.py` handles multiple transformation stages:

### 1. Name Preprocessing (`preprocess_name`)

```python
def preprocess_name(name: str) -> str:
    """Preprocess a name for comparison."""
    name = unicodedata.normalize("NFC", name)  # Unicode normalization
    name = name.lower()                        # Lowercase conversion
    return collapse_spaces(name)               # Space normalization
```

### 2. Schema-Aware Tokenization (`clean_tokenize_name`)

Different processing based on entity schema:

```python
# Organization names
if schema.name in ("Organization", "Company", "PublicBody"):
    name = replace_org_types_compare(name)  # "Corp" → "Corporation"

# Person names
elif schema.name in ("Person"):
    name = remove_person_prefixes(name)     # "Mr. John" → "John"

return tokenize_name(name)  # Split into tokens
```

### 3. Name Keys Generation (`index_name_keys`)

Creates sortable keys for deduplication:

```python
# Example process
"John A. Smith Jr." → ["john", "smith", "jr"] → "jjrsmith"
```

**Features:**
- Sorted ASCII tokens concatenated
- Minimum 5 characters for indexing
- Used for exact deduplication matching
- Highest boost factor (`4.0`)

### 4. Name Parts Generation (`index_name_parts`)

Individual searchable components:

```python
# Example output
"John Smith & Associates" → ["john", "smith", "associates"]
```

**Features:**
- Individual tokens for partial matching
- ASCII variants for international names
- Minimum 2 characters per part
- Boost factor of `1.0`

### 5. Phonetic Generation (`phonetic_names`)

Creates phonetic representations:

```python
def phonetic_names(schema: Schema, names: List[str]) -> Set[str]:
    phonemes = set()
    for name in names:
        for token in clean_tokenize_name(schema, name):
            if len(token) >= 3 and is_modern_alphabet(token):
                phoneme = metaphone(ascii_text(token))
                if len(phoneme) > 2:
                    phonemes.add(phoneme)
    return phonemes
```

## MatchQuery Implementation

### Basic Usage

```python
from openaleph_search.query.queries import MatchQuery
from openaleph_search.parse.parser import SearchQueryParser

# Create entity to match against
entity = make_entity({
    "id": "person-123",
    "schema": "Person",
    "properties": {
        "name": ["John Smith"],
        "nationality": ["us"],
        "email": ["john@example.com"]
    }
})

# Find similar entities
parser = SearchQueryParser([])
query = MatchQuery(parser, entity)
result = query.search()
```

### Name-Based Matching Strategy

The `names_query` function creates a comprehensive search strategy:

```python
def names_query(schema: Schema, names: list[str]) -> Clauses:
    shoulds = []

    # 1. Fuzzy matching on normalized names (boost: 3.0)
    for name in pick_names(names, limit=5):
        shoulds.append({
            "match": {
                Field.NAMES: {
                    "query": name,
                    "operator": "AND",
                    "boost": 3.0,
                    "fuzziness": "AUTO"  # Edit distance tolerance
                }
            }
        })

    # 2. Exact name key matching (boost: 4.0)
    for key in index_name_keys(schema, names):
        shoulds.append({
            "term": {Field.NAME_KEYS: {"value": key, "boost": 4.0}}
        })

    # 3. Name parts matching (boost: 1.0)
    for token in index_name_parts(schema, names):
        shoulds.append({
            "term": {Field.NAME_PARTS: {"value": token, "boost": 1.0}}
        })

    # 4. Phonetic matching (boost: 0.8)
    for phoneme in phonetic_names(schema, names):
        shoulds.append({
            "term": {Field.NAME_PHONETIC: {"value": phoneme, "boost": 0.8}}
        })

    # 5. Symbol matching (no boost - exact match)
    for symbol in get_name_symbols(schema, *names):
        shoulds.append({
            "term": {Field.NAME_SYMBOLS: str(symbol)}
        })

    return shoulds
```

### Name Selection Algorithm (`pick_names`)

To prevent query explosion with entities having many aliases, the system intelligently selects representative names:

```python
def pick_names(names: list[str], limit: int = 3) -> list[str]:
    # 1. Pick centroid name (most representative)
    picked_name = registry.name.pick(names)

    # 2. Pick most dissimilar names using Levenshtein distance
    for _ in range(1, limit):
        candidates = {}
        for cand in names:
            if cand not in picked:
                # Calculate total distance from already picked names
                candidates[cand] = sum(levenshtein(pick, cand) for pick in picked)

        # Select name with maximum distance (most unique)
        pick = max(candidates, key=candidates.get)
        picked.append(pick)

    return picked
```

## Identifier Matching

Beyond names, the system matches on entity identifiers:

```python
def identifiers_query(entity: EntityProxy) -> Clauses:
    shoulds = []
    for prop, value in entity.itervalues():
        if prop.type.group == registry.identifier.group:
            shoulds.append({
                "term": {
                    f"properties.{prop.name}": {
                        "value": value,
                        "boost": 3.0
                    }
                }
            })
    return shoulds
```

**Identifier Types:**
- Registration numbers
- Tax identifiers
- Passport numbers
- License numbers
- Other unique identifiers

## Property-Based Scoring

Additional properties provide scoring signals:

### High-Specificity Match Groups

Properties with high matching value (boost: `2.0`):

```python
MATCH_GROUPS = [
    registry.ip.group,     # IP addresses
    registry.url.group,    # URLs
    registry.email.group,  # Email addresses
    registry.phone.group,  # Phone numbers
]
```

### General Property Scoring

Other properties contribute to similarity score without boosting:

```python
# Properties sorted by specificity
filters = sorted(filters, key=lambda p: p[2], reverse=True)

# Add to query based on specificity
for type_, value, specificity in filters:
    if specificity > 0 and num_clauses <= MAX_CLAUSES:
        if type_.group not in MATCH_GROUPS:
            scoring.append({
                "term": {type_.group: {"value": value}}
            })
```

## Schema Compatibility

Matching respects entity schema compatibility:

```python
def get_index(self):
    # Only match within compatible schema types
    schemata = list(self.entity.schema.matchable_schemata)
    return entities_read_index(schema=schemata)
```

**Examples:**
- `Person` can match `Person` or `LegalEntity`
- `Company` can match `Company`, `Organization`, or `LegalEntity`
- `Document` cannot match entities (not matchable)
- `RealEstate` is unmatchable (even similar properties don't indicate same entity)

## Query Structure

A complete match query combines multiple strategies:

```python
{
    "bool": {
        "must": [
            {
                "bool": {
                    "should": [
                        # Name-based matching clauses
                        {"match": {"names": {"query": "john smith", "boost": 3.0}}},
                        {"term": {"name_keys": {"value": "johnsmith", "boost": 4.0}}},
                        {"term": {"name_parts": {"value": "john", "boost": 1.0}}},
                        {"term": {"name_phonetic": {"value": "JN", "boost": 0.8}}},
                        {"term": {"name_symbols": "[NAME:12345]"}}
                    ],
                    "minimum_should_match": 1
                }
            },
            {
                "bool": {
                    "should": [
                        # Identifier-based matching
                        {"term": {"properties.passportNumber": {"value": "A1234567", "boost": 3.0}}}
                    ],
                    "minimum_should_match": 0
                }
            }
        ],
        "should": [
            # Property-based scoring
            {"term": {"emails": {"value": "john@example.com", "boost": 2.0}}},
            {"term": {"countries": {"value": "us"}}}
        ],
        "must_not": [
            {"ids": {"values": ["person-123"]}}  # Exclude self
        ],
        "filter": [
            {"terms": {"dataset": ["allowed_datasets"]}}
        ]
    }
}
```

## Performance Considerations

### Query Complexity Limits

```python
MAX_CLAUSES = 500  # Prevent query explosion
```

The system limits total query clauses to prevent performance degradation with entities having many properties.

### Name Selection Optimization

- Limits to 5 most representative names
- Uses Levenshtein distance for diversity
- Prevents queries with hundreds of name variants

### Schema-Specific Processing

Different tokenization and normalization for:
- **Organizations**: Company type normalization
- **Persons**: Prefix removal
- **General entities**: Standard processing

## Function Score Integration

Match results use function scoring to boost important entities:

```python
{
    "function_score": {
        "query": match_query,
        "functions": [{
            "field_value_factor": {
                "field": "num_values",
                "factor": 0.5,
                "modifier": "sqrt"
            }
        }],
        "boost_mode": "sum"
    }
}
```

This ensures entities with more complete information rank higher.

## Usage Examples

### Basic Entity Matching

```python
# Find similar companies
company = make_entity({
    "schema": "Company",
    "properties": {
        "name": ["Acme Corporation"],
        "country": ["us"],
        "registrationNumber": ["12345"]
    }
})

query = MatchQuery(SearchQueryParser([]), company)
results = query.search()
```

### Filtered Matching

```python
# Find matches within specific datasets
parser = SearchQueryParser([
    ("filter:dataset", "companies_dataset")
])
query = MatchQuery(parser, entity, datasets=["companies_dataset"])
```

### Cross-Language Matching

```python
# Entities with different language names but same symbols
entity1 = {"name": ["Vladimir Putin"]}      # → [NAME:47200243]
entity2 = {"name": ["Владимир Путин"]}      # → [NAME:47200243]
# Will match via name_symbols field
```

## Testing and Validation

The matching system includes comprehensive tests:

```python
def test_matching():
    # Same name, different properties
    jane_us = make_entity("Person", "Jane Doe", nationality="us")
    jane_mt = make_entity("Person", "Jane Doe", nationality="mt")

    # Similar names with diacritics
    jane_plain = make_entity("Person", "Jane Doe", email="jane@foo.local")
    jane_diacritic = make_entity("Person", "Jane Dö", email="jane@foo.local")

    # Test matching finds similar entities
    query = MatchQuery(parser, jane_us)
    results = query.search()
    # Should find jane_mt, jane_plain, jane_diacritic
```

The tests verify matching across name variants, diacritics, and property combinations while respecting schema compatibility constraints.

---

## Technical Implementation

### Overview

Entity matching is implemented through the `MatchQuery` class in `openaleph_search/query/queries.py:86` and the `match_query` function in `openaleph_search/query/matching.py:103`. The system uses multiple name representations and property comparisons to find similar entities with high precision.

### Implementation Details

The matching system provides:
- **Multi-field Name Processing**: Four different name representations for comprehensive matching
- **Smart Name Selection**: Prevents query explosion using Levenshtein distance selection
- **Schema Compatibility**: Only matches within compatible entity types
- **Performance Limits**: MAX_CLAUSES (500) prevents complex query issues

### Implementation Location

Entity matching logic is in:
- `openaleph_search/query/matching.py:103` - Core matching algorithm
- `openaleph_search/query/queries.py:86` - MatchQuery class
- `openaleph_search/transform/util.py` - Name processing utilities
- `openaleph_search/query/matching.py:29` - Name selection algorithm
