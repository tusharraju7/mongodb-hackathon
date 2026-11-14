import test from 'node:test';
import assert from 'node:assert/strict';
import {authenticateDemo} from '../src/demo-auth';

test('each demo account authenticates only in its assigned workspace',()=>{
  assert.deepEqual(authenticateDemo('demo.user','ReviewDemo!26','user'),{username:'demo.user',role:'user'});
  assert.deepEqual(authenticateDemo('demo.lawyer','LegalDemo!26','lawyer'),{username:'demo.lawyer',role:'lawyer'});
  assert.throws(()=>authenticateDemo('demo.user','ReviewDemo!26','lawyer'),/User workspace/);
  assert.throws(()=>authenticateDemo('demo.lawyer','LegalDemo!26','user'),/Lawyer workspace/);
});
test('incorrect, empty and case-changed passwords cannot enter',()=>{
  for(const password of ['', 'wrong', 'reviewdemo!26'])assert.throws(()=>authenticateDemo('demo.user',password,'user'),/Incorrect/);
  assert.throws(()=>authenticateDemo('unknown','ReviewDemo!26','user'),/Incorrect/);
  assert.equal(authenticateDemo(' DEMO.USER ','ReviewDemo!26','user').role,'user');
});
test('authenticated demo identity contains no password and is immutable',()=>{
  const identity=authenticateDemo('demo.user','ReviewDemo!26','user');
  assert.equal('password' in identity,false);
  assert.ok(Object.isFrozen(identity));
});
