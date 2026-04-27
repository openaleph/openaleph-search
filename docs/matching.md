# Entity Matching

Find similar entities across datasets to identify duplicates and related records. This is inspired and partly adopted from the great open source work by [OpenSanctions](https://github.com/opensanctions).

[Read more in this OpenSanctions blog post](https://www.opensanctions.org/articles/2025-06-24-name-matching/)

[Blog post for OpenAleph](https://openaleph.org/blog/2025/09/A-Look-Inside-OpenAleph-5's-ElasticSearch-Improvements/412bfb6e-63ec-4d84-80f5-a1a3ace91520/)

## How it works

Entity matching compares multiple signals:

1. Names (with normalization and phonetic encoding)
2. Identifiers (registration numbers, tax IDs, etc.)
3. Properties (email, phone, address, etc.)

The index stores multiple name representations to catch variations:

- Normalized keywords (`names`)
- Heavier normalized name keywords (`name_keys`)
- Name symbols (cross-language and cross-alphabet matching) (`name_symbols`)
- Phonetic codes (sound-alike matching) (`name_phonetics`)
- Name parts (partial matching) (`name_parts`)


## Configuration

Matching stages 1 (normalized keywords) and 2 (name keys) are always enabled. Stages 3-5 can be toggled via environment variables:

| Setting | Default | Stage |
|---------|---------|-------|
| `OPENALEPH_SEARCH_MATCH_NAME_PARTS` | `true` | Name parts (partial token overlap) |
| `OPENALEPH_SEARCH_MATCH_PHONETIC` | `false` | Phonetic encoding (sound-alike) |
| `OPENALEPH_SEARCH_MATCH_SYMBOLS` | `false` | Name symbols (cross-language) |

Enabling more stages improves recall (finding more potential matches) at the cost of query complexity and performance. For most use cases, stages 1 and 2 provide sufficient matching quality.

```bash
# Enable all matching stages
export OPENALEPH_SEARCH_MATCH_NAME_PARTS=true
export OPENALEPH_SEARCH_MATCH_PHONETIC=true
export OPENALEPH_SEARCH_MATCH_SYMBOLS=true
```

## Name matching strategies

### 1. Normalized keywords

Names are normalized and matched as exact keywords (after normalization).

Example:
```
"John Smith & Associates Ltd." → "john smith associates ltd"
```

Normalization:
- Lowercase conversion
- Special character removal
- Whitespace collapsing
- Diacritic folding

Exact name matches (with order preserved) receive the highest boost.

### 2. Name symbols {: #name-symbols }

!!! note
    Disabled by default. Enable with `OPENALEPH_SEARCH_MATCH_SYMBOLS=true`.

Cross-language and cross-alphabet matching via symbolic representations. This can be considered as a synonyms search, but more precise and context specific than [a global synonyms file](https://www.elastic.co/docs/solutions/search/full-text/search-with-synonyms).

This uses [`rigour.names`](https://rigour.followthemoney.tech/names/). The example symbol used here from wikidata: [Vladimir](https://www.wikidata.org/wiki/Q47200243)

The extracted symbols are indexed in the `name_symbols` keyword field.

Example:
```
"Vladimir Putin" → [NAME:47200243]
"Владимир Путин" → [NAME:47200243]
```

Same symbol = same entity name (part) across languages.

### 3. Phonetic encoding {: #phonetic }

!!! note
    Disabled by default. Enable with `OPENALEPH_SEARCH_MATCH_PHONETIC=true`.

Sound-alike matching using Double Metaphone algorithm.

The phonetic representations are indexed in the `name_phonetics` keyword field.

Example:
```
"Smith" → "SM0"
"Smythe" → "SM0"
```

Catches alternate spellings and transcription variations.

### 4. Name parts {: #name-parts }

Individual name components for partial matching.

Index field: `name_parts` (keyword)

Example:
```
"John Smith & Associates" → ["john", "smith", "associates"]
```

Matches entities sharing name components.

### 5. Name keys

Sorted token concatenation for order-independent matching.

Index field: `name_keys` (keyword)

Example:
```
"John A. Smith Jr." → "jjrsmith"
"Smith John Jr. A." → "jjrsmith"
```

Matches names containing the same tokens regardless of order.


## Identifier matching

Exact matching on unique identifiers:

- Registration numbers
- Tax IDs
- Passport numbers
- License numbers
- Other unique codes

Identifiers have high matching weight (boost: 3.0).

## Property matching

Additional signals from entity properties:

### High-value properties (boost: 2.0)

- IP addresses
- URLs
- Email addresses
- Phone numbers

### General properties

All other properties contribute to similarity score without boosting.

Properties are sorted by specificity - more unique values score higher.

## Schema compatibility

Matching respects entity type compatibility:

- `Person` matches `Person` and `LegalEntity`
- `Company` matches `Company`, `Organization`, and `LegalEntity`
- Some other entity schemata like `Document` are not matchable

Only compatible schema types can match each other.

## Scoring

Match scores combine multiple factors:

| Signal | Boost | Index field | Default |
|--------|-------|-------------|---------|
| Names (exact, order preserved) | 5.0 | `names` | always |
| Name keys (order-independent) | 3.0 | `name_keys` | always |
| Identifiers | 3.0 | `properties.*` (for group type "identifier") | always |
| High-value properties | 2.0 | `properties.*` (ip, url, email, phone) | always |
| Name parts | 1.0 | `name_parts` | always |
| Other properties | 1.0 | `properties.*` | always |
| Phonetic codes | 0.8 | `name_phonetics` | opt-in |
| Name symbols | 0.8 | `name_symbols` | opt-in |

Higher boost = more important for matching.

## Performance limits

To prevent query explosion:

- Maximum 500 query clauses
- Maximum 5 names used per entity
- Names selected by diversity (Levenshtein distance)

Entities with many aliases use representative names only.

## Name selection

Two stages run in sequence before any name flows into a query clause:

### 1. `clean_matching_names` (shared cleaner, recall mode)

Both `match_query` and `blocking_query` run the entity's matchable names through `openaleph_search.transform.util:clean_matching_names` with `discard_single_token=False`. In this mode the cleaner only drops empty / whitespace-only entries and de-duplicates — short single tokens, long single tokens, and singles shadowed by a multi-token variant all flow through. Returns a `set[str]` so callers can rely on uniqueness without re-deduping.

This is intentionally looser than the percolator / mentions paths: matching scores against the normalized name fields (`names`, `name_keys`, `name_phonetic`, `name_symbols`) rather than arbitrary fulltext prose, so an alias like `"VP"` is a useful candidate-expansion signal rather than the noise it would be in a `match_phrase` against a news article. The percolator and mention paths use the default `discard_single_token=True` mode (the threshold + shadow rules described in [Percolation → Signal cleaning](./percolation.md#signal-cleaning)).

### 2. `pick_names` (budget cap)

See `openaleph_search.query.matching:pick_names`. The cleaner's output then flows through `pick_names`, which budgets the number of names submitted to the index for cheap candidate retrieval:

1. Pick a centroid name (`registry.name.pick`).
2. Pick the most dissimilar remaining names using Levenshtein distance.
3. Cap at 5 names total.

For alias-rich entities (sanctions data with many spellings) `pick_names` does the diversification work; for typical entities with a handful of names it's a no-op (input ≤ cap).

## Query structure

A match query combines multiple strategies:

```json
{
  "bool": {
    "must": [
      {
        "bool": {
          "should": [
            // Name matching clauses (using terms queries for efficiency)
            {"terms": {"names": ["john smith"], "boost": 5.0}},
            {"terms": {"name_keys": ["johnsmith"], "boost": 3.0}},
            // Optional stages (disabled by default, enable via settings):
            {"terms_set": {"name_parts": {"terms": ["john", "smith"], "minimum_should_match_script": {...}}}},   // match_name_parts
            {"terms_set": {"name_phonetic": {"terms": ["JN", "SM0"], "minimum_should_match_script": {...}}}},    // match_phonetic
            {"terms_set": {"name_symbols": {"terms": ["[NAME:12345]"], "minimum_should_match_script": {...}}}}   // match_symbols
          ],
          "minimum_should_match": 1
        }
      },
      {
        "bool": {
          "should": [
            // Identifier matching
            {"term": {"properties.registrationNumber": "ABC123"}}
          ],
          "minimum_should_match": 0
        }
      }
    ],
    "should": [
      // Property scoring
      {"term": {"emails": "john@example.com"}},
      {"term": {"countries": "us"}}
    ]
  }
}
```

For name_parts, phonetics, and symbols, `terms_set` queries require at least 2 matching terms to reduce false positives.

## Optimization tips

### For better matching

- Include multiple name variants when available
- Provide identifiers (registration numbers, tax IDs)
- Add email, phone, address properties
- Specify country/jurisdiction

### For performance

- Filter by dataset to reduce search space
- Filter by schema to search specific entity types
- Use specific identifiers to narrow results

## Name processing pipeline

Names go through multiple processing stages:

- Unicode normalization (NFC), lowercase (if latinizable)
- Schema-specific tokenization
- Token sorting (for name keys)
- Phonetic encoding (for phonetic field)
- Symbol generation (for cross-language and cross-alphabet)

Each stage creates different search representations optimized for specific matching scenarios.
