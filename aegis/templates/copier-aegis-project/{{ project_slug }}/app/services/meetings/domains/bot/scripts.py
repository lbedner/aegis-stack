"""What the bot runs in Meet's page, each in one trip: its buttons as a
reader hears them, Meet's prompts answered, the caption blocks, where the
bot is, one look at all of it (``LOOK``), and the page telling the bot as
soon as a caption moves (``WATCH_CAPTIONS``)."""

# The page's buttons as a reader hears them (their labels, else their
# text), once each: what to look for a control as, where its label is gone.
BUTTONS = """() => [...new Set([...document.querySelectorAll('button, [role=button]')]
  .filter((button) => button.checkVisibility())
  .map((button) => (button.getAttribute('aria-label') || button.innerText || '')
    .trim().replace(/\\s+/g, ' '))
  .filter(Boolean))].join('\\n')"""
# What Meet puts over the call once the bot is in, each covering the chat,
# captions and Leave until answered: that a notetaker (Gemini) is on,
# accepted with "Join now" (the bot is one itself), and tips about its
# camera ("Got it"). Answered in one look, the click going to the button
# itself so one prompt stacked over another cannot block it. Only ever run
# in the call: in the lobby "Join now" is the join button.
ANSWER_PROMPTS = """() => {
  for (const button of document.querySelectorAll('button, [role=button]')) {
    const said = (button.innerText || button.getAttribute('aria-label') || '').trim();
    if ((said === 'Join now' || said === 'Got it') && button.checkVisibility()) {
      button.click();
    }
  }
}"""
# Each block is a speaker's name, then what they said. A block is tagged
# the first time it is read, so one Meet is still writing reads as the same
# line on the next look; the counter is the page's, so blocks never share
# a tag. A block with a button is the region's own control, not a caption.
READ_CAPTIONS = """(region) => [...region.children].flatMap((block) => {
  if (block.querySelector('button')) return [];
  const [speaker, ...words] = block.innerText.split('\\n');
  if (!speaker || !words.length) return [];
  block.dataset.line ??= String((window.captionLines = (window.captionLines || 0) + 1));
  return [{line: block.dataset.line, speaker: speaker.trim(), text: words.join(' ').trim()}];
})"""


# The state ``PAGE_TEXTS`` names, from the page's text, else in the call
# while Leave shows, else waiting.
STATE = """([texts, leave, inCall, waiting]) => {
  const body = document.body.innerText;
  for (const [state, said] of texts) {
    if (said.some((text) => body.includes(text))) return state;
  }
  const button = document.querySelector(leave);
  return button && button.checkVisibility() ? inCall : waiting;
}"""


# The first shown element of ``selector`` whose name, as a reader hears it
# (its label, else what labels it), says ``name``.
NAMED = """(selector, name) => [...document.querySelectorAll(selector)]
  .find((el) => {
    const by = (el.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
    const said = el.getAttribute('aria-label')
      || by.map((id) => document.getElementById(id)?.textContent || '').join(' ');
    return said.toLowerCase().includes(name) && el.checkVisibility();
  })"""


# The caption blocks shown (``READ_CAPTIONS``), in the region named
# "Captions" (``region``, kept while it is still on the page, else found).
SHOWN_CAPTIONS = """(region) => {
  region = region?.isConnected ? region : (__NAMED__)('[role=region]', 'captions');
  return {region, captions: region ? (__READ_CAPTIONS__)(region) : []};
}""".replace("__NAMED__", NAMED).replace("__READ_CAPTIONS__", READ_CAPTIONS)


# One look at the call, in one trip to the page (each read its own trip
# cost a look six): where the bot is (``STATE``); in the call, Meet's
# prompts answered (``ANSWER_PROMPTS``), the caption blocks
# (``READ_CAPTIONS``) and the People count's text (a badge named "People"
# by aria-labelledby, not a label).
LOOK = (
    """([texts, leave, inCall, waiting]) => {
  const state = (__STATE__)([texts, leave, inCall, waiting]);
  if (state !== inCall) return {state, captions: [], people: null};
  (__ANSWER_PROMPTS__)();
  const people = (__NAMED__)('button, [role=button]', 'people');
  return {
    state,
    captions: (__SHOWN_CAPTIONS__)(null).captions,
    people: people ? people.innerText : null,
  };
}""".replace("__STATE__", STATE)
    .replace("__ANSWER_PROMPTS__", ANSWER_PROMPTS)
    .replace("__NAMED__", NAMED)
    .replace("__SHOWN_CAPTIONS__", SHOWN_CAPTIONS)
)

# How long the page gathers caption changes before telling the bot.
TELL_MS = 150
# The function the page tells the bot through (``watch_captions``).
MOVED = "__captionsMoved"
# The page telling the bot which caption blocks moved, as soon as they do:
# any change to the page starts a short wait (``TELL_MS``), then the blocks
# read as a look reads them (``SHOWN_CAPTIONS``) that differ from those last
# seen (at first, those shown when it began) go to ``binding``. Meet redraws
# often; most waits find none moved, reading only the captions region.
WATCH_CAPTIONS = """(binding) => {
  let region = null;
  const read = () => {
    let captions;
    ({region, captions} = (__SHOWN_CAPTIONS__)(region));
    return captions;
  };
  let told = new Map(read().map((c) => [c.line, c.text]));
  let due = null;
  const tell = () => {
    due = null;
    const shown = read();
    const moved = shown.filter((c) => told.get(c.line) !== c.text);
    told = new Map(shown.map((c) => [c.line, c.text]));
    if (moved.length) window[binding](moved);
  };
  new MutationObserver(() => { due ??= setTimeout(tell, __TELL_MS__); })
    .observe(document.body, {childList: true, subtree: true, characterData: true});
}""".replace("__SHOWN_CAPTIONS__", SHOWN_CAPTIONS).replace("__TELL_MS__", str(TELL_MS))
