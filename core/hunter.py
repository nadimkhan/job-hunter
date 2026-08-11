"""LinkedIn search URL builder + DM template generator.
Uses the active profile's outreach config."""


import urllib.parse, json
from datetime import datetime


def build_linkedin_searches(company: str, outreach_config: dict) -> list[dict]:
    titles = outreach_config.get("linkedin_search_titles", [])
    base = "https://www.linkedin.com/search/results/people/"
    searches = []
    for entry in titles:
        title = entry.get("title", "")
        if not title:
            continue
        label = entry.get("label") or title
        category = entry.get("category") or "engineering"
        keywords = f"{company} {title}"
        url = f"{base}?keywords={urllib.parse.quote(keywords)}"
        searches.append({"label": label, "title": title, "category": category, "url": url})
    return searches


def _safe_format(template: str, tokens: dict) -> str:
    class _Silent(dict):
        def __missing__(self, key):
            return ""
    try:
        return template.format_map(_Silent(tokens))
    except (IndexError, KeyError, ValueError):
        return template


def generate_dm_template(job: dict, outreach_config: dict) -> dict:
    candidate_name = outreach_config.get("candidate_name", "[Your Name]")
    candidate_core = [t.lower() for t in (outreach_config.get("candidate_core_tech") or [])]
    candidate_extra = [t.lower() for t in (outreach_config.get("candidate_extra_tech") or [])]
    bio_short_template = outreach_config.get("bio_short", "")
    achievements = outreach_config.get("achievements", [])
    dm_short_template = outreach_config.get("dm_short_template", "")
    dm_long_template = outreach_config.get("dm_long_template", "")

    title = (job.get("title") or "this role").strip()
    if " - " in title:
        title = title.split(" - ")[0]
    company = (job.get("company") or "your team").strip()

    tech_stack_str = job.get("tech_stack", "") or ""
    tech_bits = [t.strip().lower() for t in tech_stack_str.split(",") if t.strip()]
    matched_core = [t for t in tech_bits if t in candidate_core]

    if matched_core:
        stack_phrase = "/".join(matched_core[:2]).title()
    elif candidate_core:
        stack_phrase = "/".join(candidate_core[:2]).title()
    elif candidate_extra:
        stack_phrase = "/".join(candidate_extra[:2]).title()
    else:
        stack_phrase = "the stack"

    bio_short = _safe_format(bio_short_template, {"stack": stack_phrase})
    achievements_block = "\n\n".join(achievements)

    greeting = "Hi"
    tokens = {
        "greeting": greeting,
        "company": company,
        "title": title,
        "stack": stack_phrase,
        "bio_short": bio_short,
        "achievements": achievements_block,
        "candidate_name": candidate_name,
    }

    short = _safe_format(dm_short_template, tokens).strip()
    long_ = _safe_format(dm_long_template, tokens).strip()

    if len(short) > 300:
        short = short[:297].rstrip() + "..."

    return {"short": short, "long": long_}
