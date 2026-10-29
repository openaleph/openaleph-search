import pytest

from openaleph_search.settings import Settings


@pytest.mark.parametrize(
    "value,expected",
    [
        ("v1", "v1"),
        ("v1,v2", ["v1", "v2"]),
        (" v1 , v2 ,", ["v1", "v2"]),
        ('["v1","v2"]', ["v1", "v2"]),
        ('["v1"]', ["v1"]),
    ],
)
def test_index_read_from_env(monkeypatch, value, expected):
    monkeypatch.setenv("OPENALEPH_SEARCH_INDEX_READ", value)
    assert Settings().index_read == expected


def test_index_read_from_init():
    assert Settings(index_read="v1,v2").index_read == ["v1", "v2"]
    assert Settings(index_read=["v1", "v2"]).index_read == ["v1", "v2"]
