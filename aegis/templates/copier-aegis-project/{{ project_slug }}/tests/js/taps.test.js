// The sounds the assistant makes while it works (taps.js): each kind
// plays and stops, and "none" (or one it does not know) is no sound.
// Run: node --test tests/js.
const test = require('node:test');
const assert = require('node:assert/strict');
const { workingSound } = require('../../app/components/web_frontend/static/js/taps.js');

// An AudioContext's parts as taps.js uses them, counting what is played.
function fakeEar() {
  const ear = { sampleRate: 8000, currentTime: 0, played: 0 };
  const node = () => ({ connect: (next) => next, frequency: {}, Q: {}, gain: {} });
  ear.createBuffer = (_, length) => ({ getChannelData: () => new Float32Array(length) });
  ear.createBufferSource = () => ({ ...node(), start: () => { ear.played += 1; } });
  ear.createBiquadFilter = node;
  ear.createGain = node;
  return ear;
}

for (const kind of ['typing', 'papers', 'desk']) {
  test(`${kind} plays once started and stops when asked`, () => {
    const ear = fakeEar();
    const sound = workingSound(kind, ear, {});
    sound.start();
    assert.ok(sound.on);
    assert.ok(ear.played > 0);
    sound.stop();
    assert.equal(sound.on, false);
  });
}

test('no sound for none, or a kind it does not know', () => {
  assert.equal(workingSound('none', fakeEar(), {}), null);
  assert.equal(workingSound('kazoo', fakeEar(), {}), null);
});
