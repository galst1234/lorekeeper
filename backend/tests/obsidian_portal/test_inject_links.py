"""Tests for inject_links() extracted from obsidian_portal/mcp_server.py."""

import pytest

from lorekeeper.obsidian_portal.link_injector import inject_links

# ── Entity gets injected ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "body,entity_links,expected_link,expected_mention",
    [
        pytest.param(
            "Allandra arrived at the inn with Brandis.",
            {"Allandra": ":allandra-grey"},
            "[[:allandra-grey | Allandra]]",
            "Allandra",
            id="basic-character-link",
        ),
        pytest.param(
            "The goblin attacked first.",
            {"goblin": "Goblin"},
            "[[Goblin | goblin]]",
            "goblin",
            id="case-insensitive",
        ),
        pytest.param(
            "They met the Steel Dragon (inn) on the road.",
            {"Steel Dragon (inn)": "Steel Dragon inn, the"},
            "[[Steel Dragon inn, the | Steel Dragon (inn)]]",
            "Steel Dragon (inn)",
            id="special-regex-chars-in-mention",
        ),
        pytest.param(
            "Allandra arrived.",
            {"Allandra": "[[:allandra-grey]]"},
            "[[:allandra-grey | Allandra]]",
            "Allandra",
            id="brackets-accidentally-included-in-target",
        ),
    ],
)
def test_entity_injected(body: str, entity_links: dict[str, str], expected_link: str, expected_mention: str) -> None:
    new_body, applied, skipped = inject_links(body, entity_links)
    assert expected_link in new_body
    assert expected_mention in applied
    assert skipped == []


# ── Entity gets skipped ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "body,entity_links",
    [
        pytest.param(
            "The party met [[:allandra-grey | Allandra]] at the gate.",
            {"Allandra": ":allandra-grey"},
            id="already-linked",
        ),
        pytest.param(
            "The party explored the dungeon.",
            {"Allandra": ":allandra-grey"},
            id="mention-not-in-text",
        ),
        pytest.param(
            "",
            {"Allandra": ":allandra-grey"},
            id="empty-text",
        ),
    ],
)
def test_entity_skipped(body: str, entity_links: dict[str, str]) -> None:
    new_body, applied, skipped = inject_links(body, entity_links)
    assert new_body == body
    assert applied == []
    assert skipped == list(entity_links.keys())


# ── Unique behaviours ─────────────────────────────────────────────────────────


def test_only_first_occurrence_linked() -> None:
    body = "Allandra spoke. Allandra left. Allandra returned."
    new_body, applied, skipped = inject_links(body, {"Allandra": ":allandra-grey"})
    assert new_body.count("[[:allandra-grey | Allandra]]") == 1
    assert new_body.count("Allandra") == 3  # link text + 2 unlinked occurrences


def test_mention_inside_existing_link_not_double_linked() -> None:
    # First "goblin" is inside [[...]] and protected; second occurrence gets linked.
    body = "[[Some Page | goblin]] attacked and the goblin fled."
    new_body, applied, skipped = inject_links(body, {"goblin": "Goblin"})
    assert "[[Goblin | goblin]]" in new_body
    assert "goblin" in applied


def test_multiple_entities() -> None:
    body = "Allandra and Brandis entered the Rusty Flagon together."
    entity_links = {
        "Allandra": ":allandra-grey",
        "Brandis": ":brandis-springvale",
        "Rusty Flagon": "The Rusty Flagon",
    }
    new_body, applied, skipped = inject_links(body, entity_links)
    assert "[[:allandra-grey | Allandra]]" in new_body
    assert "[[:brandis-springvale | Brandis]]" in new_body
    assert "[[The Rusty Flagon | Rusty Flagon]]" in new_body
    assert len(applied) == 3
    assert skipped == []


def test_empty_entity_links_returns_unchanged() -> None:
    body = "Nothing to link here."
    new_body, applied, skipped = inject_links(body, {})
    assert new_body == body
    assert applied == []
    assert skipped == []


def test_partial_word_mention_not_linked() -> None:
    # "goblin" entity should not match inside "goblins" due to \b boundary logic
    body = "The goblins scattered."
    new_body, applied, skipped = inject_links(body, {"goblin": "Goblin"})
    assert new_body == body
    assert applied == []
    assert "goblin" in skipped
