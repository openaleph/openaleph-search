# Annotated Fulltext

Entity annotations allow you to embed structured entity markers directly into document fulltext. Annotation tokens are indexed at the *same Lucene positions* as the surface words they annotate, enabling proximity-based queries that combine free-text and entity-type/identity predicates.

## Use case

Given a document:

> Serious crime involving **Jane Doe** at **Acme Corp**

You want to search for "crime near any person" – not just "crime" near the literal string "Jane Doe", but crime near *any* person-typed entity mention. Annotations make this possible.

## How it works

### Preprocessing (upstream)

[The document processing pipeline](https://openaleph.org/docs/lib/ftm-analyze/) emits annotated text in `indexText` using the `\u200d` (Zero-Width Joiner) delimiter and `__X__` annotation syntax:

```
serious crime involving Jane‍__PER__‍__doejane__ Doe‍__PER__‍__doejane__ at Acme‍__LTD__‍__acmecorp__ Corp‍__LTD__‍__acmecorp__
```

Where `‍` is the ZWJ character (`\u200d`).

**Rules:**

- Each surface word that belongs to an annotated entity span carries the annotation markers, joined by ZWJ characters.
- Markers use the `__NAME__` syntax: `__PER__`, `__LTD__`, `__PEP__` for entity types, and `__doejane__`, `__acmecorp__` for normalized entity identifiers.
- Markers are **repeated at every surface word** of the span, not just the first or last. This ensures proximity queries work regardless of which surface word the query aligns to.
- Text without annotations passes through unchanged – there is zero overhead for non-annotated documents.

### Indexing

The analyzer chain processes the annotated text:

1. **`html_strip` char_filter** – strips HTML markup.
2. **`standard` tokenizer** – splits on whitespace and punctuation. The ZWJ keeps `Jane‍__PER__‍__doejane__` as a single token across any script.
3. **`ann_capture` filter** (`pattern_capture`) – splits on ZWJ into same-position terms: `jane`, `__per__`, `__doejane__` – all at the same Lucene position.
4. **`lowercase`** + **`icu_folding`** – Unicode normalization. Accented surface words get folded (e.g. `Café` → `cafe`); annotation markers pass through (already lowercase ASCII).

**Resulting token stream:**

| Position | Terms                                     |
|----------|-------------------------------------------|
| 0        | `serious`                                 |
| 1        | `crime`                                   |
| 2        | `involving`                               |
| 3        | `jane`, `__per__`, `__doejane__`          |
| 4        | `doe`, `__per__`, `__doejane__`           |
| 5        | `at`                                      |
| 6        | `acme`, `__ltd__`, `__acmecorp__`         |
| 7        | `corp`, `__ltd__`, `__acmecorp__`         |

Surface words remain adjacent (`jane` at 3, `doe` at 4) – phrase queries on the original text still work. Annotation markers sit at the same positions as their surface words, enabling proximity queries between annotations and surrounding context.

## Query examples

### Proximity: crime near any person

The core use case – find "crime" within 5 words of any person annotation:

```
"crime __PER__"~5
```

### Proximity: specific entity near a context word

Find "president" near normalized name Acme Corp:

```
"president __acmecorp__"~3
```

### Combine annotation with free-text

Find documents that mention Acme Corp AND contain the word "crime":

```
__acmecorp__ AND crime
```

### Regular text search (unaffected)

Plain text searches work exactly as before:

```
"jane doe is involved"
```

Phrase queries are unaffected because annotation tokens occupy the same positions as surface words – they don't push surface words apart.

## Cross-script support

The `standard` tokenizer (unlike the ICU tokenizer) does **not** split at Unicode script boundaries. This means annotations on Cyrillic, Arabic, or other non-Latin surface text work at the same positions:

```
Владимир‍__PER__‍__putin__ Путин‍__PER__‍__putin__
```

Produces:

| Position | Terms                                     |
|----------|-------------------------------------------|
| 0        | `владимир`, `__per__`, `__putin__`        |
| 1        | `путин`, `__per__`, `__putin__`           |

Proximity queries like `"преступление __PER__"~5` work across scripts.

## Annotation format reference

| Component | Format | Example | Description |
|-----------|--------|---------|-------------|
| Delimiter | `\u200d` (ZWJ) | – | Joins surface word to its annotations |
| Entity type | `__TYPE__` | `__PER__`, `__LTD__`, `__PEP__` | Schema/category of the entity |
| Entity ID | `__id__` | `__doejane__`, `__acmecorp__` | Normalized entity identifier |

A fully annotated token:

```
surface‍__TYPE__‍__entityid__
```

Example with multi-word entity name:

```
Jane‍__PER__‍__doejane__ Doe‍__PER__‍__doejane__
```

Both surface words carry identical annotations.

## Why not the `annotated_text` plugin?

The Elasticsearch [`annotated_text`](https://www.elastic.co/docs/reference/elasticsearch/plugins/mapper-annotated-text) plugin disables `index_phrases`, which **openaleph-search** relies on for fast phrase queries. The plugin injects annotation tokens via a custom `TokenFilter` that emits terms at position increment 0 – this conflicts with the shingle generation that `index_phrases` depends on.

Our approach uses `pattern_capture` to split a pre-joined token, which the shingle generator handles correctly because it only sees the first term at each position for phrase-pair construction.

## Index cost

Typical entity surfaces are 1-4 tokens. Each annotated word adds 2-3 additional terms at the same position. Postings compression handles repeated terms efficiently – cost scales with number of entity mentions, not document size.
