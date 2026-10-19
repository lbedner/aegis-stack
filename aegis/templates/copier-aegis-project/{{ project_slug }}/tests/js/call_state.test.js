// A live call's rules, each test an ordering a real call threw
// at them. Run: node --test tests/js (tests/web/test_call_state.py runs it
// in the suite).
const test = require('node:test');
const assert = require('node:assert/strict');
const { start, next } = require('../../app/components/web_frontend/static/js/call-state.js');

// The events in turn, from the call as it comes up; what came back from each.
const play = (...events) => {
  let state = start(30000);
  const outs = [];
  for (const event of [{ type: 'begin' }, ...events]) {
    const out = next(state, event);
    state = out.state;
    outs.push(out);
  }
  return { state, outs, last: outs.at(-1) };
};
const speech = (on) => ({ type: 'speech', on });
const audio = (on) => ({ type: 'audio', on });
const step = (on) => ({ type: 'step', on });
const mute = (on) => ({ type: 'mute', on });
const WORDS = { type: 'words' };
const ONSET = { type: 'onset' };
const TURN_END = { type: 'turn_end' };
const HEARD = { type: 'heard' };
const IDLE = { type: 'idle' };
const CUT = { type: 'cut' };
const REPLY = { type: 'reply' };
const GOODBYE = { type: 'goodbye' };
const GRACE = { type: 'grace' };
const hungUp = (outs) => outs.some((out) => out.hangUp);
const LEAVE = { type: 'leave' };
// Its greeting, played out: the call as it usually stands.
const GREETED = [audio(true), audio(false)];
// Quiet until it checked in, and that has played.
const CHECKED_IN = [...GREETED, IDLE, audio(true), audio(false)];
// Quiet again, until its goodbye has played.
const SAID_GOODBYE = [...CHECKED_IN, IDLE, audio(true), audio(false)];

test('the quiet is counted once the call is up', () => {
  assert.equal(play().last.quiet, 'count');
});

test('your talking is never quiet, however long you go on', () => {
  // 2026-10-08: the count started at your first word and hung up mid-sentence.
  const { last, state } = play(...GREETED, speech(true), WORDS);
  assert.equal(play(...GREETED, speech(true)).last.quiet, 'stop');
  assert.notEqual(last.quiet, 'count');
  assert.equal(state.hearing, true);
});

test('its audio is never quiet; the count starts when it has played out', () => {
  assert.equal(play(audio(true)).last.quiet, 'stop');
  assert.equal(play(audio(true), audio(false)).last.quiet, 'count');
});

test('a noise pauses the count but is not you answering its', () => {
  // 2026-10-08: a noise after its check-in reset it, and the countdown went away.
  const { state } = play(...CHECKED_IN, speech(true), speech(false));
  assert.equal(state.nudged, 1);
});

test('words of yours start the count over', () => {
  const { state, last } = play(...CHECKED_IN, WORDS);
  assert.equal(state.nudged, 0);
  assert.equal(last.quiet, 'count');
});

test('it checks in, then says goodbye', () => {
  const { outs } = play(...CHECKED_IN, IDLE);
  assert.deepEqual(
    outs.filter((out) => out.cue).map((out) => out.cue),
    ['check_in', 'goodbye'],
  );
});

test('a check-in it never says still moves on', () => {
  const first = play(...GREETED, IDLE).last;
  assert.equal(first.quiet, 'fallback');
  const { last } = play(...GREETED, IDLE, IDLE);
  assert.equal(last.cue, 'goodbye');
  assert.equal(last.leave, 'arm');
});

test('the call ends a moment after its goodbye has played', () => {
  const played = play(...SAID_GOODBYE);
  assert.equal(played.last.grace, 'arm');
  assert.ok(!hungUp(played.outs)); // not the instant it ends: a moment to say "wait"
  assert.ok(hungUp(play(...SAID_GOODBYE, GRACE).outs));
});

test('it does not end before its goodbye has played', () => {
  // A noise stopping before its goodbye began hung up on the old clock.
  const { outs } = play(...CHECKED_IN, IDLE, speech(true), speech(false));
  assert.ok(!hungUp(outs));
});

test('speaking over its goodbye keeps the call', () => {
  // 2026-10-08: Gemini cut it off, your words were not yet transcribed,
  // and the call hung up in between.
  const leaving = [...CHECKED_IN, IDLE, audio(true)];
  const { state, outs } = play(...leaving, CUT);
  assert.equal(state.leaving, false);
  assert.equal(outs.at(-1).leave, 'stop');
  assert.ok(!hungUp(outs));
});

test('a cut reply\'s "Talk soon." is no goodbye', () => {
  // 2026-10-08: Gemini sent the cut reply's sign-off after you spoke over it.
  const { state } = play(...GREETED, audio(true), CUT, GOODBYE);
  assert.equal(state.leaving, false);
});

test('its next reply is no longer the cut one', () => {
  // OpenAI: the cut lands after that reply is done; your "ok, bye" gets a new
  // reply, whose end_call must still end the call.
  const { state } = play(...GREETED, audio(true), CUT, REPLY, GOODBYE);
  assert.equal(state.leaving, true);
});

test('speaking over the tail of its goodbye keeps the call', () => {
  // Its audio ends on its own with you already talking: no cut comes.
  const tail = [...CHECKED_IN, IDLE, audio(true), speech(true), audio(false)];
  assert.ok(!hungUp(play(...tail).outs));
  assert.notEqual(play(...tail).last.grace, 'arm');
  assert.equal(play(...tail, WORDS).state.leaving, false);
});

test('you starting to speak in the grace holds it', () => {
  const { last } = play(...SAID_GOODBYE, speech(true));
  assert.equal(last.grace, 'stop');
  assert.ok(!hungUp(play(...SAID_GOODBYE, speech(true), GRACE).outs));
});

test('saying "wait" calls its goodbye off', () => {
  // GPT-Live reports no speech onset: each piece of your words comes as speech.
  const { state, outs } = play(...GREETED, GOODBYE, audio(true), speech(true), WORDS, speech(false));
  assert.equal(state.leaving, false);
  assert.equal(outs.at(-2).leave, 'stop');
});

test('muted, the quiet is not counted - muting is on purpose', () => {
  assert.equal(play(...GREETED, mute(true)).last.quiet, 'stop');
  assert.equal(play(...GREETED, mute(true), mute(false)).last.quiet, 'count');
});

test('muting ends whatever the mic was last hearing', () => {
  // 2026-10-08: muted mid-"speech", Gemini never heard it end and the count
  // never started after unmuting.
  const { state, last } = play(...GREETED, speech(true), mute(true), mute(false));
  assert.equal(state.hearing, false);
  assert.equal(last.quiet, 'count');
});

test('a turn the provider ends is owed an answer: no quiet until it begins', () => {
  // 2026-10-19: asked mid-call, it said "Are you still there?" while still
  // working out the answer, and the answer came after.
  const asked = [...GREETED, ONSET, TURN_END];
  assert.notEqual(play(...asked).last.quiet, 'count');
  assert.equal(play(...asked).state.owed, true);
  assert.equal(play(...asked, audio(true), audio(false)).last.quiet, 'count');
  assert.equal(play(...asked, REPLY).last.quiet, 'count'); // a turn with nothing said
});

test('you talking is not quiet from your first sound', () => {
  // 2026-10-19: a long sentence counted as quiet until its transcript came.
  assert.equal(play(...GREETED, ONSET).last.quiet, 'stop');
});

test('a late transcript is owed nothing once the provider reports turns', () => {
  // OpenAI transcribes after the turn: its words can land after the answer.
  const late = [...GREETED, ONSET, TURN_END, audio(true), audio(false)];
  const { state, last } = play(...late, speech(true), WORDS, HEARD);
  assert.equal(state.owed, false);
  assert.equal(last.quiet, 'count');
});

test('without turns from the provider, your transcript ending is the turn', () => {
  // Gemini reports no onset or end: its transcript is all there is.
  const { state, last } = play(...GREETED, speech(true), WORDS, HEARD);
  assert.equal(state.owed, true);
  assert.notEqual(last.quiet, 'count');
});

test('a noise is owed nothing', () => {
  assert.equal(play(...GREETED, speech(true), speech(false)).last.quiet, 'count');
});

test('its steps are not quiet', () => {
  assert.equal(play(...GREETED, step(true)).last.quiet, 'stop');
  assert.equal(play(...GREETED, step(true), step(false)).last.quiet, 'count');
});

test('a profile of 0 seconds never counts', () => {
  const out = next(start(0), { type: 'begin' });
  assert.equal(out.quiet, undefined);
});

// Each engine reports at its own delay - your words are transcribed after
// you spoke, its tool call comes after its audio, its audio plays after it
// is made - so the rules hold for events arriving late, not just in turn.

test('a late transcript of your "bye" does not call its goodbye off', () => {
  // OpenAI transcribes alongside its reply: your words can land after its end_call.
  const { state } = play(...GREETED, speech(true), speech(false), REPLY, audio(true), GOODBYE, WORDS);
  assert.equal(state.leaving, true);
});

test('words you start after its goodbye began do call it off', () => {
  const { state } = play(...GREETED, audio(true), GOODBYE, speech(true), WORDS);
  assert.equal(state.leaving, false);
});

test('the backstop waits while you are speaking', () => {
  // "wait, before you go..." runs past the backstop before it is transcribed.
  const { last } = play(...GREETED, audio(true), GOODBYE, audio(false), speech(true), LEAVE);
  assert.ok(!last.hangUp);
  assert.equal(last.leave, 'arm');
  assert.ok(play(...GREETED, audio(true), GOODBYE, audio(false), LEAVE).last.hangUp);
});

test('its audio starting again holds the hang-up', () => {
  // Its goodbye played, then a last "Bye!" begins within the grace.
  const { last, state } = play(...GREETED, audio(true), GOODBYE, audio(false), audio(true));
  assert.equal(state.played, false);
  assert.equal(last.grace, 'stop');
});

test('a goodbye told after its audio ended ends the call after the grace', () => {
  // A short "Bye." can finish playing before its end_call arrives.
  const { last } = play(...GREETED, audio(true), audio(false), GOODBYE);
  assert.equal(last.grace, 'arm');
});

test("the quiet's own goodbye waits for its to say it", () => {
  // Quiet when the clock runs out - but its goodbye is only cued.
  const { last, state } = play(...CHECKED_IN, IDLE);
  assert.equal(state.played, false);
  assert.notEqual(last.grace, 'arm');
});
