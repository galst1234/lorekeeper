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
        f'You are running the chores workflow for the adventure log titled "{title}". '
        f'Do NOT ask the user which page to process — it is already specified as "{title}". '
        "Complete all 5 steps below in order for this exact page. "
        "Regardless of how many confirmation turns occur, always continue with the next pending step. "
        f"After any user interaction, state \"Continuing chores for '{title}'\" and proceed. "
        "When the user explicitly approves a proposed action (replies 'yes' or equivalent), "
        "that approval covers execution — do not re-ask for confirmation inside the tool call; "
        "proceed directly to calling the tool.\n\n"
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
        "Show the user all proposed quest changes together, wait for approval, then execute.\n\n"
        "After completing all 5 steps, provide a brief summary of everything that was created or updated."
    )
