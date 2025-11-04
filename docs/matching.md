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


## Name matching strategies

### 1. Normalized keywords

Names are normalized and matched with fuzzy search.

Example:
```
"John Smith & Associates Ltd." → "john smith associates ltd"
```

Normalization:
- Lowercase conversion
- Special character removal
- Whitespace collapsing
- Diacritic folding

### 2. Name symbols

Cross-language and cross-alphabet matching via symbolic representations. This can be considered as a synonyms search, but more precise and context specific than [a global synonyms file](https://www.elastic.co/docs/solutions/search/full-text/search-with-synonyms).

This uses [`rigour.names`](https://rigour.followthemoney.tech/names/). The example symbol used here from wikidata: [Vladimir](https://www.wikidata.org/wiki/Q47200243)

The extracted symbols are indexed in the `name_symbols` keyword field.

Example:
```
"Vladimir Putin" → [NAME:47200243]
"Владимир Путин" → [NAME:47200243]
```

Same symbol = same entity name (part) across languages.

### 3. Phonetic encoding

Sound-alike matching using Double Metaphone algorithm.

The phonetic representations are indexed in the `name_phonetics` keyword field.

Example:
```
"Smith" → "SM0"
"Smythe" → "SM0"
```

Catches alternate spellings and transcription variations.

### 4. Name parts

Individual name components for partial matching.

Index field: `name_parts` (keyword)

Example:
```
"John Smith & Associates" → ["john", "smith", "associates"]
```

Matches entities sharing name components.

### 5. Name keys

Sorted token concatenation for exact deduplication.

Index field: `name_keys` (keyword)

Example:
```
"John A. Smith Jr." → "jjrsmith"
```

Highest matching score when names contain the same tokens.


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

| Signal | Boost | Index field |
|--------|-------|-------------|
| Names | 3.0 | `names` |
| Identifiers | 3.0 | `properties.*` (for group type "identifier") |
| Name keys (exact tokens) | 2.5 | `name_keys` |
| High-value properties | 2.0 | `properties.*` (ip, url, email, phone) |
| Name parts | 1.0 | `name_parts` |
| Name symbols | 1.0 | `name_symbols` |
| Other properties | 1.0 | `properties.*` |
| Phonetic codes | 0.8 | `name_phonetics` |

Higher boost = more important for matching.

## Performance limits

To prevent query explosion:

- Maximum 500 query clauses
- Maximum 5 names used per entity
- Names selected by diversity (Levenshtein distance)

Entities with many aliases use representative names only.

## Name selection

See `openaleph_search.query.matching:pick_names`

For entities with many aliases, the system selects representative names:

1. Pick centroid name (most representative)
2. Pick most dissimilar names using Levenshtein distance
3. Use up to 5 names total

This prevents performance issues while maintaining matching quality.

## Query structure

A match query combines multiple strategies:

```json
{
  "bool": {
    "must": [
      {
        "bool": {
          "should": [
            // Name matching clauses
            {"match": {"names": {"query": "john smith", "fuzziness": "AUTO"}}},
            {"term": {"name_keys": "johnsmith"}},
            {"term": {"name_parts": "john"}},
            {"term": {"name_phonetic": "JN"}},
            {"term": {"name_symbols": "[NAME:12345]"}}
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
