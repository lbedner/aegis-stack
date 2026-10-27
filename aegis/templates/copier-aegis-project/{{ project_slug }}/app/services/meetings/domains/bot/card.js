// The agent's card in a call (card.py): defines window.__meetingCard and
// answers getUserMedia before the page's own scripts run. __START__ is the
// card as it joins. The card's colors are the house's (teal on the dark
// card, for state and checks only). With nothing in flight it is the
// agent, centered: its picture, name and status. With a request in flight
// it presents it (``focus``): the agent small at the top left with its
// state, the question as the headline, what it is doing, then its answer
// in brief on a panel; the others are pills along the foot (``pills``: up
// next, and earlier). The bottom right stays empty: Meet lays the host's
// own picture there. Drawn at twice the size (``SCALE``), for a sharp
// picture once Meet has compressed it.
(() => {
  if (window.top !== window) return;
  const W = 640, H = 360, TEAL = '#17CCBF', DARK = '#0f172a', LIGHT = '#f8fafc';
  const MUTED = '#94a3b8', PANEL = '#18223a';
  const SCALE = 2;
  // Kept clear of the edges: Meet crops a tile to fit, and lays its own
  // controls over the bot's preview at the bottom.
  const EDGE = 36, M = 24;
  // The corner Meet lays the host's own picture over: nothing drawn there.
  const PIP_W = 170, PIP_H = 100;
  const card = __START__;
  const canvas = document.createElement('canvas');
  canvas.width = W * SCALE;
  canvas.height = H * SCALE;
  let picture = null, widest = 0;
  // Frames a second, steady whether or not the card changed: at two, and
  // in bursts, Meet left a change half drawn (the old card's ghost) or not
  // drawn at all. An unchanged card costs the encoder next to nothing.
  const FPS = 10;

  function avatar(g, cx, cy, r) {
    g.save();
    g.beginPath();
    g.arc(cx, cy, r, 0, Math.PI * 2);
    g.clip();
    if (picture) {
      g.drawImage(picture, cx - r, cy - r, r * 2, r * 2);
    } else {
      g.fillStyle = TEAL;
      g.fillRect(cx - r, cy - r, r * 2, r * 2);
      g.fillStyle = DARK;
      g.font = `bold ${Math.round(r * 0.86)}px sans-serif`;
      g.textAlign = 'center';
      g.textBaseline = 'middle';
      g.fillText(card.initials, cx, cy);
    }
    g.restore();
  }

  function idle(g) {
    const cx = W / 2;
    avatar(g, cx, 112, 84);
    g.textAlign = 'center';
    g.fillStyle = LIGHT;
    g.font = '600 32px sans-serif';
    g.fillText(card.name, cx, 240);
    g.fillStyle = TEAL;
    g.font = '24px sans-serif';
    g.fillText(card.status, cx, 276);
  }

  // ``text`` in lines no wider than ``width``, at most ``most`` of them, the
  // last cut with an ellipsis where it runs on.
  function lines(g, text, width, most) {
    const words = text.split(/\s+/).filter(Boolean);
    const out = [];
    let line = '', at = 0;
    for (; at < words.length; at++) {
      const next = line ? `${line} ${words[at]}` : words[at];
      if (!line || g.measureText(next).width <= width) {
        line = next;
        continue;
      }
      out.push(line);
      line = words[at];
      if (out.length === most) {
        line = '';
        break;
      }
    }
    if (line) out.push(line);
    const last = out.length - 1;
    if (last >= 0 && (at < words.length || g.measureText(out[last]).width > width)) {
      let cut = out[last];
      while (cut && g.measureText(`${cut}\u2026`).width > width) cut = cut.slice(0, -1);
      out[last] = `${cut.trimEnd()}\u2026`;
    }
    return out;
  }

  function write(g, text, x, y) {
    g.fillText(text, x, y);
    widest = Math.max(widest, x + g.measureText(text).width);
    return y;
  }

  function rounded(g, x, y, w, h, r) {
    g.beginPath();
    g.roundRect(x, y, w, h, r);
    g.fill();
  }

  // A request in flight, presented: the agent and its state at the top
  // left, the question, what it is doing (or its answer in brief, on a
  // panel), the others as pills along the foot.
  function working(g) {
    const focus = card.focus, width = W - M * 2, r = 13;
    avatar(g, M + r, M + r, r);
    g.textAlign = 'left';
    g.fillStyle = LIGHT;
    g.font = '600 15px sans-serif';
    write(g, card.name, M + r * 2 + 10, M + 18);
    const named = M + r * 2 + 10 + g.measureText(card.name).width + 10;
    g.fillStyle = TEAL;
    g.font = '14px sans-serif';
    const steps = focus.steps ? ` · step ${focus.steps}` : '';
    write(g, `${card.status}${steps}`, named, M + 18);

    g.fillStyle = MUTED;
    g.font = '600 11px sans-serif';
    write(g, 'QUESTION', M, M + 58);
    g.fillStyle = LIGHT;
    g.font = '600 24px sans-serif';
    let y = M + 88;
    for (const line of lines(g, focus.question, width, 2)) y = write(g, line, M, y) + 30;

    if (focus.verdict) {
      panel(g, focus, y - 10);
    } else {
      // What it is doing, then what it is saying meanwhile, in its words.
      let at = y - 2;
      if (focus.step || !focus.voice) {
        g.fillStyle = TEAL;
        g.font = '15px sans-serif';
        const doing = focus.step ? `◌ ${focus.step}` : focus.status;
        write(g, lines(g, doing, width, 1)[0] || '', M, at);
        at += 30;
      }
      if (focus.voice) {
        g.fillStyle = MUTED;
        g.font = 'italic 17px sans-serif';
        const room = W - M * 2 - PIP_W - 12;
        for (const line of lines(g, `“${focus.voice}”`, room, 2)) {
          at = write(g, line, M, at) + 24;
        }
      }
    }
    foot(g);
  }

  // The answer in brief: its verdict, then a line of detail, kept left of
  // the host's corner.
  function panel(g, focus, top) {
    const w = W - M * 2 - PIP_W - 12, pad = 14;
    g.font = '600 17px sans-serif';
    const verdict = lines(g, focus.verdict, w - pad * 2, 2);
    g.font = '14px sans-serif';
    const detail = focus.detail ? lines(g, focus.detail, w - pad * 2, 2) : [];
    const h = pad + verdict.length * 22 + (detail.length ? 6 + detail.length * 19 : 0) + 8;
    g.fillStyle = PANEL;
    rounded(g, M, top, w, h, 10);
    let y = top + pad + 15;
    g.fillStyle = LIGHT;
    g.font = '600 17px sans-serif';
    for (const line of verdict) y = write(g, line, M + pad, y) + 22;
    g.fillStyle = MUTED;
    g.font = '14px sans-serif';
    y += 4;
    for (const line of detail) y = write(g, line, M + pad, y) + 19;
  }

  // The other requests, a pill each along the foot: up next, then earlier
  // (checked, or crossed where it found nothing). What does not fit before
  // the host's corner is left off.
  function foot(g) {
    const stop = W - M - PIP_W - 12, base = H - M - 8;
    let x = M;
    for (const [label, marks] of [['Next', ['next']], ['Earlier', ['answered', 'failed']]]) {
      const pills = (card.pills || []).filter((p) => marks.includes(p.mark));
      if (!pills.length) continue;
      g.font = '12px sans-serif';
      g.fillStyle = MUTED;
      const labelled = g.measureText(label).width;
      if (x + labelled + 60 > stop) break;
      write(g, label, x, base);
      x += labelled + 10;
      for (const pill of pills) {
        const mark = pill.mark === 'answered' ? '✓ ' : pill.mark === 'failed' ? '✗ ' : '';
        g.font = '13px sans-serif';
        const room = Math.min(220, stop - x - 16 - g.measureText(mark).width);
        if (room < 50) break;
        const text = lines(g, pill.question, room, 1)[0] || '';
        const w = 16 + g.measureText(mark + text).width;
        g.fillStyle = PANEL;
        rounded(g, x, base - 17, w, 24, 6);
        g.fillStyle = pill.mark === 'answered' ? TEAL : MUTED;
        write(g, mark, x + 8, base);
        g.fillStyle = LIGHT;
        write(g, text, x + 8 + g.measureText(mark).width, base);
        x += w + 8;
      }
      x += 8;
    }
  }

  function draw() {
    const g = canvas.getContext('2d');
    g.setTransform(SCALE, 0, 0, SCALE, 0, 0);
    g.fillStyle = DARK;
    g.fillRect(0, 0, W, H);
    g.textBaseline = 'alphabetic';
    widest = 0;
    (card.focus ? working : idle)(g);
  }

  // Whether the host's corner is empty: nothing drawn but the card.
  function cornerClear() {
    const g = canvas.getContext('2d');
    const x = (W - M - PIP_W) * SCALE, y = (H - M - PIP_H) * SCALE;
    const seen = g.getImageData(x, y, canvas.width - x, canvas.height - y).data;
    const dark = [15, 23, 42];
    for (let i = 0; i < seen.length; i += 4) {
      if (seen[i] !== dark[0] || seen[i + 1] !== dark[1] || seen[i + 2] !== dark[2]) return false;
    }
    return true;
  }

  function picture_of(src) {
    picture = null;
    if (!src) return;
    const image = new Image();
    image.onload = () => { picture = image; draw(); };
    image.src = src;
  }
  const video = canvas.captureStream(0).getVideoTracks()[0];
  setInterval(() => video.requestFrame(), 1000 / FPS);
  let voice = null, mic = null, until = 0;
  function microphone() {
    if (!voice) {
      voice = new AudioContext();
      mic = voice.createMediaStreamDestination();
    }
    return mic;
  }
  function bytes(encoded) {
    return Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
  }
  // Every sound into the mic plays after what is already playing (a line
  // said and a live voice's pieces alike); how long is still to play.
  function queue(sound) {
    const source = voice.createBufferSource();
    source.buffer = sound;
    source.connect(mic);
    const at = Math.max(voice.currentTime, until);
    source.start(at);
    until = at + sound.duration;
    return until - voice.currentTime;
  }
  window.__meetingCard = {
    show(update) {
      Object.assign(card, update);
      if ('image' in update) picture_of(update.image);
      draw();
    },
    async speak(audio) {
      microphone();
      await voice.resume();
      return queue(await voice.decodeAudioData(bytes(audio).buffer));
    },
    async stream(pcm, rate) {
      microphone();
      await voice.resume();
      const raw = bytes(pcm);
      const samples = new Int16Array(raw.buffer, 0, raw.length >> 1);
      const sound = voice.createBuffer(1, samples.length, rate);
      const level = sound.getChannelData(0);
      for (let i = 0; i < samples.length; i++) level[i] = samples[i] / 32768;
      return queue(sound);
    },
    picture() { return canvas.toDataURL(); },
    // How far right the last drawing's text reached: never past the card.
    widest() { return widest; },
    cornerClear,
  };
  const devices = navigator.mediaDevices;
  devices.getUserMedia = async (asked = {}) => {
    const tracks = [];
    if (asked.video && card.camera) tracks.push(video.clone());
    if (asked.audio) tracks.push(microphone().stream.getAudioTracks()[0].clone());
    if (!tracks.length) throw new DOMException('No camera', 'NotAllowedError');
    return new MediaStream(tracks);
  };
  const listed = [
    ['videoinput', 'card', 'Agent card'],
    ['audioinput', 'voice', 'Agent voice'],
    ['audiooutput', 'speaker', 'Agent speaker'],
  ].map(([kind, deviceId, label]) => {
    const device = {kind, deviceId, label, groupId: 'agent'};
    return {...device, toJSON: () => device};
  });
  devices.enumerateDevices = async () =>
    listed.filter((d) => d.kind !== 'videoinput' || card.camera);
  draw();
})()
