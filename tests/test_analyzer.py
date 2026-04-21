from openaleph_search.core import get_es
from openaleph_search.index.indexes import schema_index
from openaleph_search.search.logic import analyze_text
from openaleph_search.settings import Settings

settings = Settings()


def test_mapping_analyzer():
    def _get_tokens(res) -> set[str]:
        return {t["token"] for t in res["tokens"]}

    es = get_es()
    index = schema_index("LegalEntity", settings.index_write)
    tokens = _get_tokens(
        es.indices.analyze(index=index, field="name", text="Vladimir Putin")
    )
    assert tokens == {"vladimir", "putin"}
    tokens = _get_tokens(
        es.indices.analyze(index=index, field="names", text="Vladimir Putin")
    )
    assert tokens == {"vladimir putin"}

    # Test names field with punctuation and numbers - should preserve numbers, remove punctuation
    tokens = _get_tokens(
        es.indices.analyze(index=index, field="names", text="Agent 007!")
    )
    assert tokens == {"agent 007"}

    tokens = _get_tokens(
        es.indices.analyze(index=index, field="names", text="John O'Connor-Smith & Co.")
    )
    assert tokens == {"john o connor smith co"}

    # content field with ICU and html strip
    tokens = _get_tokens(
        es.indices.analyze(
            index=index, field="content", text="Владимир Владимирович Путин"
        )
    )
    assert tokens == {"владимир", "путин", "владимирович"}
    tokens = _get_tokens(
        es.indices.analyze(
            index=index, field="content", text="hello <h1 class='foo'>Félix!</h1>"
        )
    )
    assert tokens == {"hello", "felix"}
    # text field with squash spaces, html strip
    tokens = _get_tokens(
        es.indices.analyze(
            index=index, field="text", text="hello \t <h1 class='foo'>Félix!  </h1>"
        )
    )
    assert tokens == {"hello", "felix"}

    # e.g. bodyText property with html
    tokens = _get_tokens(
        es.indices.analyze(
            index=index,
            field="properties.bodyText",
            text="hello \t <h1 class='foo'>Félix!  </h1>",
        )
    )
    assert tokens == {"class", "félix", "hello", "foo", "h1"}


def test_analyze_text_function():
    """Test the analyze_text helper function"""

    def _get_tokens(res) -> set[str]:
        return {t["token"] for t in res["tokens"]}

    # Test with field parameter (full response)
    res = analyze_text("Vladimir Putin", field="content")
    tokens = _get_tokens(res)
    assert tokens == {"vladimir", "putin"}

    # Test with different field (full response)
    res = analyze_text("Agent 007!", field="names")
    tokens = _get_tokens(res)
    assert tokens == {"agent 007"}

    # Test with tokens_only=True
    tokens = analyze_text("Vladimir Putin", field="content", tokens_only=True)
    assert tokens == {"vladimir", "putin"}
    assert isinstance(tokens, set)

    # Test tokens_only with duplicate tokens
    tokens = analyze_text("hello world hello", field="text", tokens_only=True)
    assert tokens == {"hello", "world"}
    assert len(tokens) == 2  # Only unique tokens


ZWJ = "\u200d"


def test_annotated_text_latin():
    """Annotation markers land at the same position as surface words (Latin)."""
    es = get_es()
    index = schema_index("LegalEntity", settings.index_write)
    text = (
        f"Hello Jane{ZWJ}__PER__{ZWJ}__doejane__ Doe{ZWJ}__PER__{ZWJ}__doejane__ here"
    )
    res = es.indices.analyze(index=index, field="content", text=text)
    by_pos = {}
    for t in res["tokens"]:
        by_pos.setdefault(t["position"], set()).add(t["token"])
    assert by_pos[0] == {"hello"}
    assert by_pos[1] == {"jane", "__per__", "__doejane__"}
    assert by_pos[2] == {"doe", "__per__", "__doejane__"}
    assert by_pos[3] == {"here"}


def test_annotated_text_cross_script():
    """Annotation markers land at same position even for Cyrillic surface text."""
    es = get_es()
    index = schema_index("LegalEntity", settings.index_write)
    text = f"Владимир{ZWJ}__PER__{ZWJ}__putin__ Путин{ZWJ}__PER__{ZWJ}__putin__"
    res = es.indices.analyze(index=index, field="content", text=text)
    by_pos = {}
    for t in res["tokens"]:
        by_pos.setdefault(t["position"], set()).add(t["token"])
    assert "владимир" in by_pos[0]
    assert "__per__" in by_pos[0]
    assert "__putin__" in by_pos[0]
    assert "путин" in by_pos[1]
    assert "__per__" in by_pos[1]


def test_annotated_text_surface_phrase_preserved():
    """Surface words remain adjacent — phrase queries work across annotations."""
    es = get_es()
    index = schema_index("LegalEntity", settings.index_write)
    text = f"Владимир{ZWJ}__PER__{ZWJ}__putin__ Путин{ZWJ}__PER__{ZWJ}__putin__"
    res = es.indices.analyze(index=index, field="content", text=text)
    positions = {}
    for t in res["tokens"]:
        positions[t["token"]] = t["position"]
    # Surface words at adjacent positions (0, 1) — no gap from annotations
    assert positions["путин"] - positions["владимир"] == 1


def test_annotated_text_icu_folding():
    """icu_folding normalizes accented surface words; annotations pass through."""
    es = get_es()
    index = schema_index("LegalEntity", settings.index_write)
    text = f"Café{ZWJ}__PLACE__{ZWJ}__cafe__"
    res = es.indices.analyze(index=index, field="content", text=text)
    by_pos = {}
    for t in res["tokens"]:
        by_pos.setdefault(t["position"], set()).add(t["token"])
    assert by_pos[0] == {"cafe", "__place__", "__cafe__"}


def test_annotated_text_plain_passthrough():
    """Plain text without annotations tokenizes normally."""
    es = get_es()
    index = schema_index("LegalEntity", settings.index_write)
    res = es.indices.analyze(
        index=index, field="content", text="Vladimir Putin is here"
    )
    tokens = [t["token"] for t in res["tokens"]]
    assert tokens == ["vladimir", "putin", "is", "here"]
