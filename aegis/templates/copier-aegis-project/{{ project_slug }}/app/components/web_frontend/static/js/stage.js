/* The stage (partials/chat/stage.html): a call, full screen. Each card she
   draws is a tab: a panel in the front and a tab in the strip below (app.js
   ``showTab``), the newest shown and underlined; once one is up she steps
   aside (``data-showing``). voice.js hands it each card and line
   (``window.chatStage``); off the stage it is not loaded. */
(() => {
  let drawn = 0;
  const stage = () => document.getElementById('chat-stage');
  // A change, animated where the browser can (her figure stepping aside,
  // the card coming on).
  const animated = (change) => (document.startViewTransition ? document.startViewTransition(change) : change());

  window.chatStage = {
    // A drawn card's place: a new panel and its tab, shown.
    slot() {
      const key = String(++drawn);
      const slot = clone('chat-live-card');
      const tab = clone('chat-stage-tab');
      slot.hidden = true;
      slot.dataset.tabPanel = key;
      tab.dataset.tab = key;
      document.getElementById('chat-stage-front').append(slot);
      const strip = document.getElementById('chat-stage-strip');
      strip.append(tab);
      strip.hidden = false;
      animated(() => {
        showTab(stage(), key);
        stage().dataset.showing = '';
      });
      return slot;
    },
    // A card loaded into its panel: its tab named by the card's title.
    loaded(slot) {
      const tab = document.querySelector(`#chat-stage-strip [data-tab="${slot.dataset.tabPanel}"]`);
      const title = slot.querySelector('[data-card] > :first-child > :first-child');
      if (tab) tab.textContent = title?.textContent.trim() ?? '';
    },
    // The sentence she is on, under her name.
    saying(sentence) {
      document.getElementById('chat-stage-line').textContent = sentence;
    },
  };
})();
