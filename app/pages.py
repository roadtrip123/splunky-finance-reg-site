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
