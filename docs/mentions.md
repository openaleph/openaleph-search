# Mentions

Find documents that mention a given named entity by phrase-matching the entity's name variants against the documents bucket.

!!! info "Reverse percolation"
    Where [Percolation](./percolation.md) runs *one document against many stored queries* ("which of my entities are mentioned in this text?"), `MentionsQuery` runs the inverse: *one entity against many stored documents* ("which of my documents mention this entity?"). Same signal – names as phrases in fulltext – applied from the other direction, with no precomputed stored queries involved.

`MentionsQuery` takes the ID of a named entity (Person, Company, Organization, Vessel, …) and returns entities from the Document hierarchy (Document, PlainText, HyperText, Pages, Page, …) whose indexed text contains the entity's caption or any of its matchable name variants as a phrase.

## How it works

At query time, `MentionsQuery` loads the target entity via `get_entity` and extracts its matchable names (`registry.name`, `matchable=True` – typically `name`, `alias`, `previousName` …). It then builds the same shape of search query a user would write against the documents bucket, with a `mention_clause` ANDed into the bool body.

The mention clause is a `bool.should` with `minimum_should_match: 1` combining:

1. **Fulltext phrase match** – one `multi_match` clause per matchable name, with `type: phrase` and `slop: 0`, across the `content` and `text` fields (`text` boosted down to `0.8`). Phrase matching is strict: it finds the name as a contiguous token sequence in the document's fulltext.
2. **Structured-name bonus** – a `terms` clause over `Field.NAMES` (keyword) across all matchable name variants, boosted to `2.0`. This catches documents that carry the entity's name as an extracted property value (`names` group) rather than only as free text.
3. **Optional synonym expansion** – when `parser.synonyms=true`, two extra clauses are added via `ExpandNameSynonymsMixin` (shared with `EntitiesQuery`): a `terms` clause over `Field.NAME_SYMBOLS` from the entity's NAME-category symbols (boost `0.5`), and a `terms` clause over `Field.NAME_KEYS` from `index_name_keys` of the entity's names (boost `0.3`). Mirrors the user-text synonyms path in `EntitiesQuery.get_text_query` – same fields, same boosts – but derives keys directly from the entity's discrete names rather than n-gramming user query tokens.

The mention clause is ANDed (`bool.must`) with the rest of the query built by `EntitiesQuery` – `parser.text`, filters, negative filters, auth – so `parser.text` narrows mention hits instead of replacing them.

### Default schema scope

Default `schemata` is `["Document"]` (not `["Thing"]` as in `EntitiesQuery`), which covers Document and all its descendants. The index resolver uses the Document-hierarchy buckets (`documents`, `pages`, `page`) accordingly. A caller-supplied `filter:schema` or `filter:schemata` overrides it – e.g. `filter:schema=Pages` to scope to page entities only.

### Sort and highlights

- **Sort.** When no explicit `sort` is passed, `MentionsQuery` forces `_score` rather than falling back to `_doc`. The mention clause carries all the scoring signal even when `parser.text` is empty, so the base "empty query → no ranking" heuristic would hide the best hits. An explicit `sort` from the parser still wins.
- **Highlights.** With `highlight=true`, highlight configs for `content`, `text`, and `translation` have their `highlight_query` replaced with the same phrase shoulds used by the mention clause (merged with any filter-value clauses the base class added). Without this, an empty `parser.text` would make the highlighter fall back to `match_all` and emit unmarked `no_match_size` snippets.

## Querying

There is no dedicated CLI subcommand – `MentionsQuery` is a programmatic API.

```python
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.queries import MentionsQuery

parser = SearchQueryParser([("highlight", "true"),
                            ("limit", "50")])
query = MentionsQuery(parser, entity_id="person-abc")
result = query.search()

for hit in result["hits"]["hits"]:
    doc = hit["_source"]
    print(doc["caption"], "→", hit.get("highlight", {}).get("content", []))
```

Standard parser knobs flow through automatically:

- `filter:*` – applied as filters on the document search (`filter:dataset`, `filter:countries`, `filter:schema=Pages`, …).
- `q=…` – free-text narrowing that ANDs with the mention requirement (e.g. "documents that mention this person *and* contain the word 'invoice'").
- `synonyms=true` – opt-in symbol / name-key expansion of the entity's names (see above).
- `highlight=true` + `highlight_count=N` – fragment snippets with `<em>…</em>` markup around matched phrases, same shape as `EntitiesQuery` highlights.
- `limit` / `offset` – pagination.
- `sort` – overrides the default `_score` sort.
- `dehydrate=true` – strips bulky `properties` from the response.
- `auth` – same auth filters as any other entity query.

### Errors

`MentionsQuery(parser, entity_id=...)` raises `ValueError` if:

- `entity_id` is falsy.
- The entity is not found in the index.
- The entity has no matchable names (`registry.name`, `matchable=True`). A Document or a nameless schema cannot be the subject of a mentions search – there is nothing to phrase-match on.

## Limits and trade-offs

### Recall is bounded by the entity's stored names

The mention clause is built from the entity's matchable name properties only. Variants the entity doesn't know about won't match a document: a PDF that says `"Müller"` against an entity stored only as `"Mueller"` will not fire unless `synonyms=true` lifts them into the same name-symbol / name-key bucket.

If recall matters, either enrich the entity with aliases / `previousName` values, or opt in to `synonyms=true`.

### Phrase matching is strict

`multi_match` phrase clauses use `slop: 0` – the tokens must appear contiguously and in order. Unlike the percolator's name clause (which uses `slop: 2` to tolerate middle initials and reversed name order), the mentions path does not tolerate insertions or reordering in the fulltext. Store order-independent variants explicitly as aliases if that matters for your data.

### No identifier signal

The percolator also fires on exact identifier matches (IMO, VAT, registration numbers, …). `MentionsQuery` does *not* – it is name-only. If you need identifier-based document discovery, run a plain `EntitiesQuery` with the identifier value as free text, or build a dedicated query against `Field.IDENTIFIERS`.

### Document hierarchy only

Results are scoped to the Document bucket family by default. Things (Person, Company, …) and Intervals (Ownership, Sanction, …) are not searched – they have no meaningful fulltext for a mention clause to fire against. The subject entity itself, which lives in the things bucket, is naturally absent from results.

### One entity per query

`MentionsQuery` takes a single `entity_id`. To screen a batch of entities, issue parallel requests and merge client-side. (If you need the opposite direction – *one text, many entities* – use [Percolation](./percolation.md) instead.)
