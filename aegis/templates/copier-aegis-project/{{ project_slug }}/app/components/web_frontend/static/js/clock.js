/* The scheduler clock (Overseer > Scheduler > Overview): move a job.

   The hand always shows now. Pick a job (its dot or its legend row) and drag
   it around the ring, or nudge it with the arrow keys: the centre reads its
   new time, and any job its run would now overlap is flagged. Nothing is
   saved; Reset puts it back.

   The server draws the dial and rotates each job's slot to its angle
   (ui_scheduler.clock); moving a job only changes that rotation, so no
   geometry is repeated here. The pure functions are what the tests load in
   node (tests/web/test_clock_js.py). */

const DAY_DEGREES = 360;
const SNAP_DEGREES = 1.25; // five minutes
const STEP_DEGREES = 3.75; // one arrow-key press: fifteen minutes

const wrap = (angle) => ((angle % DAY_DEGREES) + DAY_DEGREES) % DAY_DEGREES;

// The nearest five minutes to ``angle``.
function snap(angle) {
  return wrap(Math.round(angle / SNAP_DEGREES) * SNAP_DEGREES);
}

// Whether a run from ``a`` for ``sa`` degrees and one from ``b`` for ``sb``
// degrees share any moment of the day (either may run past midnight).
function overlaps(a, sa, b, sb) {
  return wrap(b - a) <= sa || wrap(a - b) <= sb;
}

// The time of day at ``angle``, "HH:MM".
function clockTime(angle) {
  const minutes = Math.floor(wrap(angle) * 4);
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`;
}

// Degrees clockwise from the top for a point ``dx``, ``dy`` from the centre
// (screen coordinates: y grows downwards).
function pointerAngle(dx, dy) {
  return Math.round(wrap((Math.atan2(dx, -dy) * 180) / Math.PI));
}

if (typeof document !== 'undefined') {
  document.addEventListener('alpine:init', () => {
    Alpine.data('schedulerClock', () => ({
      selected: null, // the picked job's id
      hovered: null, // the job under the pointer (or keyboard focus)
      dragging: null, // the job being dragged, while the pointer is down
      dragged: false, // the pointer moved a job since it went down
      moved: {}, // job id -> new angle, for jobs moved from where they are

      slot(id) {
        return this.$root.querySelector(`.clock__slot[data-job-id="${CSS.escape(id)}"]`);
      },
      home(id) {
        return Number(this.slot(id).dataset.angle);
      },
      angleOf(id) {
        return this.moved[id] ?? this.home(id);
      },
      sweepOf(id) {
        return Number(this.slot(id).dataset.sweep || 0);
      },
      moveTo(id, angle) {
        const to = snap(angle);
        if (to === this.home(id)) delete this.moved[id];
        else this.moved[id] = to;
      },

      select(id) {
        this.selected = id;
      },
      hover(id) {
        this.hovered = id;
      },
      unhover(id) {
        if (this.hovered === id) this.hovered = null;
      },
      grab(event, id) {
        this.select(id);
        this.dragging = id;
        this.dragged = false;
        this.$refs.dial.setPointerCapture(event.pointerId);
      },
      drag(event) {
        if (!this.dragging) return;
        this.dragged = true;
        const box = this.$refs.dial.getBoundingClientRect();
        this.moveTo(
          this.dragging,
          pointerAngle(
            event.clientX - (box.left + box.width / 2),
            event.clientY - (box.top + box.height / 2),
          ),
        );
      },
      release() {
        this.dragging = null;
      },
      step(id, direction) {
        this.select(id);
        this.moveTo(id, this.angleOf(id) + direction * STEP_DEGREES);
      },
      reset() {
        if (this.selected) delete this.moved[this.selected];
      },
      // Back to how the page loaded: nothing picked, unsaved moves dropped.
      neutral() {
        this.selected = null;
        this.moved = {};
      },
      // A click on the dial that is not on a job or a button clears too,
      // except the one that ends a drag: the dial holds the pointer while a
      // job is dragged, so letting go "clicks" the dial itself.
      clickDial(event) {
        if (this.dragged) {
          this.dragged = false;
          return;
        }
        if (!event.target.closest('button')) this.neutral();
      },

      // Bindings the template uses.
      // Turns a job's slot to its current angle, moved or not. Set directly
      // rather than through :style: Alpine's style bookkeeping does not
      // handle custom properties reliably, and a dropped --angle drew the
      // job at 00:00.
      place(el, id) {
        el.style.setProperty('--angle', `${this.angleOf(id)}deg`);
      },
      stateOf(id) {
        if (id === this.selected) return 'selected';
        const active = this.selected;
        if (
          active &&
          active in this.moved &&
          overlaps(this.angleOf(active), this.sweepOf(active), this.angleOf(id), this.sweepOf(id))
        ) {
          return 'conflict';
        }
        return id === this.hovered ? 'hover' : '';
      },
      timeOf(id) {
        return id ? clockTime(this.angleOf(id)) : '';
      },
      movedFrom(id) {
        return id in this.moved ? clockTime(this.home(id)) : '';
      },
      nameOf(id) {
        return id ? this.slot(id).dataset.name : '';
      },
      isMoved() {
        return Boolean(this.selected) && this.selected in this.moved;
      },
    }));
  });
}

if (typeof module !== 'undefined') module.exports = { snap, overlaps, clockTime, pointerAngle };
