/* What the assistant sounds like while it works and has said nothing yet,
   heard instead of it narrating its lookups: the chat's voice (voice.js)
   and the meeting bot's mic (the meetings card, which reads this file into
   its page). Generated, not recorded: bursts of filtered noise, at the
   uneven pace of someone at a desk. The kinds are the voice's working
   sound (``VOICE_WORKING_SOUND``): key taps (typing), papers shuffled
   (papers), or the two mixed (desk).

   workingSound(kind, ear, out): that sound made on the AudioContext ``ear``
   into ``out``, started and stopped (each as often as asked); null for
   "none", or a kind it does not know. */
(() => {
  const between = (low, high) => low + Math.random() * (high - low);

  // One burst of noise, ``seconds`` long, its loudness over its length
  // ``shape`` (0 to 1), through a band around ``pitch``.
  const burst = (ear, out, { seconds, shape, pitch, width, level }) => {
    const buffer = ear.createBuffer(1, Math.ceil(ear.sampleRate * seconds), ear.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * shape(i / data.length);
    const source = ear.createBufferSource();
    const tone = ear.createBiquadFilter();
    const gain = ear.createGain();
    source.buffer = buffer;
    tone.type = 'bandpass';
    tone.frequency.value = pitch;
    tone.Q.value = width;
    gain.gain.value = level;
    source.connect(tone).connect(gain).connect(out);
    source.start();
  };

  // A key: short, sharp, gone at once.
  const tap = (ear, out) => burst(ear, out, {
    seconds: between(0.018, 0.038),
    shape: (at) => (1 - at) ** 3,
    pitch: between(1800, 3600),
    width: 1,
    level: between(0.05, 0.1),
  });
  // A page moved: a soft swell, crackling as it goes.
  const rustle = (ear, out) => burst(ear, out, {
    seconds: between(0.25, 0.6),
    shape: (at) => Math.sin(Math.PI * at) * (Math.random() < 0.03 ? 2.5 : 1),
    pitch: between(2200, 4200),
    width: 0.6,
    level: between(0.025, 0.045),
  });

  // Each kind: what one step plays, and how long until the next (ms).
  const typing = (ear, out) => () => {
    tap(ear, out);
    // Unhurried keys, and often the pause between words.
    return Math.random() < 0.25 ? between(500, 1200) : between(150, 350);
  };
  const papers = (ear, out) => () => {
    rustle(ear, out);
    // Now and then a second page right after, as a stack is squared.
    return Math.random() < 0.3 ? between(250, 450) : between(1500, 3500);
  };
  const desk = (ear, out) => {
    let keys = 0; // taps left in this run of typing
    return () => {
      if (keys > 0) {
        keys -= 1;
        tap(ear, out);
        return Math.random() < 0.2 ? between(400, 900) : between(150, 350);
      }
      keys = Math.round(between(4, 14));
      if (Math.random() < 0.5) rustle(ear, out);
      else tap(ear, out);
      return between(700, 1800);
    };
  };
  const KINDS = { typing, papers, desk };

  function workingSound(kind, ear, out) {
    if (!Object.hasOwn(KINDS, kind)) return null;
    const step = KINDS[kind](ear, out);
    let next = null;
    const keep = () => {
      next = setTimeout(keep, step());
    };
    return {
      start() { if (next === null) keep(); },
      stop() { clearTimeout(next); next = null; },
      get on() { return next !== null; },
    };
  }

  if (typeof window !== 'undefined') window.workingSound = workingSound;
  if (typeof module !== 'undefined') module.exports = { workingSound };
})();
