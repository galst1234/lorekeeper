from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class SkillMeta:
    fn: Callable[[str], str]
    title: str = field(default="")
    description: str = field(default="")


SKILLS: dict[str, SkillMeta] = {}


def _register(
    name: str,
    title: str = "",
    description: str = "",
) -> Callable[[Callable[[str], str]], Callable[[str], str]]:
    def decorator(fn: Callable[[str], str]) -> Callable[[str], str]:
        SKILLS[name] = SkillMeta(fn=fn, title=title, description=description)
        return fn

    return decorator


def dispatch(name: str, args: str) -> str:
    """Look up and invoke a skill by name, or return an error message."""
    if name not in SKILLS:
        return f"Unknown skill: /{name}. Available skills: {sorted(SKILLS)}"
    return SKILLS[name].fn(args)


@_register(
    "chores",
    title="/chores [Adventure Log Title]",
    description="Process an adventure log: create characters, inject links, add calendar entry, update quests",
)
def chores_skill(args: str) -> str:
    """Return the adventure log processing workflow prompt for the given title."""
    title = args.strip()
    if not title:
        return "Usage: /chores <Adventure Log Title>"
    return (
        f"You are currently working on the chores workflow for: {title}.\n"
        f'Do NOT ask the user which page to process — it is already specified as "{title}". '
        "Complete all 5 steps below in order for this exact page. "
        "Regardless of how many confirmation turns occur, always continue with the next pending step. "
        "When the user explicitly approves a proposed action (replies 'yes' or equivalent), "
        "that approval covers execution — do not re-ask for confirmation inside the tool call; "
        "proceed directly to calling the tool. "
        "If the user declines or skips a specific action within a step (e.g. skipping a character, "
        "stopping a retry), that applies only to that action — continue with the remaining steps "
        "of the chores workflow.\n\n"
        'After each step completes, announce "✓ Step N complete — moving to Step N+1" '
        "and immediately begin the next step (unless that step requires a confirmation).\n\n"
        "**Step 1 — Fetch the page**\n"
        f'Call `fetch_wiki_pages_tool` to find the page with title "{title}". '
        "Then call `fetch_wiki_page_tool` with the resolved page ID to get the full body text.\n\n"
        "**Step 2 — Character check**\n"
        "Call `fetch_characters_tool` to get all known characters. Scan the adventure log body "
        "for named characters. For each name not found in the character list: "
        "search `qdrant-find` using that name to gather all mentions across campaign content "
        "(full name, role, bio details, relationships). "
        "Compile everything found into ONE complete proposal per character "
        "(name, description, bio, tagline, tags) — do not propose a stub and refine later. "
        "Present all proposals together, wait for approval, then create each approved character.\n\n"
        "**Step 3 — Link injection**\n"
        "Call `inject_adventure_log_links_tool` with the page ID. "
        "When passing entity_links to the tool, targets must be bare values only: "
        ":slug for characters (e.g. :keldor-weavegrave), plain page title for wiki pages "
        "(e.g. High Hall, the). Never pass [[ ]], | or any wiki-link syntax as a target — "
        "the tool wraps targets itself. "
        "Show the user the proposed pairs before calling the tool, wait for approval, then inject. "
        "If the tool reports that some links were skipped (already linked or text not found), "
        "accept that result — do not retry, do not debug, do not ask about skipped links. "
        "Note what was skipped and immediately move to Step 4.\n\n"
        "**Step 4 — Calendar entry**\n"
        "Extract the in-game date from the adventure log body. "
        "Call `fetch_calendar_entries_tool` for that date to check whether the entry already exists. "
        f'If "{title}" is already listed on that date, announce "Step 4 skipped — already on calendar" '
        "and move to Step 5. Otherwise show the user the proposed entry "
        f'("Add {title} to <Month> <day>, <year>?"), wait for explicit approval, then add.\n\n'
        "**Step 5 — Quest log**\n"
        "Call `fetch_quests_tool` to get the current quest log. "
        "Read the full quest list carefully. For each topic in the adventure log, check whether any "
        "existing quest already covers it — even under a different name or framing. "
        "Only propose creating a quest if no existing quest covers that thread. "
        "Only propose updating a quest if the session adds meaningful new information not already in it. "
        "If nothing needs to change, state that clearly and skip. "
        "Otherwise show the user all proposed changes together, wait for approval, then execute.\n\n"
        "After completing all 5 steps, provide a brief summary of everything that was created or updated. "
        "At the very end of your summary, include the exact text [SKILL_COMPLETE] on its own line."
    )
