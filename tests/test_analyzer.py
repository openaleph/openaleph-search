from openaleph_search.core import get_es
from openaleph_search.index.indexes import schema_index
from openaleph_search.search.logic import analyze_text


def test_mapping_analyzer():
    def _get_tokens(res) -> set[str]:
        return {t["token"] for t in res["tokens"]}

    es = get_es()
    index = schema_index("LegalEntity", "v1")
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
