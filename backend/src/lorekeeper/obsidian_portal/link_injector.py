"""Pure utility for injecting Obsidian Portal wiki-link syntax into text."""

import re

_WIKI_LINK_REGEX = re.compile(r"\[\[[^]]*]]")


def inject_links(body: str, entity_links: dict[str, str]) -> tuple[str, list[str], list[str]]:
    """
    Inject wiki-link syntax into text for the first appearance of each entity mention.

    Only the first occurrence of each mention is linked. Entities already linked anywhere
    in the text are skipped entirely. Text inside existing [[...]] is never modified.

    Args:
        body: The source text to inject links into.
        entity_links: Mapping of exact mention text to bare link target (no [[ or ]]).
            Use ":slug" for characters, "Page Title" for pages.

    Returns:
        Tuple of (modified_body, applied, skipped) where applied and skipped contain
        the mention strings that were linked or skipped respectively.
    """
    applied: list[str] = []
    skipped: list[str] = []

    for mention, raw_target in entity_links.items():
        target = raw_target.strip().removeprefix("[[").removesuffix("]]")
        link = f"[[{target} | {mention}]]"

        already_linked = bool(
            re.search(r"\[\[\s*" + re.escape(target) + r"\s*\|[^]]*]]", body, re.IGNORECASE),
        )
        if already_linked:
            skipped.append(mention)
            continue

        protected = [(m.start(), m.end()) for m in _WIKI_LINK_REGEX.finditer(body)]
        prefix = r"\b" if mention[0].isalnum() or mention[0] == "_" else r""
        suffix = r"\b" if mention[-1].isalnum() or mention[-1] == "_" else r""
        mention_re = re.compile(prefix + re.escape(mention) + suffix, re.IGNORECASE)
        replaced = False
        for match in mention_re.finditer(body):
            if not any(start <= match.start() < end for start, end in protected):
                body = body[: match.start()] + link + body[match.end() :]
                applied.append(mention)
                replaced = True
                break
        if not replaced:
            skipped.append(mention)

    return body, applied, skipped
