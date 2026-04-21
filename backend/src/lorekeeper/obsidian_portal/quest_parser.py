"""
Parse and render the Obsidian Portal Quest Log wiki page.

The page body uses custom accordion markup. This module handles:
- Parsing the body into structured Quest objects
- Serialising back to the original markup format
- Inserting and updating quests with move-between-sections support

Round-trip invariant: render_body(parse_body(raw)) == raw
(verify against the live page before deployment; adjust _render_item whitespace if needed)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lorekeeper.obsidian_portal.models import Quest, QuestStatus, QuestType

# ── Sentinels ──────────────────────────────────────────────────────────────────
_HIDDEN_SENTINEL = "\x00HIDDEN\x00"
_SLIDESHOW_SENTINEL = "\x00SLIDESHOW\x00"

# ── Compiled patterns ──────────────────────────────────────────────────────────
HIDDEN_DIV_RE = re.compile(r'<div\s+style="visibility:\s*hidden;">.*?</div>', re.DOTALL)
SLIDESHOW_RE = re.compile(r"\[slideshow\].*?\[end-slideshow\]", re.DOTALL)
COMPLETED_BOUNDARY_RE = re.compile(r"(h2\. Completed Quests\s*\n?)")
H3_RE = re.compile(r'(<h3 class="quests">(.+?)</h3>)')
ITEM_RE = re.compile(
    r"\[accordion-item\]\s*"
    r'\[title\]<div class="(open|completed|failed)">(.+?)</div>\[end-title\]\s*'
    r"\[content\](.*?)\[end-content\]\s*"
    r"\[end-accordion-item\]",
    re.DOTALL,
)
ACCORDION_RE = re.compile(r"\[accordion\](.*?)\[end-accordion\]", re.DOTALL)

QUEST_TYPE_NAMES = {"Main Quests", "Side Quests"}
QUEST_TYPE_MAP = {"Main Quests": "Main Quest", "Side Quests": "Side Quest"}
QUEST_TYPE_HEADER_MAP = {"Main Quest": "Main Quests", "Side Quest": "Side Quests"}


# ── Internal dataclasses ───────────────────────────────────────────────────────
@dataclass
class SubSection:
    quest_type: str | None  # "Main Quest" | "Side Quest" | None
    header_html: str | None  # original <h3> tag, or None
    quests: list[Quest] = field(default_factory=list)
    # Round-trip fields
    raw_pre: str = ""  # text between h3 (or section start) and [accordion]
    raw_inner: str | None = None  # None = no accordion block; str = inner accordion content
    raw_post: str = ""  # text after [end-accordion]
    dirty: bool = False  # True when quests have been mutated


@dataclass
class PhaseBlock:
    header_html: str  # original <h3> tag
    phase_name: str
    sub_sections: list[SubSection] = field(default_factory=list)
    raw_personal: str | None = None  # verbatim content for Personal Quests phase
    header_suffix: str = ""  # text after phase h3 and before first sub-header h3


@dataclass
class ParsedBody:
    pre_active: str
    active_phases: list[PhaseBlock]
    completed_header: str
    completed_phases: list[PhaseBlock]
    hidden_template: str  # full <div style="visibility: hidden;">...</div>
    slideshow: str = ""  # verbatim [slideshow]...[end-slideshow] content
    post_hidden: str = ""  # text after the hidden template


# ── Item rendering ─────────────────────────────────────────────────────────────
def _render_item(quest: Quest) -> str:
    return (
        "[accordion-item]\n"
        f'[title]<div class="{quest.status}">{quest.title}</div>[end-title]\n'
        f"[content]{quest.content}[end-content]\n"
        "[end-accordion-item]"
    )


# ── Sub-section rendering ──────────────────────────────────────────────────────
def _render_sub(sub: SubSection) -> str:
    parts: list[str] = []
    if sub.header_html:
        parts.append(sub.header_html)
    parts.append(sub.raw_pre)

    if sub.dirty:
        # Re-render accordion from quest objects
        if sub.quests:
            inner = "\n" + "\n".join(_render_item(q) for q in sub.quests) + "\n"
            parts.append(f"[accordion]{inner}[end-accordion]")
        # If quests emptied, omit accordion entirely
    elif sub.raw_inner is not None:
        # Preserve original accordion content verbatim
        parts.append(f"[accordion]{sub.raw_inner}[end-accordion]")

    parts.append(sub.raw_post)
    return "".join(parts)


# ── Phase rendering ────────────────────────────────────────────────────────────
def _render_phase(phase: PhaseBlock) -> str:
    result = phase.header_html
    if phase.raw_personal is not None:
        result += phase.raw_personal
    else:
        result += phase.header_suffix
        for sub in phase.sub_sections:
            result += _render_sub(sub)
    return result


# ── Item parsing ───────────────────────────────────────────────────────────────
def _parse_items(inner: str, phase_name: str, quest_type: str | None) -> list[Quest]:
    quests = []
    for m in ITEM_RE.finditer(inner):
        quests.append(
            Quest(
                title=m.group(2),
                content=m.group(3),
                status=m.group(1),  # type: ignore[arg-type]
                phase=phase_name,
                quest_type=quest_type,  # type: ignore[arg-type]
            ),
        )
    return quests


# ── Sub-section parsing ────────────────────────────────────────────────────────
def _parse_sub_raw(raw: str, phase_name: str, quest_type: str | None, *, header_html: str | None) -> SubSection:
    m = ACCORDION_RE.search(raw)
    if m:
        pre = raw[: m.start()]
        inner = m.group(1)
        post = raw[m.end() :]
        quests = _parse_items(inner, phase_name, quest_type)
    else:
        pre = raw
        inner = None
        post = ""
        quests = []
    return SubSection(
        quest_type=quest_type,
        header_html=header_html,
        quests=quests,
        raw_pre=pre,
        raw_inner=inner,
        raw_post=post,
    )


# ── Half parsing ───────────────────────────────────────────────────────────────
def _parse_half(text: str) -> tuple[str, list[PhaseBlock]]:
    """Parse one section half (active or completed) into (pre_text, phases)."""
    parts = H3_RE.split(text)
    # Layout: [pre, full_h3_0, name_0, content_0, full_h3_1, name_1, content_1, ...]
    pre = parts[0]
    phases: list[PhaseBlock] = []
    current_phase: PhaseBlock | None = None

    i = 1
    while i < len(parts):
        full_h3 = parts[i]
        name = parts[i + 1]
        content = parts[i + 2]
        i += 3

        if name == "Personal Quests":
            # Store verbatim; the slideshow sentinel is already inside content
            phase = PhaseBlock(header_html=full_h3, phase_name=name, raw_personal=content)
            phases.append(phase)
            current_phase = phase

        elif name in QUEST_TYPE_NAMES:
            # Sub-type header belonging to the current phase
            qt = QUEST_TYPE_MAP[name]
            if current_phase is None:
                # Edge case: orphaned sub-header; wrap in a synthetic phase
                current_phase = PhaseBlock(header_html="", phase_name="")
                phases.append(current_phase)
            sub = _parse_sub_raw(content, current_phase.phase_name, qt, header_html=full_h3)
            current_phase.sub_sections.append(sub)

        else:
            # New phase header
            phase = PhaseBlock(header_html=full_h3, phase_name=name)
            phases.append(phase)
            current_phase = phase

            if ACCORDION_RE.search(content):
                # Phase with a direct accordion (no sub-type headers)
                sub = _parse_sub_raw(content, name, None, header_html=None)
                phase.sub_sections.append(sub)
            else:
                # Whitespace before upcoming sub-type headers
                phase.header_suffix = content

    return pre, phases


# ── Public API ─────────────────────────────────────────────────────────────────
def _protect_regions(raw: str) -> tuple[str, str, str]:
    """Replace hidden div and slideshow with sentinels. Returns (raw, hidden_template, slideshow)."""
    m = HIDDEN_DIV_RE.search(raw)
    if m:
        hidden_template = m.group(0)
        raw = raw[: m.start()] + _HIDDEN_SENTINEL + raw[m.end() :]
    else:
        hidden_template = ""

    m = SLIDESHOW_RE.search(raw)
    if m:
        slideshow = m.group(0)
        raw = raw[: m.start()] + _SLIDESHOW_SENTINEL + raw[m.end() :]
    else:
        slideshow = ""

    return raw, hidden_template, slideshow


def parse_body(raw: str) -> ParsedBody:
    """Parse the quest log wiki page body into a structured ParsedBody."""

    # Steps 1-2: protect hidden div and slideshow with sentinels
    raw, hidden_template, slideshow = _protect_regions(raw)

    # Step 3: split active / completed halves
    split = COMPLETED_BOUNDARY_RE.split(raw, maxsplit=1)
    active_raw, completed_header, rest = split if len(split) > 1 else (split[0], "", "")

    # Isolate the hidden-template sentinel at the end of the completed half
    if _HIDDEN_SENTINEL in rest:
        hidden_idx = rest.index(_HIDDEN_SENTINEL)
        completed_raw = rest[:hidden_idx]
        post_hidden = rest[hidden_idx + len(_HIDDEN_SENTINEL) :]
    else:
        completed_raw = rest
        post_hidden = ""

    # Step 4: parse each half
    pre_active, active_phases = _parse_half(active_raw)
    _, completed_phases = _parse_half(completed_raw)

    return ParsedBody(
        pre_active=pre_active,
        active_phases=active_phases,
        completed_header=completed_header,
        completed_phases=completed_phases,
        hidden_template=hidden_template,
        slideshow=slideshow,
        post_hidden=post_hidden,
    )


def render_body(parsed: ParsedBody) -> str:
    """Serialise a ParsedBody back to the wiki page body string."""
    parts: list[str] = [parsed.pre_active]
    for phase in parsed.active_phases:
        parts.append(_render_phase(phase))
    parts.append(parsed.completed_header)
    for phase in parsed.completed_phases:
        parts.append(_render_phase(phase))
    parts.append(parsed.hidden_template)
    parts.append(parsed.post_hidden)

    result = "".join(parts)
    # Restore protected regions
    if parsed.slideshow:
        result = result.replace(_SLIDESHOW_SENTINEL, parsed.slideshow)
    return result


def extract_quests(parsed: ParsedBody) -> list[Quest]:
    """Flatten all quests from active and completed phases, excluding Personal Quests."""
    quests: list[Quest] = []
    for phase in parsed.active_phases + parsed.completed_phases:
        if phase.raw_personal is not None:
            continue
        for sub in phase.sub_sections:
            quests.extend(sub.quests)
    return quests


# ── Helpers for insert / update ────────────────────────────────────────────────
def _is_active(status: str) -> bool:
    return status == "open"


def _find_quest(
    parsed: ParsedBody,
    title: str,
) -> tuple[Quest, list[PhaseBlock], PhaseBlock, SubSection, int] | None:
    """Return (quest, phases_list, phase, sub, index) or None."""
    for phases in [parsed.active_phases, parsed.completed_phases]:
        for phase in phases:
            if phase.raw_personal is not None:
                continue
            for sub in phase.sub_sections:
                for idx, q in enumerate(sub.quests):
                    if q.title == title:
                        return q, phases, phase, sub, idx
    return None


def _get_or_create_sub(phase: PhaseBlock, quest_type: str | None) -> SubSection:
    for sub in phase.sub_sections:
        if sub.quest_type == quest_type:
            return sub
    # Create new sub-section
    if quest_type is None:
        header_html = None
    else:
        h3_name = QUEST_TYPE_HEADER_MAP[quest_type]
        header_html = f'<h3 class="quests">{h3_name}</h3>'
    new_sub = SubSection(quest_type=quest_type, header_html=header_html, dirty=True)
    phase.sub_sections.append(new_sub)
    return new_sub


def _get_or_create_phase(phases: list[PhaseBlock], phase_name: str) -> PhaseBlock:
    for phase in phases:
        if phase.phase_name == phase_name:
            return phase
    new_phase = PhaseBlock(
        header_html=f'<h3 class="quests">{phase_name}</h3>',
        phase_name=phase_name,
    )
    phases.append(new_phase)
    return new_phase


def insert_quest(parsed: ParsedBody, quest: Quest) -> None:
    """
    Insert a new quest into the parsed body.

    Raises ValueError if a quest with the same title already exists.
    """
    all_titles = {q.title for q in extract_quests(parsed)}
    if quest.title in all_titles:
        raise ValueError(f"A quest named '{quest.title}' already exists.")

    phases = parsed.active_phases if _is_active(quest.status) else parsed.completed_phases
    target_phase = _get_or_create_phase(phases, quest.phase)
    target_sub = _get_or_create_sub(target_phase, quest.quest_type)
    target_sub.quests.append(quest)
    target_sub.dirty = True


def update_quest_data(  # noqa: PLR0913, C901
    parsed: ParsedBody,
    title: str,
    *,
    new_title: str | None = None,
    new_content: str | None = None,
    new_status: QuestStatus | None = None,
    new_phase: str | None = None,
    new_quest_type: QuestType | None = None,
) -> str:
    """
    Find a quest by title and apply updates. Returns a human-readable change summary.

    Raises ValueError if the quest is not found.
    Moving between active/completed sections is handled automatically when status changes.
    """
    found = _find_quest(parsed, title)
    if found is None:
        raise ValueError(f"Quest '{title}' not found.")

    quest, _phases, _old_phase, old_sub, old_idx = found
    changes: list[str] = []
    new_fields: dict = {}

    if new_title is not None and new_title != quest.title:
        changes.append(f"title: '{quest.title}' → '{new_title}'")
        new_fields["title"] = new_title

    if new_content is not None and new_content != quest.content:
        changes.append("content updated")
        new_fields["content"] = new_content

    if new_status is not None and new_status != quest.status:
        changes.append(f"status: {quest.status} → {new_status}")
        new_fields["status"] = new_status

    if new_phase is not None and new_phase != quest.phase:
        changes.append(f"phase: '{quest.phase}' → '{new_phase}'")
        new_fields["phase"] = new_phase

    if new_quest_type is not None and new_quest_type != quest.quest_type:
        changes.append(f"quest_type: {quest.quest_type} → {new_quest_type}")
        new_fields["quest_type"] = new_quest_type

    if not new_fields:
        return "no changes"

    if "title" in new_fields:
        other_titles = {q.title for q in extract_quests(parsed)} - {quest.title}
        if new_fields["title"] in other_titles:
            raise ValueError(f"A quest named '{new_fields['title']}' already exists.")

    updated = quest.model_copy(update=new_fields)

    # Determine if quest must move to a different location
    section_changed = _is_active(quest.status) != _is_active(updated.status)
    location_changed = section_changed or updated.phase != quest.phase or updated.quest_type != quest.quest_type

    if location_changed:
        # Remove from old location
        old_sub.quests.pop(old_idx)
        old_sub.dirty = True
        # Re-insert at new location
        insert_quest(parsed, updated)
    else:
        # In-place update
        old_sub.quests[old_idx] = updated
        old_sub.dirty = True

    return "; ".join(changes)
