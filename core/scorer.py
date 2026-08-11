"""Rule-based relevance scorer. No API key needed.
Scores jobs 0-100 based on title, description, and tech stack match.
Also detects whether a job is India/remote-friendly.

All preferences come from the active profile (DB-backed JSON blob)."""

import re


def extract_tech_stack(text: str, relevant_tech: list[str]) -> list[str]:
    text_lower = text.lower()
    return [tech for tech in relevant_tech if tech in text_lower]


def estimate_experience_level(text: str) -> str:
    text_lower = text.lower()
    fresher_kw = ["intern", "internship", "trainee", "entry level", "entry-level",
                  "0-1 year", "0-2 years", "fresher", "new grad", "graduate",
                  "campus", "freshers"]
    senior_kw = ["senior", "sr.", "lead", "principal", "staff",
                  "8+ years", "10+ years", "15+ years"]
    junior_kw = ["junior", "jr.", "1+ year", "1-2 years"]

    if any(w in text_lower for w in fresher_kw):
        return "fresher"
    if any(w in text_lower for w in senior_kw):
        return "senior"
    if any(w in text_lower for w in junior_kw):
        return "junior"
    return "mid"


def check_india_friendly(location: str, description: str,
                         india_positive: list, india_negative: list,
                         tz_good: list, tz_bad: list) -> dict:
    full_text = f"{location} {description}".lower()
    loc_lower = location.lower()

    neg_hits = [kw for kw in india_negative if kw in full_text]
    if neg_hits:
        return {"result": "no", "note": f"Restricted: {', '.join(neg_hits[:3])}"}

    tz_neg_hits = [kw for kw in tz_bad if kw in loc_lower]
    if tz_neg_hits:
        return {"result": "no", "note": f"Timezone mismatch: {', '.join(tz_neg_hits[:2])}"}

    pos_hits = [kw for kw in india_positive if kw in full_text]
    if pos_hits:
        return {"result": "yes", "note": f"Open: {', '.join(pos_hits[:3])}"}

    global_signals = ["worldwide", "anywhere", "global", "work from anywhere",
                     "location independent", "globally distributed"]
    if any(kw in full_text for kw in global_signals):
        return {"result": "yes", "note": "Global remote"}

    non_india = ["united states", "usa", "us", "canada", "uk",
                  "europe", "eu", "germany", "france", "australia"]
    if any(r in loc_lower for r in non_india):
        return {"result": "no", "note": f"Restricted to: {location}"}

    return {"result": "maybe", "note": "No clear restriction"}


def score_job(title: str, description: str, location: str = "",
              profile_config: dict = None) -> dict:
    if profile_config is None:
        return {"score": 0, "tech_stack": [], "experience_level": "mid",
                "india_friendly": "unknown", "location_note": "",
                "reasons": [], "red_flags": []}

    search = profile_config.get("search", {})
    scoring = profile_config.get("scoring", {})
    location_cfg = profile_config.get("location", {})

    pos_titles = search.get("title_keywords_positive", [])
    neg_titles = search.get("title_keywords_negative", [])
    relevant_tech = search.get("relevant_tech", [])
    core_tech = scoring.get("core_tech", [])
    signal_list = scoring.get("backend_signals", [])
    weights = scoring.get("weights", {"title": 35, "tech": 35, "experience": 15, "signal": 15})
    exp_target = scoring.get("experience_target", "mid")
    exp_bonuses = scoring.get("experience_bonuses", {})

    w_title = int(weights.get("title", 35))
    w_tech = int(weights.get("tech", 35))
    w_exp = int(weights.get("experience", 15))
    w_signal = int(weights.get("signal", 15))

    score = 0
    reasons, red_flags = [], []
    full_text = f"{title} {description}".lower()
    title_lower = title.lower()

    # Title
    title_matches = [kw for kw in pos_titles if kw in title_lower]
    if title_matches:
        pts = min(len(title_matches) * 12, w_title)
        score += pts
        reasons.append(f"Title: {', '.join(title_matches[:6])}")

    title_neg = [kw for kw in neg_titles if kw in title_lower]
    if title_neg:
        score -= len(title_neg) * 15
        red_flags.append(f"Blocked: {', '.join(title_neg[:4])}")

    # Tech
    tech_found = extract_tech_stack(full_text, relevant_tech)
    tech_core = [t for t in tech_found if t in core_tech]
    tech_secondary = [t for t in tech_found if t not in core_tech]

    core_budget = max(0, int(w_tech * 0.71))
    sec_budget = max(0, w_tech - core_budget)

    if tech_core:
        score += min(len(tech_core) * 12, core_budget)
        reasons.append(f"Core tech: {', '.join(tech_core)}")
    if tech_secondary:
        score += min(len(tech_secondary) * 3, sec_budget)
        reasons.append(f"Related: {', '.join(tech_secondary[:8])}")

    # Experience
    exp_level = estimate_experience_level(full_text)
    exp_row = exp_bonuses.get(exp_target, {})
    raw_bonus = int(exp_row.get(exp_level, 0))
    scaled_bonus = int(round(raw_bonus * (w_exp / 15.0)))
    score += scaled_bonus
    if scaled_bonus > 0:
        reasons.append(f"Exp match: {exp_level} (target={exp_target}) +{scaled_bonus}")
    elif scaled_bonus < 0:
        red_flags.append(f"Exp mismatch: {exp_level} (target={exp_target}) {scaled_bonus}")

    # Domain signals
    sig_matches = [s for s in signal_list if s in full_text]
    if sig_matches:
        score += min(len(sig_matches) * 4, w_signal)
        reasons.append(f"Signals: {', '.join(sig_matches[:5])}")

    # India-friendly
    india_check = check_india_friendly(
        location, description,
        india_positive=location_cfg.get("india_positive", []),
        india_negative=location_cfg.get("india_negative", []),
        tz_good=location_cfg.get("timezone_compatible", []),
        tz_bad=location_cfg.get("timezone_incompatible", []),
    )

    score = max(0, min(100, score))
    return {
        "score": score,
        "tech_stack": tech_found,
        "experience_level": exp_level,
        "india_friendly": india_check["result"],
        "location_note": india_check["note"],
        "reasons": reasons,
        "red_flags": red_flags,
    }
