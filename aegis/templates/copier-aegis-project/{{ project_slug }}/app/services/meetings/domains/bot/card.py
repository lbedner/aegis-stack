"""The agent's card in a call: what its camera shows (its image, or its
initials, its name and what it is doing) and the voice its microphone
carries.

The page is hooked before Meet loads (``script``): Meet's camera and
microphone requests are answered by the page itself, the camera with a
canvas the card is drawn on, the microphone with a track that carries
only what the bot says (``speak``). The browser has no devices of its
own, so the page lists these as its camera, microphone and speaker; with
none, Meet says "Camera not found" and never asks. The canvas is redrawn only when the
card changes (``show``) and sent a frame every half second, so a browser
with no GPU is not kept busy. An agent with its camera off gives Meet no
picture at all. The script runs in the page itself, never in the frames
Meet opens inside it, and carries no picture: its initials stand until
the page has loaded and the picture is handed over (``open_meet``).
"""

import base64
import json

from playwright.async_api import Page
from pydantic import BaseModel

from app.services.meetings.models import CLAIMED

LISTENING = "Listening"
NO_CAPTIONS = "Can't see captions"
QUESTION_HEARD = "Question heard"
ANSWERING = "Answering"
LEAVING = "Leaving"


class Start(BaseModel):
    """The card as the bot joins: who it is, its image (a data URL) and
    whether its camera is on."""

    name: str
    image: str | None = None
    camera: bool = True


def status_of(captions: bool, going: set[str]) -> str:
    """What the bot is doing, from what it knows: answering a question a
    runner has taken (``going``: the call's runs not yet done), one heard
    and waiting, captions it cannot see (nothing is being written), else
    listening."""
    if CLAIMED in going:
        return ANSWERING
    if going:
        return QUESTION_HEARD
    return LISTENING if captions else NO_CAPTIONS


def initials(name: str) -> str:
    """What stands for an agent with no image: the first letter of each
    of its first two words."""
    letters = [word[0] for word in name.split()[:2]]
    return "".join(letters).upper() or "?"


# Defines ``window.__meetingCard`` and answers getUserMedia before the
# page's own scripts run. The card's colors are the house's (teal on the
# dark card).
CARD = """(() => {
  if (window.top !== window) return;
  const W = 640, H = 360, TEAL = '#17CCBF', DARK = '#0f172a', LIGHT = '#f8fafc';
  const card = __START__;
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  let picture = null;
  function draw() {
    const g = canvas.getContext('2d');
    // Kept clear of the bottom edge: Meet crops a tile, and lays its own
    // controls over the bot's preview there.
    const r = 84, cx = W / 2, cy = 112;
    g.fillStyle = DARK;
    g.fillRect(0, 0, W, H);
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
      g.font = 'bold 72px sans-serif';
      g.textAlign = 'center';
      g.textBaseline = 'middle';
      g.fillText(card.initials, cx, cy);
    }
    g.restore();
    g.textAlign = 'center';
    g.textBaseline = 'alphabetic';
    g.fillStyle = LIGHT;
    g.font = '600 32px sans-serif';
    g.fillText(card.name, cx, 240);
    g.fillStyle = TEAL;
    g.font = '24px sans-serif';
    g.fillText(card.status, cx, 276);
  }
  function picture_of(src) {
    picture = null;
    if (!src) return;
    const image = new Image();
    image.onload = () => { picture = image; draw(); };
    image.src = src;
  }
  const video = canvas.captureStream(0).getVideoTracks()[0];
  setInterval(() => video.requestFrame(), 500);
  let voice = null, mic = null;
  function microphone() {
    if (!voice) {
      voice = new AudioContext();
      mic = voice.createMediaStreamDestination();
    }
    return mic;
  }
  window.__meetingCard = {
    show(update) {
      Object.assign(card, update);
      if ('image' in update) picture_of(update.image);
      draw();
    },
    async speak(audio) {
      const out = microphone();
      await voice.resume();
      const bytes = Uint8Array.from(atob(audio), (c) => c.charCodeAt(0));
      const sound = await voice.decodeAudioData(bytes.buffer);
      const source = voice.createBufferSource();
      source.buffer = sound;
      source.connect(out);
      source.start();
      return sound.duration;
    },
    picture() { return canvas.toDataURL(); },
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
})()"""


def script(start: Start) -> str:
    """The card's page script, for the agent as it joins: everything but
    its picture (a data URL of megabytes, in a script Meet runs in every
    page it opens, kept Meet from loading), handed over once it has
    loaded."""
    card = start.model_dump(exclude={"image"}) | {
        "initials": initials(start.name),
        "status": LISTENING,
    }
    return CARD.replace("__START__", json.dumps(card))


async def show(page: Page, **update: str | bool | None) -> None:
    """Redraw the card with ``update`` (its status, image or name); a page
    opened without the card (``script``) has none to redraw."""
    await page.evaluate("(update) => window.__meetingCard?.show(update)", update)


async def speak(page: Page, audio: bytes) -> float:
    """Play ``audio`` (any format the browser decodes: TTS's MP3 or WAV) into the
    microphone; how many seconds it lasts."""
    encoded = base64.b64encode(audio).decode()
    return await page.evaluate("(audio) => window.__meetingCard.speak(audio)", encoded)
