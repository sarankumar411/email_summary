MAP_PROMPT = """Summarize these client email messages as strict JSON.
Return actors, concluded_discussions, and open_action_items only.
Actors must include header-derived people and body-mentioned people with source set appropriately."""

REDUCE_PROMPT = """Merge partial email summaries as strict JSON.
Deduplicate actors, consolidate concluded discussion topics, and union open action items."""

