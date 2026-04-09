from collections.abc import Callable

SKILLS: dict[str, Callable[[str], str]] = {}


def _register(name: str) -> Callable[[Callable[[str], str]], Callable[[str], str]]:
    def decorator(fn: Callable[[str], str]) -> Callable[[str], str]:
        SKILLS[name] = fn
        return fn

    return decorator


def dispatch(name: str, args: str) -> str:
    """Look up and invoke a skill by name, or return an error message."""
    if name not in SKILLS:
        return f"Unknown skill: /{name}. Available skills: {sorted(SKILLS)}"
    return SKILLS[name](args)


@_register("chores")
def chores_skill(args: str) -> str:
    """Return the adventure log processing workflow prompt for the given title."""
    title = args.strip()
    if not title:
        return "Usage: /chores <Adventure Log Title>"
    return (
        f'You are processing the adventure log entry titled "{title}". '
        "Follow these steps in sequence. Use the standard verify-confirm-execute pattern "
        "for each write operation. Do not skip any step.\n\n"
        "**Step 1 — Fetch the page**\n"
        f'Call `fetch_wiki_pages_tool` to find the page with title "{title}". '
        "Then call `fetch_wiki_page_tool` with the resolved page ID to get the full body text.\n\n"
        "**Step 2 — Character check**\n"
        "Call `fetch_characters_tool` to get all known characters. Scan the adventure log body "
        "for named characters. For each character mentioned in the text that does NOT appear in "
        "the known characters list, follow the `create_character_tool` workflow: verify the "
        "character does not exist, show the user the proposed name and any inferred details, "
        "wait for explicit approval, then create.\n\n"
        "**Step 3 — Link injection**\n"
        "Call `inject_adventure_log_links_tool` with the page ID. Show the user the proposed "
        "links, wait for explicit approval, then inject.\n\n"
        "**Step 4 — Calendar entry**\n"
        "Extract the in-game date from the adventure log body. Call `add_calendar_entry_tool` "
        f'with the resolved date and the title "{title}". Show the user the proposed calendar '
        "entry, wait for explicit approval, then add.\n\n"
        "**Step 5 — Quest log**\n"
        "Call `fetch_quests_tool` to get the current quest log. Based on the adventure log body, "
        "identify new quests that started this session (call `create_quest_tool` for each) and "
        "existing quests with progress or status changes (call `update_quest_tool` for each). "
        "Follow the standard confirmation pattern for each quest change.\n\n"
        "After completing all steps, provide a brief summary of everything that was created or updated."
    )
