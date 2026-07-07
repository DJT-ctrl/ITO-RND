"""Unit tests for exact-duplicate removal (processors/dedup.py)."""

from processors.dedup import dedupe_posts


def _post(post_id: str, content: str, likes: int = 0, comments: int = 0, shares: int = 0) -> dict:
    return {
        "id": post_id,
        "content": content,
        "engagement": {"likes": likes, "comments": comments, "shares": shares},
    }


def test_empty_input_returns_empty_list():
    deduped, num_removed = dedupe_posts([])
    assert deduped == []
    assert num_removed == 0


def test_no_duplicates_is_a_no_op():
    posts = [_post("1", "First post"), _post("2", "Second post")]
    deduped, num_removed = dedupe_posts(posts)
    assert deduped == posts
    assert num_removed == 0


def test_exact_duplicate_keeps_highest_engagement_copy():
    posts = [
        _post("1", "Same content here", likes=10, comments=1, shares=0),
        _post("2", "Same content here", likes=100, comments=20, shares=5),
    ]
    deduped, num_removed = dedupe_posts(posts)
    assert num_removed == 1
    assert [p["id"] for p in deduped] == ["2"]


def test_duplicate_with_surrounding_whitespace_is_still_matched():
    posts = [
        _post("1", "Same content here", likes=5),
        _post("2", "  Same content here  \n", likes=50),
    ]
    deduped, num_removed = dedupe_posts(posts)
    assert num_removed == 1
    assert [p["id"] for p in deduped] == ["2"]


def test_ties_keep_first_seen():
    posts = [
        _post("1", "Tied content", likes=10),
        _post("2", "Tied content", likes=10),
    ]
    deduped, num_removed = dedupe_posts(posts)
    assert num_removed == 1
    assert [p["id"] for p in deduped] == ["1"]


def test_blank_content_posts_are_never_deduped_against_each_other():
    posts = [_post("1", ""), _post("2", "   "), _post("3", "")]
    deduped, num_removed = dedupe_posts(posts)
    assert num_removed == 0
    assert [p["id"] for p in deduped] == ["1", "2", "3"]


def test_preserves_original_order_of_kept_posts():
    posts = [
        _post("1", "Unique A"),
        _post("2", "Dup", likes=1),
        _post("3", "Unique B"),
        _post("4", "Dup", likes=99),
    ]
    deduped, num_removed = dedupe_posts(posts)
    assert num_removed == 1
    assert [p["id"] for p in deduped] == ["1", "3", "4"]
