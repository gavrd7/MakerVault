import test from 'node:test';
import assert from 'node:assert/strict';
import { printerIntent, consumePrinterIntent } from '../src/components/printerNavigation.js';
const printers = [{ id: 'k1' }, { id: 'k2' }];

test('live action is consumed so returning to the page cannot reopen K1', () => {
  let target = { type: 'printers', id: 'k1', openLive: true, token: 1 };
  assert.equal(printerIntent(target, printers, null).printer.id, 'k1');
  target = consumePrinterIntent(target, 1);
  assert.equal(printerIntent(target, printers, null), null);
});

test('camera action selects the requested printer independently of live monitoring', () => {
  const target = { type: 'printers', id: 'k2', openCamera: true, token: 2 };
  assert.deepEqual(printerIntent(target, printers, null), { printer: printers[1], camera: true, token: 2 });
  assert.equal(printerIntent(target, printers, 2), null);
  assert.equal(printerIntent({ type: 'printers', id: 'k1', token: 3 }, printers, null), null);
});

test('pending data and a newer navigation request are not discarded', () => {
  const target = { type: 'printers', id: 'k2', openCamera: true, token: 4 };
  assert.equal(printerIntent(target, [], null), null);
  assert.equal(consumePrinterIntent(target, 3), target);
  assert.ok(printerIntent(target, printers, null));
});
