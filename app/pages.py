"""Words for the pages that are not the guide itself: headlines, the step cards on the overview,
and the house rules. Kept apart from the routes so the copy can be edited without reading code."""

NUMBERS = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
           "Eleven", "Twelve"]


def number_word(n):
    return NUMBERS[n] if 0 <= n < len(NUMBERS) else str(n)


NAV = [
    ("home", "/", "Overview"),
    ("briefing", "/briefing", "Briefing & Setup"),
    ("lab", "/lab", "Workshop lab"),
    ("troubleshooting", "/troubleshooting", "Troubleshooting"),
]

GUIDE_PAGES = {
    "briefing": {
        "path": "/briefing",
        "eyebrow": "The briefing",
        "title": "A fictional bank.",
        "title_em": "A real agent.",
        "lede": "Set up first: your Galileo project, the app connected to it, and the agent "
                "connected to a model. When a question you ask shows up as a trace in Galileo, "
                "you are ready for the lab.",
        "accent": "orange",
        "prev": None,
        "next": "lab",
    },
    "lab": {
        "path": "/lab",
        "eyebrow": "The workshop lab",
        "title": "{count} steps.",
        "title_em": "Catch it, then stop it.",
        "lede": "Build three evaluators that catch a bad answer after the customer has read it, "
                "then a guardrail that stops an unsafe action before it happens. Every check runs "
                "against your own stream.",
        "accent": "magenta",
        "prev": "briefing",
        "next": "troubleshooting",
    },
    "troubleshooting": {
        "path": "/troubleshooting",
        "eyebrow": "Field guide",
        "title": "When something",
        "title_em": "doesn't look right.",
        "lede": "The symptoms people hit most, what each one means, and the fix. Start with the "
                "table, then the longer notes below it.",
        "accent": "cyan",
        "prev": "lab",
        "next": None,
    },
}

PAGE_NAMES = {"briefing": "Briefing & Setup", "lab": "Workshop lab",
              "troubleshooting": "Troubleshooting"}

# One line per step for the overview cards. A step upstream adds without an entry here still gets a
# card, just without the sentence.
STEP_CARDS = {
    1: ("Setup", "Sign in to Galileo and create an API key, a project and a log stream for the "
                 "agent to report into."),
    2: ("Setup", "Paste your key, project and stream into the app's Setup tab and prove the "
                 "connection holds."),
    3: ("Setup", "Point the agent at the model, ask it one real question, and find that question "
                 "as a trace in Galileo."),
    4: ("Evaluators", "Define three LLM-as-a-judge evaluators: the whole question answered, the "
                      "numbers right, the right customer."),
    5: ("Evaluators", "Attach the judges to your stream from the app, so every new turn is "
                      "scored."),
    6: ("Test", "Inject faults one at a time and watch each judge catch the answer it was built "
                "for."),
    7: ("Guardrail", "Build the guardrail that refuses a transfer out of someone else's account, "
                     "before it happens."),
    8: ("Test", "Ask the agent to move another customer's money and watch the guardrail decide."),
}

HOUSE_RULES = [
    ("Initials on everything",
     "Evaluators live at the organisation level, so put your initials on each one, as the guide "
     "shows."),
    ("Your instance is yours",
     "Your bank, your data, your settings. Nothing you do reaches anyone else's."),
    ("Re-run before you debug",
     "Judges are models and they vote. If a score looks wrong, run it again before you rewrite "
     "the prompt."),
    ("Stuck for five minutes?",
     "Check the troubleshooting page first, then put your hand up."),
]


# ---------------------------------------------------------------- the headline

HEADLINE = ["Splunk Agent", "Observability"]

# Splunk's brand gradient, as splunk.com defines it, starting at its highlight pink: #CE0070 is
# 3.3:1 on this navy and reads as blurred, #EB008B holds 4.2:1.
SPLUNK_STOPS = [(0.0, "#EB008B"), (0.30, "#EE1D62"), (0.58, "#F05A22"), (0.76, "#F4781F"),
                (1.0, "#F99D1C")]


def splunk_colour(t):
    """The colour at position t (0 to 1) along the Splunk gradient."""
    t = max(0.0, min(1.0, t))
    for (a, low), (b, high) in zip(SPLUNK_STOPS, SPLUNK_STOPS[1:]):
        if t <= b:
            f = (t - a) / (b - a)
            rgb = [round(int(low[i:i + 2], 16) * (1 - f) + int(high[i:i + 2], 16) * f)
                   for i in (1, 3, 5)]
            return "#{:02X}{:02X}{:02X}".format(*rgb)
    return SPLUNK_STOPS[-1][1]


def gradient_lines(lines, spread=0.18):
    """Each letter of the headline as (character, solid colour), sampled along the gradient by its
    place in the headline, the lower line shifted along so the sweep runs diagonally.

    Solid letters rather than a gradient clipped to the text: Chrome paints clipped text through a
    mask that can come out softer than ordinary text on a Retina screen, and solid text is drawn
    like every other word on the page."""
    count = len(lines)
    out = []
    for index, line in enumerate(lines):
        start = spread * index / max(1, count - 1)
        end = 1 - spread * (count - 1 - index) / max(1, count - 1)
        steps = max(1, len(line) - 1)
        out.append([(ch, splunk_colour(start + (end - start) * i / steps))
                    for i, ch in enumerate(line)])
    return out
