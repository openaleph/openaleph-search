# Name Synonyms

**openaleph-search** supports search-time name synonym expansion, allowing queries to match across different spellings, transliterations, and language variants of person names.

## How it works

When a user enables synonyms (`?synonyms=true`), the search query is analyzed with a synonym-enabled analyzer that expands name tokens to their known variants. For example, searching for `Vladimir` also matches `Wladimir`, `Владимир`, `فلاديمير`, and dozens of other spellings – all at the same Lucene position, so phrase queries and proximity queries work correctly.

Synonyms are applied **at search time only** – the index is unaffected. This means:

- No reindexing needed when synonyms are updated
- Users can toggle synonyms on/off per query
- Index size is not increased

## Synonym source

The synonym rules are sourced from [rigour](https://rigour.followthemoney.tech/names/), the name normalization library used across the FollowTheMoney ecosystem. The source file maps name spelling variants to Wikidata identifiers:

```
ovsei, ovsej, ovsey, owssej, овсей => Q10000006
igumnov, igumnow => Q10000087
vladimir, vladimirs, wladimir, volodya, владимир, ... => Q2253934
```

The Wikidata identifiers are stripped – only the comma-separated name variants are kept as interchangeable synonyms for Elasticsearch.

**156,000+** synonym rules covering person names across Latin, Cyrillic, Arabic, Greek, CJK, and other scripts.

## Compiling the synonym file

```bash
make synonyms
```

This downloads the latest name variants from the [rigour repository](https://github.com/opensanctions/rigour) and compiles them into `contrib/person_name_synonyms.txt` in Elasticsearch synonym format.

The file is baked into the Elasticsearch Docker image:

```bash
make elastic-build
```

## Query usage

### Enable synonyms

Add `synonyms=true` to the query:

```bash
openaleph-search search query-string "Vladimir Igumnov" --args "synonyms=true"
```

### Without synonyms (default)

```bash
openaleph-search search query-string "Vladimir Igumnov"
```

Only matches documents containing the exact spellings `Vladimir` and `Igumnov`.

### With synonyms

```bash
openaleph-search search query-string "Vladimir Igumnov" --args "synonyms=true"
```

Also matches `Wladimir Igumnow`, `Владимир Игумнов`, and any other known
spelling variant.

## Interaction with other features

### [Highlighting](highlighting.md)

When synonyms are enabled with highlighting (`synonyms=true&highlight=true`), the highlight shows the **actual indexed text**, not the query term. Searching for `Vladimir` matches a document containing `Wladimir`, and the highlight shows `<em>Wladimir</em>`.

### [Annotations](annotations.md)

Synonyms and annotations are independent features that work together. You can combine synonym-expanded name searches with annotation proximity queries:

```
"__PER__ crime"~5
```

With `synonyms=true`, the surface text matching benefits from synonym expansion while annotation markers work as usual.

### Keyword fields

The synonym analyzer expands terms on **text fields** (content, name, text).  For **keyword fields** (`names`, `name_parts`, `name_keys`, `name_symbols`), a separate Python-side expansion via [rigour symbols](https://rigour.followthemoney.tech/names/) is used when synonyms are enabled. Both mechanisms activate together with `?synonyms=true`.

## Technical details

### Analyzer chain

The synonym search analyzer (`icu-search-synonyms`) is defined as:

```
tokenizer: standard
filters:   lowercase → person_name_synonyms (synonym_graph) → icu_folding
```

It is applied at search time only, via the `analyzer` parameter on the `query_string` query – the field's index-time analyzer remains unchanged.

The `synonym_graph` filter type (rather than plain `synonym`) correctly handles multi-token name variants (e.g., CJK names that tokenize into multiple characters).

### Performance

The 156k synonym rules are compiled into a finite state transducer (FST) when the index is created (~14 seconds per index, one-time cost). At search time, FST lookups are O(token_length), not O(num_rules) – synonym expansion adds negligible latency per query.
