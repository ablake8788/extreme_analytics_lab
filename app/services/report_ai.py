"""
report_ai.py - asks OpenAI to write the wording of a results report.

The model receives (1) the facts computed by results_facts.py and (2) the
text of the reference document (e.g. Titanium_analytics.docx). It returns
JSON with wording only. Guardrails:

  - Every table in the Word report is filled from the facts, never from AI.
  - Any AI sentence containing a number that is not in the facts or the
    reference document is removed (and counted in the report's notes).
  - Causes may only be written as hypotheses to investigate.
  - Without an API key (or if the call fails) plain wording built from the
    facts is used, so a report is always produced.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

OPENAI_URL = "https://api.openai.com/v1/chat/completions"

SYSTEM_PROMPT = """You write building-operations analysis reports for Titanium Analytics.

You receive FACTS (computed by a deterministic analysis engine) and a REFERENCE
document that describes Titanium's method (Extremes, Changes, Volatility) and
its abnormality report format. Write clear, plain-English wording for a
building manager.

Hard rules:
1. Use only numbers, dates and times that appear in FACTS (or, in the market
   review, in REFERENCE). Never compute, estimate or invent a new number.
2. Never state a cause as fact. Causes are hypotheses to investigate, written
   as "This pattern fits ... - a hypothesis to check, not a conclusion."
3. Do not soften or omit unfavourable findings (e.g. many false flags).
4. Be concise. Bullets are single sentences.
5. Return ONLY a JSON object with exactly these keys:
{
 "summary_bullets": [3 to 4 strings],
 "normal_behavior": "one short paragraph about the typical daily cycle",
 "abnormality_notes": [one object per FACTS.abnormalities item, same order:
     {"title": "short title", "context": ["1-3 bullets"], "hypothesis": "one sentence"}],
 "gap_note": "one sentence about data gaps, or empty string",
 "minor_observations": ["bullets"],
 "changes": ["2-4 bullets"],
 "volatility": ["2-4 bullets"],
 "flags_explanation": "one paragraph: why the engine flagged what it did",
 "recommendations_operations": [{"title": "...", "text": "..."}],
 "recommendations_analytics": [{"title": "...", "text": "..."}],
 "market_review": [{"promise": "...", "today": "...", "after": "..."}],
 "market_note": "one or two sentences",
 "limitations": ["2-4 bullets"]
}"""

KEYS = ["summary_bullets", "normal_behavior", "abnormality_notes", "gap_note", "minor_observations",
        "changes", "volatility", "flags_explanation", "recommendations_operations",
        "recommendations_analytics", "market_review", "market_note", "limitations"]


class AIReportError(RuntimeError):
    pass


@dataclass
class ReportText:
    content: dict
    source: str                      # "openai" or "built-in"
    model: str = ""
    removed_sentences: list = field(default_factory=list)
    note: str = ""


# ------------------------------------------------------------------ OpenAI
def call_openai(facts: dict, reference_text: str, api_key: str, model: str, timeout: float) -> dict:
    if requests is None:
        raise AIReportError("The 'requests' package is not installed.")
    user = ("FACTS (JSON):\n" + json.dumps(facts, ensure_ascii=False)
            + "\n\nREFERENCE DOCUMENT:\n" + (reference_text[:15000] if reference_text else "(not provided)"))
    payload = {"model": model, "temperature": 0.2, "response_format": {"type": "json_object"},
               "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]}
    try:
        r = requests.post(OPENAI_URL, json=payload, timeout=timeout,
                          headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    except Exception as exc:
        raise AIReportError(f"Could not reach OpenAI: {exc.__class__.__name__}") from None
    if r.status_code == 401:
        raise AIReportError("OpenAI rejected the API key (check [openai] api_key in config.local.ini).")
    if r.status_code == 429:
        raise AIReportError("OpenAI rate limit or quota reached - try again later or check billing.")
    if r.status_code >= 400:
        raise AIReportError(f"OpenAI returned HTTP {r.status_code}.")
    try:
        text = r.json()["choices"][0]["message"]["content"]
        data = json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M))
    except Exception:
        raise AIReportError("OpenAI returned an answer that was not valid JSON.") from None
    if not isinstance(data, dict):
        raise AIReportError("OpenAI returned an unexpected answer.")
    return data


# ------------------------------------------------------------------ number check
_NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


def _numbers_in(text: str) -> set:
    out = set()
    for m in _NUM.findall(text or ""):
        m = m.replace(",", "")
        try:
            out.add(round(abs(float(m)), 2))
        except ValueError:
            pass
    return out


def allowed_numbers(facts: dict, reference_text: str) -> set:
    allowed = _numbers_in(json.dumps(facts)) | _numbers_in(reference_text or "")
    allowed |= {float(i) for i in range(0, 32)}           # days, hours, small counts
    allowed |= {float(y) for y in range(2020, 2041)}       # years
    return allowed


def _ok(sentence: str, allowed: set) -> bool:
    for n in _numbers_in(sentence):
        if n in allowed:
            continue
        if any(abs(n - a) <= 0.011 for a in allowed):
            continue
        return False
    return True


def verify(content: dict, allowed: set) -> tuple[dict, list]:
    removed = []

    def clean_text(t):
        if not isinstance(t, str):
            return ""
        parts = re.split(r"(?<=[.!?])\s+", t.strip())
        kept = []
        for p in parts:
            if _ok(p, allowed):
                kept.append(p)
            else:
                removed.append(p)
        return " ".join(kept)

    def clean(obj):
        if isinstance(obj, str):
            return clean_text(obj)
        if isinstance(obj, list):
            return [x for x in (clean(i) for i in obj) if x not in ("", None, {}, [])]
        if isinstance(obj, dict):
            return {k: clean(v) for k, v in obj.items()}
        return obj

    return clean(content), removed


# ------------------------------------------------------------------ built-in wording
def builtin_text(f: dict) -> dict:
    u = f.get("units", "")
    fl, cyc, ch, vol = f["engine_flags"], f["daily_cycle"], f["changes"], f["volatility"]
    comp = f.get("window_comparison") or []
    abn = f["abnormalities"]
    s = []
    if f["data_gaps"]:
        g = f["data_gaps"][0]
        s.append(f"Data gap: no readings from {g['start']} to {g['end']} ({g['duration']}).")
    for a in abn[:2]:
        s.append(f"{a['direction'].capitalize()} typical from {a['start']} to {a['end']} ({a['duration']}), "
                 f"up to {abs(a['peak_deviation'])}{u} from typical.")
    if len(comp) == 2:
        s.append(f"The engine flagged {comp[0]['events']} events with a {comp[0]['hours']}-hour baseline; "
                 f"with a {comp[1]['hours']}-hour baseline the same data gives {comp[1]['events']}.")
    notes = [{"title": f"{a['direction'].capitalize()} typical for this time of day",
              "context": [f"Observed {a['observed_range']}{u} where {a['typical_range']}{u} is typical."],
              "hypothesis": "Check schedules, overrides and equipment logs for this period - a hypothesis to check, not a conclusion."}
             for a in abn]
    return {
        "summary_bullets": s or ["No substantial abnormality was found against the typical daily cycle."],
        "normal_behavior": f"The typical daily swing is {cyc['daily_swing_min']}-{cyc['daily_swing_max']}{u}; "
                           f"schedule transitions happen around hours {', '.join(str(h) for h in cyc['transition_hours'])}.",
        "abnormality_notes": notes,
        "gap_note": "Readings resumed after the gap." if f["data_gaps"] else "",
        "minor_observations": [f"{m['start']}: {m['direction']} typical for {m['duration']} "
                               f"(up to {abs(m['peak_deviation'])}{u})." for m in f["minor_observations"]],
        "changes": [f"Typical fastest change: {ch['typical_fastest_drop']}{u} down, {ch['typical_fastest_rise']}{u} up per reading.",
                    f"{ch['abnormal_change_in_transition_pct']}% of abnormal-change flags fall in schedule transition hours."],
        "volatility": [f"Daily variability of changes stays between {vol['daily_step_std_min']} and {vol['daily_step_std_max']}{u}."]
                      + [f"{d['date']} had {d['reversals_per_100']} reversals per 100 readings." for d in vol["unstable_days"]],
        "flags_explanation": f"{fl['extreme_in_transition_pct']}% of extreme flags ({fl['extreme_in_transition_hours']} of "
                             f"{fl['extreme_readings']}) fall in schedule transition hours, and {fl['extreme_with_tiny_variability']} "
                             f"came from periods with almost no variability.",
        "recommendations_operations": [{"title": "Review the abnormal periods",
                                        "text": "Check schedules, overrides and equipment logs for the periods listed."}]
                                      + ([{"title": "Check the data gap", "text": "Find the cause and alert on missing data."}]
                                         if f["data_gaps"] else []),
        "recommendations_analytics": [{"title": "Use a daily baseline", "text": "A window covering one day avoids flagging the normal cycle."},
                                      {"title": "Add a variability floor", "text": "At least one sensor step, so a single tick cannot trigger an extreme."}],
        "market_review": [],
        "market_note": "",
        "limitations": ["Causes are hypotheses for investigation.", "The typical baseline uses only the period in this file."],
    }


# ------------------------------------------------------------------ entry point
def write_report_text(facts: dict, reference_text: str, api_key: str = "", model: str = "",
                      timeout: float = 90.0) -> ReportText:
    if not api_key:
        return ReportText(builtin_text(facts), "built-in",
                          note="AI wording not used: no OpenAI API key is set ([openai] api_key in config.local.ini).")
    try:
        raw = call_openai(facts, reference_text, api_key, model, timeout)
    except AIReportError as exc:
        return ReportText(builtin_text(facts), "built-in", note=f"AI wording not used: {exc}")
    content = {k: raw.get(k, [] if k not in ("normal_behavior", "gap_note", "flags_explanation", "market_note") else "")
               for k in KEYS}
    content, removed = verify(content, allowed_numbers(facts, reference_text))
    fallback = builtin_text(facts)
    for k in KEYS:  # anything the model left empty falls back to the built-in wording
        if content.get(k) in ("", [], None) and k not in ("gap_note", "market_review", "market_note"):
            content[k] = fallback[k]
    return ReportText(content, "openai", model=model, removed_sentences=removed)
