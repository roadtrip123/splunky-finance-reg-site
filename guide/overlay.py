"""Turn the repo's provider-agnostic lab guide into this event's web guide.

Two jobs, both about keeping credentials out of the public page:

  * the "Before you start" table publishes the two bank passwords and the Galileo URLs. On a page
    anyone can open, next to a registration form, that table becomes a pointer to the details card,
    which is filled from /api/credentials behind the participant cookie.
  * Step 3 and Step 4 need the LiteLLM base URL, model and key. None of the three appear in the
    markdown; the steps point at the card instead.

Every anchor is asserted to appear exactly once, so an upstream edit that moves one fails the
build instead of quietly dropping a section.
"""

CARD = "*Your lab details*"

LAB_TABLE = f"""## Before you start

Everything you need is in **{CARD}**, which opens from the button at the bottom right of every
page: your own copy of the bank, the customer and presenter logins, your Galileo account, and the
model endpoint. It fills in once you have checked in, and shows the same details every time you
come back.

Open your app, sign in to banking, then open `/demo-admin` in **another tab of the same browser
profile**. The two link automatically.
"""

AGENT_NOTE = f"""
   > **For this workshop:** choose Provider **Custom (OpenAI-compatible)**, which reveals the
   > **Base URL** field. Take the Base URL, Model and API key from **{CARD}** (the button at the
   > bottom right), and use the Model as the **Model name** too. The key is required even where the
   > gateway itself would answer without one, because the client refuses to send a request with an
   > empty key.
"""

INTEGRATION = f"""
**For this workshop:** the block above is already filled in with your gateway, model and key once
you have checked in: copy it straight into the field. The same block is on **My lab** and in
**{CARD}** (the button at the bottom right). Its `alias` is the name Galileo's model picker shows
when you build the evaluators.

If saving or testing the integration comes back with a 404, the endpoint field wants the full path
rather than the base, so add `/chat/completions` to the Base URL.
"""

# Upstream's integration body with ENDPOINT_URL, LLM_MODEL and YOUR_TOKEN placeholders. On the
# site it becomes the participant's own, filled in behind their cookie, the same block My lab
# shows, so the guide and My lab never disagree and the key is never in page source.
SNIPPET_WAS = ' Code Snippet:\n ```\n{\n  "authentication_type": "api_key",\n  "endpoint": "ENDPOINT_URL",\n  "default_model": "LLM_MODEL",\n  "model_properties": [\n    {\n      "name": "LLM_MODEL",\n      "alias": "LLM_MODEL_NAME",\n      "based_on": null,\n      "supported_parameters": [\n        "max_tokens",\n        "stop_sequences",\n        "temperature",\n        "tool_choice",\n        "tools"\n      ],\n      "supports_json_schema": false\n    }\n  ],\n  "token": null,\n  "api_key_header": "Authorization",\n  "api_key_value": "Bearer YOUR_TOKEN",\n  "authentication_scope": null,\n  "oauth2_token_url": null,\n  "headers": null,\n  "custom_llm_config": null,\n  "custom_header_mapping": null,\n  "multi_modal_config": null\n}\n ```\n'

SNIPPET_NOW = """
**Your integration, filled in:**

<div class="live-snippet" data-integration-snippet></div>

"""

# Upstream's screenshot of Galileo's custom-integration dialog carries hand-drawn EXAMPLE arrows
# with sample values, a made-up key among them. The site shows a clean capture of the dialog.
INTEGRATION_SHOT_WAS = (
    '<img width="627" height="719" alt="image" '
    'src="https://github.com/user-attachments/assets/81b1aacf-b573-49ef-a7b4-6da76a4eea64" />'
)
INTEGRATION_SHOT_NOW = (
    '<img width="604" height="717" alt="Galileo Integration Settings, Custom: a name for the '
    'integration and the Custom Integration box the JSON is pasted into" '
    'src="/static/img/galileo-custom-integration.png" />'
)

# Each evaluator names the judge model precisely. The alias is the site's own, filled in at request
# time from the gateway settings (see MODEL_ALIAS), so it follows a change made on the admin page and
# the model's name is not written into this public repository.
MODEL_ALIAS = '<span class="model-alias" data-model-alias>your custom model</span>'
PICK_WAS = "Select the **LLM Model** that you configured earlier in this step,"
PICK_NOW = f"Select **{MODEL_ALIAS}** as the **LLM Model**,"
PICKER_WAS = ("The model picker lists the `alias` from your integration, for example 'GPT-4.1 mini', "
              "or whatever you called your custom model, rather than the model name.")
PICKER_NOW = (f"That is the custom integration you added at the start of this step: the picker lists "
              f"models by their alias, so look for **{MODEL_ALIAS}**, not the gateway's model name.")
INTEGRATION_KIND_WAS = ("2. Select the integration you want to use for your LLM judge for example "
                        "OpenAI or Custom")
INTEGRATION_KIND_NOW = ("2. Select **Custom**: the judges use the same model gateway as the agent, "
                        f"and it appears in the evaluators as **{MODEL_ALIAS}**")

JUDGE_WAS = """**Use `gpt-4.1-mini` as the judge model.** Every accuracy figure in this lab was measured on it. A
reasoning model is not a better judge here: on the same traces, GPT-5.1 caught one incomplete answer
in three, and `gpt-4.1-mini` caught them. The picker only lists models from the integration you
configured above, so choose it there first."""

JUDGE_NOW = """**Your judge runs on the same model as the agent**, through the gateway in your lab details,
because that is the integration you configured above. The accuracy figures quoted later in this lab
were measured on `gpt-4.1-mini`, so read them as a guide rather than a promise. The judge model
matters more than the prompt: on the same traces GPT-5.1 caught one incomplete answer in three
where `gpt-4.1-mini` caught all of them. If a judge passes an answer you can plainly see is wrong,
re-run it before you start rewriting the prompt. The picker only lists models from the integration
you configured above."""

# (anchor, replacement). Anchors are verbatim upstream text and must match exactly once.
EDITS = [
    # The table and the paragraph that follows it, replaced by a pointer to the details card.
    (
        """## Before you start

| What | Where it comes from |
| --- | --- |
| Your app | the URL your instructor gives you |
| Customer login | account `12345678`, password `AlexDemo1234!` |
| Presenter portal | the same URL with `/demo-admin` on the end, password `PresenterDemo1234!` |
| Galileo console URL | `https://console.multitenant.galileocloud.io` |
| Galileo API URL |  `https://api.multitenant.galileocloud.io` |
| Galileo Agent Control URL | `https://agent-control.multitenant.galileocloud.io` |


Open the app, sign in to banking, then open `/demo-admin` in **another tab of the same browser profile**. The two link automatically.""",
        LAB_TABLE.rstrip(),
    ),
    (
        "   > provider answers 404, and it reads as a wrong model name.\n",
        "   > provider answers 404, and it reads as a wrong model name.\n" + AGENT_NOTE,
    ),
    (
        "with no score, or with reasoning that will not parse, that is the first field to try as `true`.\n",
        "with no score, or with reasoning that will not parse, that is the first field to try as `true`.\n"
        + INTEGRATION,
    ),
    (INTEGRATION_KIND_WAS, INTEGRATION_KIND_NOW),
    (INTEGRATION_SHOT_WAS, INTEGRATION_SHOT_NOW),
    (PICK_WAS, PICK_NOW, 3),
    (PICKER_WAS, PICKER_NOW, 3),
    (SNIPPET_WAS, SNIPPET_NOW),
    (JUDGE_WAS, JUDGE_NOW),
    # The lab opens by telling people what the instructor hands out. On the portal they claim it.
    (
        "Your instructor gives you one URL, an account number and two passwords. Everything else "
        "you build yourself.",
        "Register on this site and you are given your own instance and your own Galileo account. "
        "Everything else you build yourself.",
    ),
]


class MissingAnchor(Exception):
    """A plan that no longer matches the document is worth stopping for."""


def apply(text):
    for edit in EDITS:
        anchor, replacement = edit[0], edit[1]
        expected = edit[2] if len(edit) > 2 else 1
        found = text.count(anchor)
        if found != expected:
            first = anchor.strip().splitlines()[0][:80]
            raise MissingAnchor(f"anchor appears {found} times, expected {expected}: {first}")
        text = text.replace(anchor, replacement)
    return text
