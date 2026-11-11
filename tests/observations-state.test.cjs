const test = require('node:test');
const assert = require('node:assert/strict');
const {unread, createReader} = require('../static/js/observations.js');

test('first visit, read marker and new message', () => {
  assert.deepEqual(unread(['a', 'b'], null), {count: 2, uncertain: false});
  assert.equal(unread(['a', 'b'], 'b').count, 0);
  assert.equal(unread(['a', 'b', 'c'], 'b').count, 1);
  assert.equal(unread([], 'b').count, 0);
});
test('removed marker does not classify old messages as new', () => {
  assert.deepEqual(unread(['old', 'new'], 'removed'), {count: null, uncertain: true});
});
test('storage contains only last id, segregates users and tickets, persists', () => {
  const data = new Map();
  const storage = {getItem: k => data.get(k) ?? null, setItem: (k, v) => data.set(k, v)};
  const first = createReader('user1', () => storage);
  assert.equal(first.get('ticket'), null);
  first.mark('ticket', 'm2');
  assert.equal(createReader('user1', () => storage).get('ticket'), 'm2');
  assert.equal(createReader('user2', () => storage).get('ticket'), null);
  assert.equal(first.get('other'), null);
  assert.deepEqual([...data.values()], ['m2']);
});
test('blocked storage falls back to memory and reports nonpersistent state', () => {
  const reader = createReader('user', () => {throw new Error('SecurityError');});
  reader.mark('ticket', 'last');
  assert.equal(reader.get('ticket'), 'last');
  assert.equal(reader.persistent(), false);
});
test('readable storage with failed writes uses the newer memory marker', () => {
  const reader = createReader('user', () => ({getItem: () => 'old', setItem() {throw new Error('QuotaExceededError');}}));
  assert.equal(reader.get('ticket'), 'old');
  reader.mark('ticket', 'new');
  assert.equal(reader.get('ticket'), 'new');
  assert.equal(reader.persistent(), false);
});
