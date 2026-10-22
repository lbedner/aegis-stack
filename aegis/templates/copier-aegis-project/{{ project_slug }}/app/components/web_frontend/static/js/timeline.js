/* The player: plays steps against a clock, for any page that hands it some.

   A page marks a player ``data-player`` and puts its steps inside it as
   JSON (``<script type="application/json" data-play-steps>``): each step
   starts ``at`` and lasts ``ms`` (timeline milliseconds, real ones for a
   replay), lights ``targets`` (CSS selectors within the player) in its
   ``state`` (one of ``RANK``'s). What ran before stays ``done``. The
   player only sets ``data-play-state`` on what a moment lights; CSS
   (input.css) says how each state looks and moves, so a new animation is
   new steps and, at most, new CSS.

   Its controls are any of, inside it: ``[data-play-do=play|back|forward|
   restart]`` buttons, a ``select[data-play-speed]``, an
   ``input[type=range][data-play-seek]``, a ``[data-play-clock]`` and a
   ``[data-play-caption]``, where the latest step to start says what it is
   (a step's ``says``).

   A player may play in scenes, one after another: each a
   ``[data-play-scene=key]`` inside it, shown only from its
   ``data-play-at`` to the next one's, the clock counting its real time
   (``data-play-ms`` long), after any staged beats leading it
   (``data-play-lead``) and held through any after; a ``[data-play-chapter=key]`` button goes to
   its start, and is marked current while it shows.
   With reduced motion, playing moves a step at a time and nothing runs
   between. The pure functions are what the tests load in node
   (tests/web/test_timeline_js.py). */

// Each state a step lights in, strongest first where two light one thing.
const RANK = { failed: 3, stall: 2, refused: 2, active: 1, done: 0 };
const AIM_MS = 2000; // the whole played in at least this long, at its starting speed
const SHOWN_MS = 150; // the least a step stays lit, in real time
const STEP_HOLD_MS = 900; // reduced motion: how long each step holds
const FRAME_MS = 50; // the most real time a frame counts, however late it came

// What ``steps`` light at ``t``: each target's state, the strongest where
// two steps light it; a step that has ended leaves its targets done. A
// step lasts at least ``floor``, so one too short to see still shows.
function frameAt(steps, t, floor = 0) {
  const lit = {};
  steps.forEach((step) => {
    if (t < step.at) return;
    const on = t < step.at + Math.max(step.ms, floor);
    const state = on ? step.state : 'done';
    step.targets.forEach((target) => {
      if (!(target in lit) || RANK[state] > RANK[lit[target]]) lit[target] = state;
    });
  });
  return lit;
}

// When the last step ends.
function endOf(steps) {
  return Math.max(0, ...steps.map((step) => step.at + step.ms));
}

// The next step's start after ``t`` (``way`` 1; the end past the last),
// or the one before it (``way`` -1; the start before the first).
function stepFrom(steps, t, way) {
  const starts = [...new Set(steps.map((step) => step.at))].sort((a, b) => a - b);
  if (way > 0) {
    const next = starts.find((at) => at > t);
    return next === undefined ? endOf(steps) : next;
  }
  const before = starts.filter((at) => at < t);
  return before.length ? before[before.length - 1] : 0;
}

// The clock after ``dt`` real milliseconds at ``speed``, stopping at the
// end; a late frame counts as ``FRAME_MS``, so a slow page load or a tab
// away never skips part of it.
function tick(steps, t, dt, speed) {
  return Math.min(t + Math.min(dt, FRAME_MS) * speed, endOf(steps));
}

// The scene showing at ``t``: the last to start by then (the first
// before any has); null with none.
function sceneAt(scenes, t) {
  const started = scenes.filter((scene) => scene.at <= t);
  return (started.length ? started[started.length - 1] : scenes[0]) || null;
}

// A scene's clock at ``t``: its real time, held at 0 through the beats
// leading it and at its end through any after.
function clockOf(scene, t) {
  return Math.min(Math.max(t - scene.at - scene.lead, 0), scene.ms);
}

// What the moment is, in words: the latest step to start by ``t`` that
// says one.
function saysAt(steps, t) {
  let found = null;
  steps.forEach((step) => {
    if (step.says && step.at <= t && (found === null || step.at >= found.at)) found = step;
  });
  return found ? found.says : '';
}

// The fastest of ``speeds`` (fastest first) that still takes ``AIM_MS``
// to play ``total``; the slowest where none does.
function startingSpeed(total, speeds) {
  return speeds.find((speed) => total / speed >= AIM_MS) || speeds[speeds.length - 1];
}

function readable(ms) {
  return ms < 10 ? `${ms.toFixed(2)} ms` : ms < 1000 ? `${ms.toFixed(1)} ms` : `${(ms / 1000).toFixed(2)} s`;
}

// One player on the page: its steps, its clock and its controls.
function player(root) {
  const steps = JSON.parse(root.querySelector('script[data-play-steps]').textContent);
  const end = endOf(steps);
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const speedPick = root.querySelector('select[data-play-speed]');
  const seek = root.querySelector('input[data-play-seek]');
  const clock = root.querySelector('[data-play-clock]');
  const caption = root.querySelector('[data-play-caption]');
  const scenes = [...root.querySelectorAll('[data-play-scene]')].map((el) => ({
    key: el.dataset.playScene,
    at: Number(el.dataset.playAt),
    lead: Number(el.dataset.playLead || 0),
    ms: Number(el.dataset.playMs),
    el,
  }));
  let t = 0;
  // The speeds offered (the select's, macros/player.html); real time alone without one.
  const speeds = speedPick ? [...speedPick.options].map((option) => Number(option.value)) : [1];
  let speed = startingSpeed(end, speeds);
  let running = null;
  // Each target's elements, looked up once; what each lit one shows.
  const found = new Map();
  const elementsOf = (target) => {
    if (!found.has(target)) found.set(target, [...root.querySelectorAll(target)]);
    return found.get(target);
  };
  const chapters = [...root.querySelectorAll('[data-play-chapter]')];
  let lit = new Map();
  let shownScene = null;
  let said = null;
  if (speedPick) speedPick.value = String(speed);
  if (seek) seek.max = String(end);

  // The moment drawn: only what changed since the last is touched.
  function show() {
    const now = new Map();
    Object.entries(frameAt(steps, t, SHOWN_MS * speed)).forEach(([target, state]) => {
      elementsOf(target).forEach((el) => {
        if (!now.has(el) || RANK[state] > RANK[now.get(el)]) now.set(el, state);
      });
    });
    lit.forEach((_, el) => {
      if (!now.has(el)) el.removeAttribute('data-play-state');
    });
    now.forEach((state, el) => {
      if (lit.get(el) !== state) el.setAttribute('data-play-state', state);
    });
    lit = now;
    root.toggleAttribute('data-playing', running !== null);
    if (seek) seek.value = String(t);
    const shown = sceneAt(scenes, t);
    if (shown !== shownScene) {
      shownScene = shown;
      scenes.forEach((scene) => {
        scene.el.hidden = scene !== shown;
      });
      chapters.forEach((chapter) => {
        chapter.toggleAttribute('aria-current', shown !== null && chapter.dataset.playChapter === shown.key);
      });
    }
    const says = saysAt(steps, t);
    if (caption && says !== said) {
      said = says;
      caption.textContent = says;
    }
    if (clock) {
      clock.textContent = shown
        ? `${readable(clockOf(shown, t))} of ${readable(shown.ms)}`
        : `${readable(t)} of ${readable(end)}`;
    }
  }
  function stop() {
    if (running !== null) (reduced ? clearInterval : cancelAnimationFrame)(running);
    running = null;
    show();
  }
  function play() {
    if (t >= end) t = 0;
    if (reduced) {
      running = setInterval(() => {
        t = stepFrom(steps, t, 1);
        if (t >= end) stop();
        else show();
      }, STEP_HOLD_MS);
      show();
      return;
    }
    let last = performance.now();
    const frame = (now) => {
      t = tick(steps, t, now - last, speed);
      last = now;
      if (t >= end) {
        stop();
        return;
      }
      show();
      running = requestAnimationFrame(frame);
    };
    running = requestAnimationFrame(frame);
    show();
  }
  const actions = {
    play: () => (running === null ? play() : stop()),
    back: () => { stop(); t = stepFrom(steps, t, -1); show(); },
    forward: () => { stop(); t = stepFrom(steps, t, 1); show(); },
    restart: () => { stop(); t = 0; play(); },
  };
  root.addEventListener('click', (event) => {
    const button = event.target.closest('[data-play-do]');
    if (button && root.contains(button)) actions[button.dataset.playDo]();
    const chapter = event.target.closest('[data-play-chapter]');
    const scene = chapter && scenes.find((found) => found.key === chapter.dataset.playChapter);
    if (scene) {
      stop();
      t = scene.at;
      show();
    }
  });
  if (speedPick) speedPick.addEventListener('change', () => { speed = Number(speedPick.value); show(); });
  if (seek) seek.addEventListener('input', () => { stop(); t = Number(seek.value); show(); });
  show();
  if (!reduced) play();
}

if (typeof document !== 'undefined') {
  const started = new WeakSet();
  const startAll = () => document.querySelectorAll('[data-player]').forEach((root) => {
    if (started.has(root)) return;
    started.add(root);
    player(root);
  });
  document.addEventListener('DOMContentLoaded', startAll);
  document.addEventListener('htmx:load', startAll);
}

if (typeof module !== 'undefined') module.exports = { frameAt, endOf, stepFrom, tick, startingSpeed, sceneAt, saysAt, clockOf };
