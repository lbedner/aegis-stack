// A card's parts named in Illiana's words (mentions.js): which words name
// which part, found in a sentence. Run: node --test tests/js.
const test = require('node:test');
const assert = require('node:assert/strict');
const { partsOf, namesIn, lastNamed, namedAt } = require('../../app/components/web_frontend/static/js/mentions.js');

// The parts a card draws, as its map keys and titles.
const PARTS = partsOf([
  { key: 'backend', title: 'Server' },
  { key: 'service_auth', title: 'Authentication' },
  { key: 'outside:Stripe', title: 'Stripe' },
  { key: 'service_ai', title: 'AI' },
]);
const keys = (text) => namesIn(text, PARTS).map((found) => found.key);

test('a part is named by its title or its own name, any case', () => {
  assert.deepEqual(keys('The server hands it to auth, then Authentication calls stripe.'), [
    'backend',
    'service_auth',
    'service_auth',
    'outside:Stripe',
  ]);
  assert.deepEqual(keys('the Backend'), ['backend']);
});

test('only whole words name a part', () => {
  assert.deepEqual(keys('She said it was authorised, and the AI agreed.'), ['service_ai']);
});

test('a match says where it is, so it can be marked in place', () => {
  const [found] = namesIn('Ask the Server.', PARTS);
  assert.deepEqual(found, { start: 8, end: 14, key: 'backend' });
});

test('a part the card does not draw is never named', () => {
  assert.deepEqual(keys('The worker and the queue.'), []);
  assert.deepEqual(namesIn('Anything at all', partsOf([])), []);
});

test('following speech lights the part named last', () => {
  assert.equal(lastNamed('First the Server, then auth', PARTS), 'service_auth');
  assert.equal(lastNamed('Nothing on the card', PARTS), null);
});

test('an answer heard again lights the part named as far as the audio is', () => {
  const said = 'First the Server, then auth';
  assert.equal(namedAt(said, 0, PARTS), null);
  assert.equal(namedAt(said, 0.6, PARTS), 'backend');
  assert.equal(namedAt(said, 1, PARTS), 'service_auth');
});
