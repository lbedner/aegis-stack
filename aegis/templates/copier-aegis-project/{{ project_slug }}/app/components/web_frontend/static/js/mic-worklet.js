/* A live call's microphone. An AudioWorklet runs on the audio
   thread and must be its own module: it hands each block of the mic, at the
   capture context's rate (the model's input rate), to voice.js, which
   batches it into PCM16 frames for the relay's WebSocket. */
class MicPcm extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel) this.port.postMessage(channel.slice(0));
    return true;
  }
}
registerProcessor('mic-pcm', MicPcm);
