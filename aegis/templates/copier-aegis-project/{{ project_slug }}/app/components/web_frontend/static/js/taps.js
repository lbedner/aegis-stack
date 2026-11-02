/* Soft key taps while the assistant works and has said nothing yet, heard
   instead of it narrating its lookups: the chat's voice (voice.js) and the
   meeting bot's mic (the meetings card, which reads this file into its
   page). Generated, not a recording: a short burst of filtered noise per
   key, at the uneven pace of someone typing.

   keyTaps(ear, out): taps made on the AudioContext ``ear`` into ``out``,
   started and stopped (each as often as asked). */
window.keyTaps = (ear, out) => {
  let next = null;
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
    source.connect(tone).connect(level).connect(out);
    source.start();
  };
  const keep = () => {
    tap();
    // Unhurried keys, and often the pause between words.
    next = setTimeout(keep, Math.random() < 0.25 ? 500 + Math.random() * 700 : 150 + Math.random() * 200);
  };
  return {
    start() { if (next === null) keep(); },
    stop() { clearTimeout(next); next = null; },
    get on() { return next !== null; },
  };
};
