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
   text. Audio is never kept.

   The phone beside the microphone is a live call (the end of this file):
   one path for every engine, over the chat mount's WebSocket. */
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
  const box = () => chatComposer()?.querySelector('textarea');
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

  // The microphone, once the browser allows it; ``needs`` is what the
  // caller records with (MediaRecorder, an AudioWorklet), so a browser
  // without it is told so rather than failing later.
  const microphone = async (needs) => {
    if (!navigator.mediaDevices?.getUserMedia || !needs) {
      say('unsupported');
      return null;
    }
    try {
      return await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      say(e.name === 'NotAllowedError' ? 'denied' : 'unsupported');
      return null;
    }
  };

  const start = async (button) => {
    const stream = await microphone(window.MediaRecorder);
    if (!stream) return;
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
    // A form's preview speaks the form's current fields, unsaved.
    const form = 'speakForm' in button.dataset && button.closest('form');
    const query = form ? `?${new URLSearchParams(new FormData(form))}` : '';
    show(button, 'thinking'); // fetching and synthesizing
    player = voiced(`${button.dataset.speak}${query}`, button, reply);
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

  // --- A live call: one path for every engine ------------------------------
  // The server holds the engine's session; this page carries the audio over
  // the mount's WebSocket. The mic is captured at the model's input rate (an
  // AudioWorklet, mic-worklet.js) and sent as PCM16; the voice comes back as
  // PCM16 at its output rate and is scheduled gap-free. The server says what
  // the call is doing in small JSON events; the thread reloads as each turn
  // is saved, steps and cards and all.
  let call = null;
  const phone = () => document.getElementById('chat-live');
  const callBar = () => document.getElementById('chat-call');
  const FRAME = 640; // samples a frame: 40ms at 16 kHz
  // How long a saved turn takes to land before the thread is reloaded.
  const SAVE_MS = 1500;
  const engaged = (control) => {
    show(control, 'thinking');
    control.setAttribute('aria-pressed', 'true');
  };
  const hangUp = () => {
    if (!call || call.closing) return;
    call.closing = true;
    for (const track of call.stream.getTracks()) track.stop();
    call.ws.close();
    call.mic?.close();
    call.speaker?.close();
    // A turn saved as the call closed never reached this page.
    showSaved(call.conversation);
    clearTimeout(call.quiet);
    clearTimeout(call.idle);
    stopTyping();
    stopBar();
    show(phone(), 'idle');
    phone()?.setAttribute('aria-pressed', 'false');
    say(null);
    call = null;
  };
  // --- The call bar: the composer row gives way to it for the call. The
  // cost is the server's, priced as each turn is saved.
  const field = (name) => callBar()?.querySelector(`[data-call-${name}]`);
  const showCost = (dollars) => { field('cost').textContent = `$${dollars.toFixed(2)}`; };
  const clock = (seconds) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
  const tick = () => {
    if (call) field('timer').textContent = clock((Date.now() - call.started) / 1000);
  };
  const startBar = (engine) => {
    call.started = Date.now();
    field('engine').textContent = engine?.label || '';
    field('cost').textContent = '';
    field('cost-later').hidden = false;
    chatComposer().hidden = true;
    callBar().hidden = false;
    call.ticker = setInterval(tick, 1000);
    tick();
  };
  const stopBar = () => {
    clearInterval(call?.ticker);
    muted(false);
    if (callBar()) callBar().hidden = true;
    if (chatComposer()) chatComposer().hidden = false;
  };
  // Mute: the mic stops going out, and dead air does not count meanwhile.
  const muted = (on) => {
    document.getElementById('chat-mute')?.setAttribute('aria-pressed', String(on));
    if (!call) return;
    call.muted = on;
    if (on) {
      clearTimeout(call.idle);
      say('muted');
    } else {
      rest();
    }
  };
  // Dead air costs the same as talk: after the profile's seconds with
  // nobody speaking and nothing being worked on, hang up (0: never).
  const awake = () => {
    if (!call || call.closing || call.muted) return;
    clearTimeout(call.idle);
    const seconds = voice().idle;
    if (seconds > 0 && !call.working) call.idle = setTimeout(hangUp, seconds * 1000);
  };
  // Between replies the call is listening, or - while the agent runs a
  // step - working, with the typing under it.
  const rest = () => {
    if (!call || call.closing) return;
    const working = call.working > 0;
    show(phone(), working ? 'working' : 'recording');
    say(call.muted ? 'muted' : working ? 'working' : 'live', working ? call.step : null);
    if (working) startTyping();
    else stopTyping();
    awake();
  };
  // The assistant is talking: no typing under it, no dead-air hang-up.
  const speaking = () => {
    stopTyping();
    clearTimeout(call.idle);
    show(phone(), 'speaking');
  };
  const stepping = (step) => {
    call.working += 1;
    call.step = step;
    rest();
  };
  const stepped = () => {
    call.working = 0;
    call.step = null;
    rest();
  };
  // The thread, reloaded so a saved turn shows with its steps and cards.
  const showTurns = (id) => {
    if (!id) return;
    setConversation(id);
    htmx.ajax('GET', phone().dataset.thread + id, { target: chatThread(), swap: 'innerHTML' });
  };
  const showSaved = (id) => setTimeout(() => showTurns(id), SAVE_MS);
  const pcm16 = (samples) => {
    const out = new Int16Array(samples.length);
    for (let i = 0; i < samples.length; i++) out[i] = Math.max(-1, Math.min(1, samples[i])) * 0x7fff;
    return out.buffer;
  };
  const listen = async (rate) => {
    call.mic = new AudioContext({ sampleRate: rate });
    await call.mic.audioWorklet.addModule(phone().dataset.worklet);
    const node = new AudioWorkletNode(call.mic, 'mic-pcm');
    let batch = [];
    node.port.onmessage = ({ data }) => {
      if (!call || call.muted || call.ws.readyState !== WebSocket.OPEN) return;
      batch.push(...data);
      if (batch.length < FRAME) return;
      call.ws.send(pcm16(batch));
      batch = [];
    };
    call.mic.createMediaStreamSource(call.stream).connect(node);
  };
  // The voice, each chunk queued behind the last; the call shows it
  // speaking until the queue has played out.
  const voiceChunk = (data) => {
    if (!call?.speaker) return;
    const samples = new Int16Array(data);
    const buffer = call.speaker.createBuffer(1, samples.length, call.speaker.sampleRate);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++) channel[i] = samples[i] / 0x8000;
    const node = call.speaker.createBufferSource();
    node.buffer = buffer;
    node.connect(call.speaker.destination);
    const at = Math.max(call.speaker.currentTime, call.playhead);
    node.start(at);
    call.playhead = at + buffer.duration;
    call.sources.push(node);
    node.onended = () => { if (call) call.sources = call.sources.filter((s) => s !== node); };
    speaking();
    clearTimeout(call.quiet);
    call.quiet = setTimeout(spoken, (call.playhead - call.speaker.currentTime) * 1000 + 300);
  };
  // The voice has played out: listening again, or - after the goodbye -
  // hanging up.
  const spoken = () => {
    if (!call) return;
    if (call.signingOff) return hangUp();
    rest();
  };
  // The agent ended the call: hang up once its goodbye has played out, or
  // shortly if none is queued.
  const signOff = () => {
    call.signingOff = true;
    if (!call.sources.length) setTimeout(spoken, 1500);
  };
  // Spoken over: what was not yet heard is dropped.
  const interrupted = () => {
    for (const node of call.sources) try { node.stop(); } catch (_) {}
    call.sources = [];
    call.playhead = 0;
    clearTimeout(call.quiet);
    rest();
  };
  const relayed = async (event) => {
    if (!call) return;
    if (event.type === 'ready') {
      call.ready = true;
      call.conversation = event.conversation_id;
      setConversation(event.conversation_id);
      call.speaker = new AudioContext({ sampleRate: event.output_rate });
      try {
        await listen(event.input_rate);
      } catch (e) {
        console.warn('[live]', e);
        hangUp();
        return say('unsupported');
      }
      startBar(event.engine);
      rest();
    } else if (event.type === 'interrupted') {
      interrupted();
    } else if (event.type === 'heard') {
      awake();
    } else if (event.type === 'hang_up') {
      signOff();
    } else if (event.type === 'working') {
      stepping(event.label);
    } else if (event.type === 'done' && call.working) {
      stepped();
    } else if (event.type === 'card') {
      // A chart up while it is talked about; the saved turn replaces it.
      const slot = clone('chat-live-card');
      chatThread().append(slot);
      htmx.ajax('GET', event.url, { target: slot, swap: 'innerHTML' });
    } else if (event.type === 'saved') {
      showTurns(call.conversation);
      showCost(event.cost);
      field('cost-later').hidden = true;
    }
  };
  const dial = async (button) => {
    const stream = await microphone(window.AudioWorkletNode);
    if (!stream) return;
    const url = new URL(button.dataset.relay, location.href);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    if (conversationId()) url.searchParams.set('conversation_id', conversationId());
    const ws = new WebSocket(url);
    ws.binaryType = 'arraybuffer';
    call = { ws, stream, sources: [], playhead: 0, working: 0, idle: null, quiet: null };
    engaged(button);
    ws.addEventListener('message', ({ data }) => (typeof data === 'string' ? relayed(JSON.parse(data)) : voiceChunk(data)));
    ws.addEventListener('close', () => {
      if (call?.ws !== ws || call.closing) return;
      const opened = call.ready;
      hangUp();
      if (!opened) say('offline');
    });
  };
  document.addEventListener('click', (event) => {
    if (event.target.closest?.('#chat-mute')) return call && muted(!call.muted);
    if (event.target.closest?.('#chat-hang-up')) return hangUp();
    const button = event.target.closest?.('#chat-live');
    if (!button) return;
    ear ??= new AudioContext();
    if (call) return hangUp();
    hush();
    dial(button);
  });
})();
