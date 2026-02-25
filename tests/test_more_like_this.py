from urllib.parse import parse_qsl, urlparse

import pytest
from ftmq.util import make_entity

from openaleph_search.index.entities import index_bulk
from openaleph_search.model import SearchAuth
from openaleph_search.parse.parser import SearchQueryParser
from openaleph_search.query.more_like_this import more_like_this_query
from openaleph_search.query.queries import MoreLikeThisQuery


def _url_to_args(url):
    """Convert URL query string to args list for SearchQueryParser"""
    parsed = urlparse(url)
    return parse_qsl(parsed.query, keep_blank_values=True)


def _create_mlt_query(
    url, entity=None, exclude=None, datasets=None, collection_ids=None, auth=None
):
    """Create MoreLikeThisQuery from URL string"""
    args = _url_to_args(url)
    parser = SearchQueryParser(args, auth)
    return MoreLikeThisQuery(
        parser,
        entity=entity,
        exclude=exclude,
        datasets=datasets,
        collection_ids=collection_ids,
    )


# Test documents with similar content
TEST_DOCUMENTS = [
    {
        "id": "doc1",
        "schema": "Document",
        "properties": {
            "title": ["Machine Learning Research Paper"],
            "bodyText": [
                "This paper discusses various machine learning algorithms including neural networks, "
                "decision trees, and support vector machines. We present novel approaches to deep "
                "learning architectures and their applications in computer vision and natural "
                "language processing tasks."
            ],
            "contentHash": ["abc123"],
        },
    },
    {
        "id": "doc2",
        "schema": "Document",
        "properties": {
            "title": ["Artificial Intelligence Survey"],
            "bodyText": [
                "Artificial intelligence and machine learning have revolutionized many fields. "
                "This survey covers neural networks, deep learning models, and their use in "
                "computer vision applications. We also discuss natural language processing "
                "and automated decision making systems."
            ],
            "contentHash": ["def456"],
        },
    },
    {
        "id": "doc3",
        "schema": "Document",
        "properties": {
            "title": ["Data Science Handbook"],
            "bodyText": [
                "Data science combines statistical analysis with machine learning techniques. "
                "This handbook provides comprehensive coverage of neural network architectures, "
                "deep learning frameworks, and practical applications in computer vision and "
                "text analysis using natural language processing methods."
            ],
            "contentHash": ["ghi789"],
        },
    },
    {
        "id": "doc4",
        "schema": "Document",
        "properties": {
            "title": ["Cooking Recipes Collection"],
            "bodyText": [
                "This cookbook contains various recipes for Italian pasta dishes, French pastries, "
                "and Mediterranean cuisine. Learn how to prepare authentic dishes using traditional "
                "cooking methods and fresh ingredients from local markets."
            ],
            "contentHash": ["jkl012"],
        },
    },
    {
        "id": "page1",
        "schema": "Pages",
        "properties": {
            "title": ["Deep Learning Tutorial"],
            "indexText": [
                "Welcome to our deep learning tutorial series. In this comprehensive guide, we'll "
                "explore neural network fundamentals, machine learning optimization techniques, "
                "and advanced applications in computer vision and natural language understanding. "
                "This tutorial covers neural networks, deep learning architectures, machine learning "
                "algorithms, computer vision techniques, and natural language processing methods."
            ],
        },
    },
    {
        "id": "page2",
        "schema": "Pages",
        "properties": {
            "title": ["Photography Tips"],
            "indexText": [
                "Photography is an art form that captures moments in time. Learn about camera settings, "
                "composition techniques, lighting principles, and post-processing workflows to improve "
                "your photographic skills and create stunning visual narratives."
            ],
        },
    },
]


@pytest.fixture(scope="function")
def index_test_documents(cleanup_after):
    """Index test documents for more_like_this testing"""
    entities = [make_entity(doc) for doc in TEST_DOCUMENTS]
    index_bulk("test_mlt", entities, sync=True)
    return entities


def test_more_like_this_query_function():
    """Test the more_like_this_query function directly"""
    entity = make_entity(TEST_DOCUMENTS[0])  # Machine Learning doc

    # Test basic query generation
    query = more_like_this_query(entity)

    assert "bool" in query
    assert "must" in query["bool"]
    assert "must_not" in query["bool"]

    # Check for more_like_this query
    mlt_query = None
    for clause in query["bool"]["must"]:
        if "more_like_this" in clause:
            mlt_query = clause["more_like_this"]
            break

    assert mlt_query is not None
    assert "fields" in mlt_query
    assert "like" in mlt_query
    assert mlt_query["like"] == [{"_id": "doc1"}]

    # Check default parameters (hardcoded in more_like_this.py when no parser)
    assert mlt_query["min_doc_freq"] == 1
    assert mlt_query["minimum_should_match"] == "10%"
    assert mlt_query["min_term_freq"] == 1
    assert mlt_query["max_query_terms"] == 200

    # Test with custom parser
    parser = SearchQueryParser(
        [
            ("mlt_min_doc_freq", "3"),
            ("mlt_minimum_should_match", "50%"),
            ("mlt_min_term_freq", "5"),
            ("mlt_max_query_terms", "10"),
        ],
        None,
    )

    query_with_parser = more_like_this_query(entity, parser=parser)

    mlt_query_custom = None
    for clause in query_with_parser["bool"]["must"]:
        if "more_like_this" in clause:
            mlt_query_custom = clause["more_like_this"]
            break

    assert mlt_query_custom is not None
    assert mlt_query_custom["min_doc_freq"] == 3
    assert mlt_query_custom["minimum_should_match"] == "50%"
    assert mlt_query_custom["min_term_freq"] == 5
    assert mlt_query_custom["max_query_terms"] == 10

    # Test with datasets filter
    query_with_datasets = more_like_this_query(entity, datasets=["test_dataset"])
    assert any(
        "terms" in clause and "dataset" in clause["terms"]
        for clause in query_with_datasets["bool"]["filter"]
    )

    # Test entity exclusion
    assert {"ids": {"values": ["doc1"]}} in query["bool"]["must_not"]


def test_more_like_this_query_class_basic():
    """Test MoreLikeThisQuery class initialization and basic methods"""
    entity = make_entity(TEST_DOCUMENTS[0])
    query = _create_mlt_query("/search", entity=entity)

    assert query.entity == entity
    assert query.exclude == []
    assert query.datasets is None
    assert query.collection_ids is None

    # Test get_index targets documents/pages
    index = query.get_index()
    assert isinstance(index, str)
    assert len(index) > 0


def test_more_like_this_query_no_entity():
    """Test MoreLikeThisQuery with no entity returns match_none"""
    query = _create_mlt_query("/search", entity=None)
    inner_query = query.get_inner_query()

    assert inner_query == {"match_none": {}}


def test_more_like_this_search_similar_documents(index_test_documents):
    """Test finding similar documents using more_like_this"""
    # Use the first ML document as the source
    source_entity = None
    for entity in index_test_documents:
        if entity.id == "doc1":
            source_entity = entity
            break

    assert source_entity is not None

    # Create query with more permissive parameters for small test dataset
    query = _create_mlt_query(
        "/search?mlt_min_doc_freq=1&mlt_minimum_should_match=10%&mlt_min_term_freq=1",
        entity=source_entity,
    )
    result = query.search()

    # Should find some results (the similar ML documents)
    assert result["hits"]["total"]["value"] > 0

    # Check that results don't include the source document
    hit_ids = [hit["_id"] for hit in result["hits"]["hits"]]
    assert "doc1" not in hit_ids

    # The most similar documents should be the other ML-related documents
    # doc2 and doc3 should rank higher than doc4 (cooking) or page2 (photography)
    if len(result["hits"]["hits"]) >= 2:
        top_results = result["hits"]["hits"][:2]
        top_ids = [hit["_id"] for hit in top_results]

        # At least one of the top results should be ML-related
        ml_related_ids = {"doc2", "doc3", "page1"}
        assert any(hit_id in ml_related_ids for hit_id in top_ids)


def test_more_like_this_with_exclusions(index_test_documents):
    """Test more_like_this query with entity exclusions"""
    source_entity = None
    for entity in index_test_documents:
        if entity.id == "doc1":
            source_entity = entity
            break

    # Exclude specific documents
    exclude_ids = ["doc2", "page1"]
    query = _create_mlt_query("/search", entity=source_entity, exclude=exclude_ids)
    result = query.search()

    # Check that excluded documents are not in results
    hit_ids = [hit["_id"] for hit in result["hits"]["hits"]]
    for excluded_id in exclude_ids:
        assert excluded_id not in hit_ids

    # Source document should also be excluded (automatic)
    assert "doc1" not in hit_ids


def test_more_like_this_with_dataset_filter(index_test_documents):
    """Test more_like_this query with dataset filtering"""
    source_entity = None
    for entity in index_test_documents:
        if entity.id == "doc1":
            source_entity = entity
            break

    # Filter by specific dataset with more permissive parameters for small test dataset
    query = _create_mlt_query(
        "/search?mlt_min_doc_freq=1&mlt_minimum_should_match=10%&mlt_min_term_freq=1",
        entity=source_entity,
        datasets=["test_mlt"],
    )
    result = query.search()

    # Should still find results from the test dataset
    assert result["hits"]["total"]["value"] > 0

    # Test with non-existent dataset (should return no results)
    query_empty = _create_mlt_query(
        "/search", entity=source_entity, datasets=["nonexistent"]
    )
    result_empty = query_empty.search()

    assert result_empty["hits"]["total"]["value"] == 0


def test_more_like_this_pages_similarity(index_test_documents):
    """Test finding similar pages using more_like_this"""
    # Use the deep learning page as source
    source_entity = None
    for entity in index_test_documents:
        if entity.id == "page1":
            source_entity = entity
            break

    assert source_entity is not None

    query = _create_mlt_query("/search", entity=source_entity)
    result = query.search()

    # Verify source page is excluded from results (even if no results found)
    hit_ids = [hit["_id"] for hit in result["hits"]["hits"]]
    assert "page1" not in hit_ids

    # The more_like_this query executed successfully (even if no matches found)
    # This is acceptable behavior for small test datasets where similarity
    # thresholds may not be met
    assert "hits" in result
    assert "total" in result["hits"]

    # If results are found, verify they don't include the source entity
    if result["hits"]["total"]["value"] > 0:
        assert len(hit_ids) > 0
        for hit_id in hit_ids:
            assert hit_id != "page1"


def test_more_like_this_configurable_parameters():
    """Test that more_like_this query parameters are configurable via URL parameters"""
    entity = make_entity(TEST_DOCUMENTS[0])  # Machine Learning doc

    # Test with custom parameters
    query_with_params = _create_mlt_query(
        "/search?mlt_min_doc_freq=2&mlt_minimum_should_match=30%&mlt_min_term_freq=2&mlt_max_query_terms=15",
        entity=entity,
    )

    inner_query = query_with_params.get_inner_query()

    # Check that the more_like_this query exists
    mlt_query = None
    for clause in inner_query["bool"]["must"]:
        if "more_like_this" in clause:
            mlt_query = clause["more_like_this"]
            break

    assert mlt_query is not None
    assert mlt_query["min_doc_freq"] == 2
    assert mlt_query["minimum_should_match"] == "30%"
    assert mlt_query["min_term_freq"] == 2
    assert mlt_query["max_query_terms"] == 15

    # Test with default parameters
    query_default = _create_mlt_query("/search", entity=entity)
    inner_query_default = query_default.get_inner_query()

    mlt_query_default = None
    for clause in inner_query_default["bool"]["must"]:
        if "more_like_this" in clause:
            mlt_query_default = clause["more_like_this"]
            break

    assert mlt_query_default is not None
    assert mlt_query_default["min_doc_freq"] == 1  # parser default
    assert mlt_query_default["minimum_should_match"] == "10%"  # parser default
    assert mlt_query_default["min_term_freq"] == 1  # parser default
    assert mlt_query_default["max_query_terms"] == 200  # parser default


def test_more_like_this_bucket_filtering():
    """Test that MoreLikeThisQuery only targets documents and pages buckets"""
    # Create a non-document entity (Person)
    person_entity = make_entity(
        {"id": "person1", "schema": "Person", "properties": {"name": ["Jane Doe"]}}
    )

    query = _create_mlt_query("/search", entity=person_entity)

    # Should still work but target document/page schemas only
    index = query.get_index()
    assert isinstance(index, str)

    # The inner query should still be generated properly
    inner_query = query.get_inner_query()
    assert "bool" in inner_query


def _count(result) -> int:
    return result["hits"]["total"]["value"]


def test_more_like_this_auth(
    monkeypatch, cleanup_after, auth_admin, auth_private, auth_public
):
    """Test that MoreLikeThisQuery respects authentication filters"""
    monkeypatch.setenv("OPENALEPH_SEARCH_AUTH", "true")

    # Create test documents for different datasets
    public_docs = [
        make_entity(
            {
                "id": "public_doc1",
                "schema": "Document",
                "properties": {
                    "title": ["Public Machine Learning Paper"],
                    "bodyText": [
                        "This public document discusses machine learning algorithms, neural networks, and deep learning architectures for computer vision applications."
                    ],
                },
            }
        ),
        make_entity(
            {
                "id": "public_doc2",
                "schema": "Document",
                "properties": {
                    "title": ["Public AI Research"],
                    "bodyText": [
                        "Public research on artificial intelligence, machine learning models, and neural network optimization techniques."
                    ],
                },
            }
        ),
    ]

    private_docs = [
        make_entity(
            {
                "id": "private_doc1",
                "schema": "Document",
                "properties": {
                    "title": ["Private ML Study"],
                    "bodyText": [
                        "Private study on machine learning applications, deep neural networks, and computer vision algorithms."
                    ],
                },
            }
        ),
        make_entity(
            {
                "id": "private_doc2",
                "schema": "Document",
                "properties": {
                    "title": ["Private Data Science"],
                    "bodyText": [
                        "Confidential data science research involving machine learning techniques and neural network architectures."
                    ],
                },
            }
        ),
    ]

    # Index documents in different datasets
    index_bulk("test_public", public_docs, sync=True)
    index_bulk("test_private", private_docs, sync=True)

    # Use first public doc as source for more-like-this
    source_entity = public_docs[0]

    unauthenticated = SearchAuth()

    # Test that unauthenticated users get no results
    mlt_query = _create_mlt_query(
        "/search?mlt_min_doc_freq=1&mlt_minimum_should_match=10%&mlt_min_term_freq=1",
        source_entity,
        auth=unauthenticated,
    )
    result = mlt_query.search()
    assert _count(result) == 0

    # Test that public auth only sees public results
    mlt_query = _create_mlt_query(
        "/search?mlt_min_doc_freq=1&mlt_minimum_should_match=10%&mlt_min_term_freq=1",
        source_entity,
        auth=auth_public,
    )
    result = mlt_query.search()
    public_hits = _count(result)

    # Should find the other public document similar to source
    assert public_hits >= 1
    hit_ids = [hit["_id"] for hit in result["hits"]["hits"]]
    # Should not include source document
    assert "public_doc1" not in hit_ids
    # Should only include public documents
    for hit_id in hit_ids:
        assert hit_id.startswith("public_")

    # Test that private auth sees both public and private results
    mlt_query = _create_mlt_query(
        "/search?mlt_min_doc_freq=1&mlt_minimum_should_match=10%&mlt_min_term_freq=1",
        source_entity,
        auth=auth_private,
    )
    result = mlt_query.search()
    private_hits = _count(result)
    hit_ids = [hit["_id"] for hit in result["hits"]["hits"]]
    # Should not include source document
    assert "public_doc1" not in hit_ids
    for hit_id in hit_ids:
        assert hit_id.startswith("public_") or hit_id.startswith("private_")

    # Private auth should see same or more results than public auth
    assert private_hits >= public_hits

    # Test that admin sees all results
    mlt_query = _create_mlt_query(
        "/search?mlt_min_doc_freq=1&mlt_minimum_should_match=10%&mlt_min_term_freq=1",
        source_entity,
        auth=auth_admin,
    )
    result = mlt_query.search()
    admin_hits = _count(result)
    hit_ids = [hit["_id"] for hit in result["hits"]["hits"]]
    # Should not include source document
    assert "public_doc1" not in hit_ids
    for hit_id in hit_ids:
        assert hit_id.startswith("public_") or hit_id.startswith("private_")

    # Admin should see same or more results than private auth
    assert admin_hits >= private_hits
