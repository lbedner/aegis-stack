/* Talking to the assistant, beside the chat stream (chat.js).

   A spoken turn is the typed turn. The microphone records until it is
   pressed again, the recording is transcribed into the composer and sent
   through chat.js like anything typed.

   How it is heard is the server's, on the mic as data-voice: `reply`
   "live" speaks each sentence as soon as it is complete, "answer" plays
   the settled answer; `sound` "typing" plays soft key taps while the
   assistant works and has said nothing yet. Any answer's Listen button
   plays it on demand.

   Nothing is recorded until the microphone is pressed - that is when the
   browser asks. The status line's wording lives in the surface partial's
   <template id="chat-mic-states">; the server's own refusals arrive as
   text. Audio is never kept. */
(() => {
  const LIMIT_MS = 2 * 60 * 1000; // a question, not a dictation
  const QUIET_MS = 8000; // typing stops this long after a turn with nothing to say
  let recorder = null;
  let speakReply = false; // the turn in flight is heard once it settles
  let live = false; // the turn in flight is heard as it is written
  let pending = ''; // streamed text not yet a whole sentence
  const queue = []; // sentences fetched ahead, played in order
  let current = null;
  let player = null;
  let playing = null; // the Listen button whose audio is playing

  const mic = () => document.getElementById('chat-mic');
  const box = () => document.querySelector('#chat-composer textarea');
  const voice = () => JSON.parse(mic()?.dataset.voice || '{}');

  const say = (state, text) => {
    const status = document.getElementById('chat-mic-status');
    if (!status) return;
    const phrase = state && document.getElementById('chat-mic-states')
      ?.content.querySelector(`[data-state="${state}"]`);
    status.textContent = text ?? phrase?.textContent ?? '';
  };

  const pressed = (on) => mic()?.setAttribute('aria-pressed', String(on));
  // What a voice control is doing: idle, recording, thinking, speaking. The
  // page draws each state (the voice_states macro); this only sets it.
  const show = (control, state) => control?.setAttribute('data-state', state);
  // The mic's state, with the status line that reads it out.
  const mood = (state) => {
    show(mic(), state);
    if (state === 'thinking' || state === 'speaking') say(state);
    if (state === 'idle') say(null);
  };

  // --- Working: soft key taps until it speaks --------------------------------
  // Generated, not a recording: a short burst of filtered noise per key, at
  // the uneven pace of someone typing.
  let ear = null; // the AudioContext, made on the mic press that allows it
  let typing = null;
  let quiet = null;
  const tap = () => {
    const length = 0.018 + Math.random() * 0.02;
    const buffer = ear.createBuffer(1, Math.ceil(ear.sampleRate * length), ear.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / data.length) ** 3;
    const source = ear.createBufferSource();
    const tone = ear.createBiquadFilter();
    const level = ear.createGain();
    source.buffer = buffer;
    tone.type = 'bandpass';
    tone.frequency.value = 1800 + Math.random() * 1800;
    level.gain.value = 0.05 + Math.random() * 0.05;
    source.connect(tone).connect(level).connect(ear.destination);
    source.start();
  };
  const keepTyping = () => {
    tap();
    // Unhurried keys, and often the pause between words.
    typing = setTimeout(keepTyping, Math.random() < 0.25 ? 500 + Math.random() * 700 : 150 + Math.random() * 200);
  };
  const startTyping = () => {
    if (voice().sound !== 'typing' || typing || !ear) return;
    ear.resume();
    keepTyping();
  };
  const stopTyping = () => {
    clearTimeout(typing);
    clearTimeout(quiet);
    typing = null;
  };

  // The first sound of the voice ends the typing and shows it speaking -
  // on ``control`` (a speaker button) and, for a reply, on the mic.
  const voiced = (url, control = null, reply = true) => {
    const audio = new Audio(url);
    audio.addEventListener('playing', () => {
      stopTyping();
      show(control, 'speaking');
      if (reply) mood('speaking');
    });
    return audio;
  };

  // --- Hearing --------------------------------------------------------------
  const extension = (type) =>
    type.includes('mp4') ? 'mp4' : type.includes('ogg') ? 'ogg' : 'webm';

  // What was heard goes straight out, as if typed and sent. While a turn is
  // still streaming the box is locked, so it waits there to be sent. The
  // composer carries data-spoken until the post goes out, so the answer is
  // heard.
  const place = (text) => {
    const input = box();
    if (!input) return;
    input.value = input.value.trim() ? `${input.value.trim()} ${text}` : text;
    input.dispatchEvent(new Event('input', { bubbles: true })); // Alpine's x-model
    input.form.dataset.spoken = '';
    say(null);
    if (input.disabled) return;
    input.form.requestSubmit();
  };

  const transcribe = async (blob, url) => {
    say('transcribing');
    const body = new FormData();
    body.append('audio', blob, `speech.${extension(blob.type)}`);
    try {
      const answer = await fetch(url, { method: 'POST', body });
      const data = await answer.json().catch(() => ({}));
      if (answer.ok && data.text) return place(data.text);
      mic()?.setAttribute('data-state', 'idle');
      if (data.error) say(null, data.error);
      else say('offline');
    } catch (_) {
      mic()?.setAttribute('data-state', 'idle');
      say('offline');
    }
  };

  const start = async (button) => {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return say('unsupported');
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      return say(e.name === 'NotAllowedError' ? 'denied' : 'unsupported');
    }
    const chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.addEventListener('dataavailable', (event) => { if (event.data.size) chunks.push(event.data); });
    recorder.addEventListener('stop', () => {
      for (const track of stream.getTracks()) track.stop();
      clearTimeout(recorder._limit);
      const type = recorder.mimeType || 'audio/webm';
      recorder = null;
      pressed(false);
      mic()?.setAttribute('data-state', 'thinking');
      transcribe(new Blob(chunks, { type }), button.dataset.transcripts);
    });
    recorder.start();
    recorder._limit = setTimeout(() => recorder?.stop(), LIMIT_MS);
    pressed(true);
    mic()?.setAttribute('data-state', 'recording');
    say('recording');
  };

  document.addEventListener('click', (event) => {
    const button = event.target.closest?.('#chat-mic');
    if (!button) return;
    // A browser only lets a page make sound after a press: this is that press.
    ear ??= new AudioContext();
    if (recorder) recorder.stop();
    else {
      hush();
      start(button);
    }
  });

  // --- Speaking ---------------------------------------------------------------
  const stop = () => {
    if (player?.reply) mood('idle');
    player?.pause();
    playing?.setAttribute('aria-pressed', 'false');
    show(playing, 'idle');
    player = null;
    playing = null;
  };

  // ``reply``: the answer to a spoken turn, so the mic shows it too; a
  // Listen shows only on its own button.
  const play = (button, reply = false) => {
    const again = playing === button;
    stop();
    if (again) return; // pressing a playing Listen button stops it
    show(button, 'thinking'); // fetching and synthesizing
    player = voiced(button.dataset.speak, button, reply);
    player.reply = reply;
    playing = button;
    button.setAttribute('aria-pressed', 'true');
    player.addEventListener('ended', stop);
    player.addEventListener('error', stop);
    player.play().catch(stop); // autoplay refused: the button still works
  };

  document.addEventListener('click', (event) => {
    const button = event.target.closest?.('[data-speak]');
    if (!button) return;
    hush();
    play(button);
  });

  // --- Live: each sentence as it is written -----------------------------------
  // Fetched as soon as it is whole (the server synthesizes while the one
  // before plays) and played in order.
  const next = () => {
    current = queue.shift() || null;
    if (!current) {
      if (!live && !pending) mood('idle'); // it has finished
      return;
    }
    current.addEventListener('ended', next);
    current.addEventListener('error', next);
    current.play().catch(next);
  };
  const enqueue = (text) => {
    if (!text.trim()) return;
    const audio = voiced(`${mic().dataset.say}?text=${encodeURIComponent(text)}`);
    audio.preload = 'auto';
    queue.push(audio);
    if (!current) next();
  };
  // A sentence ends at . ! or ? before a space, or at a line break (a list
  // item or a heading has no full stop).
  const ENDS = /[.!?](?=\s)|\n/;
  const cut = () => {
    for (let at = pending.search(ENDS); at !== -1; at = pending.search(ENDS)) {
      enqueue(pending.slice(0, at + 1));
      pending = pending.slice(at + 1);
    }
  };
  const flush = () => {
    enqueue(pending);
    pending = '';
  };
  const hush = () => {
    live = false;
    pending = '';
    queue.length = 0;
    current?.pause();
    current = null;
    stopTyping();
    mood('idle');
  };
  document.addEventListener('chat:text', (event) => {
    if (!live) return;
    pending += event.detail;
    cut();
  });
  // Anything written before a tool call is said before the tool runs.
  document.addEventListener('chat:tool', () => {
    if (live) flush();
  });
  document.addEventListener('chat:end', () => {
    if (live) flush();
    live = false;
    if (!current && !queue.length && !speakReply) mood('idle');
    // A turn that ends with nothing to say (failed, or silent) must not
    // leave the typing - or the spinner - running.
    clearTimeout(quiet);
    quiet = setTimeout(() => {
      stopTyping();
      if (!current && !player) mood('idle');
    }, QUIET_MS);
  });

  // A turn sent from a transcript is answered aloud, in the server's chosen
  // way; a typed one is not.
  document.body.addEventListener('htmx:configRequest', (event) => {
    const form = event.detail.elt;
    if (form.id !== 'chat-composer') return;
    const spoken = 'spoken' in form.dataset;
    delete form.dataset.spoken;
    live = spoken && voice().reply === 'live';
    speakReply = spoken && !live;
    say(null);
    if (!spoken) return;
    mood('thinking');
    startTyping();
  });
  // The settled answer is swapped in over the streaming bubble (chat.js);
  // that is the moment it can be heard.
  document.body.addEventListener('htmx:load', (event) => {
    const button = speakReply && event.detail.elt.matches?.('[data-role=assistant]')
      && event.detail.elt.querySelector('[data-speak]');
    if (!button) return;
    speakReply = false;
    play(button, true);
  });
})();
