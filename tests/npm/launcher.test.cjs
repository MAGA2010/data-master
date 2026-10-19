'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const { findPython, main, setup, managedPaths } = require('../../bin/data-master.cjs');

test('Python discovery rejects old versions and honors executable paths containing spaces', () => {
  const calls = [];
  const python = findPython({ DATA_MASTER_PYTHON: '/a path/python' }, (cmd, args) => {
    calls.push([cmd, args]);
    return { status: 0, stdout: JSON.stringify({ path: cmd, version: [3, 13] }) };
  });
  assert.equal(python, '/a path/python');
  assert.equal(calls.length, 1);
  assert.equal(findPython({ DATA_MASTER_PYTHON: '/old/python' }, () => ({
    status: 0, stdout: JSON.stringify({ path: '/old/python', version: [3, 10] }) })), null);
});

test('version and help work without Python or dependency installation', () => {
  const forbidden = () => { throw Error('must not spawn'); };
  assert.equal(main(['--version'], {}, forbidden), 0);
  assert.equal(main(['--help'], {}, forbidden), 0);
});

test('analysis forwards literal arguments without a shell', () => {
  let forwarded;
  const run = (cmd, args, options) => {
    if (args.includes('import json,sys; print(json.dumps({"path":sys.executable,"version":list(sys.version_info[:2])}))')) {
      return { status: 0, stdout: JSON.stringify({ path: cmd, version: [3, 13] }) };
    }
    forwarded = { cmd, args, options };
    return { status: 7 };
  };
  const file = 'data folder/$(literal);file.csv';
  assert.equal(main(['analyze', file, '--out', 'report folder'], { DATA_MASTER_PYTHON: 'custom python' }, run), 7);
  assert.equal(forwarded.cmd, 'custom python');
  assert.deepEqual(forwarded.args.slice(-4), ['analyze', file, '--out', 'report folder']);
  assert.equal(forwarded.options.shell, undefined);
});

test('missing Python fails clearly without trying pip', () => {
  assert.equal(main(['doctor'], { DATA_MASTER_PYTHON: '/missing' }, () => ({ status: 1 })), 2);
});

test('setup creates a venv, propagates pip failure, releases lock, and retries', () => {
  const cache = fs.mkdtempSync(path.join(os.tmpdir(), 'dm-setup-'));
  const env = { ...process.env, DATA_MASTER_CACHE: cache, DATA_MASTER_PYTHON: 'test python' };
  const calls = [];
  const run = (cmd, args) => {
    calls.push(args);
    if (args[0] === '-c') return { status: 0, stdout: JSON.stringify({ path: cmd, version: [3, 13] }) };
    return { status: args.includes('pip') ? 9 : 0 };
  };
  try {
    assert.equal(setup([], env, run), 9);
    assert.ok(calls.some(args => args[1] === 'venv'));
    assert.ok(calls.some(args => args[1] === 'pip' && args.includes('-r')));
    assert.ok(!fs.existsSync(managedPaths(env).directory + '.lock'));
    assert.equal(setup([], env, (cmd, args) => args[0] === '-c'
      ? { status: 0, stdout: JSON.stringify({ path: cmd, version: [3, 13] }) }
      : { status: 0 }), 0);
  } finally { fs.rmSync(cache, { recursive: true, force: true }); }
});

test('packed npm install runs outside checkout and preserves demo evidence', { timeout: 240000 }, () => {
  const root = path.resolve(__dirname, '../..');
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'dm-npm-'));
  const npm = process.env.npm_execpath;
  assert.ok(npm, 'Run this suite with npm test so npm_execpath is available');
  const python = findPython();
  assert.ok(python, 'Python 3.11+ with project dependencies required for integration test');
  const env = { ...process.env, DATA_MASTER_PYTHON: python, DATA_MASTER_CACHE: path.join(temp, 'cache'), PYTHONUTF8: '1' };
  function invoke(args, expected = 0) {
    const result = spawnSync(process.execPath, [npm, ...args], {
      cwd: temp, env, encoding: 'utf8', timeout: 180000, windowsHide: true });
    assert.equal(result.status, expected, result.stdout + result.stderr);
    return result.stdout;
  }
  try {
    const pack = JSON.parse(invoke(['pack', root, '--pack-destination', temp, '--json']))[0];
    const names = pack.files.map(f => f.path);
    for (const needed of ['bin/data-master.cjs', 'data_master/cli.py', 'scripts/run_pipeline.py',
      'references/journal-reporting-standards.json', 'examples/independent_groups/measurements.csv']) {
      assert.ok(names.includes(needed), needed);
    }
    assert.ok(!names.some(n => n.includes('/outputs/') || n.startsWith('.git/') || n.startsWith('node_modules/')));
    const metadata = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
    for (const hook of ['install', 'postinstall', 'preinstall', 'prepare']) assert.equal(metadata.scripts[hook], undefined);
    invoke(['install', '--prefix', temp, '--ignore-scripts', '--no-audit', '--no-fund', path.join(temp, pack.filename)]);
    const exec = (...args) => invoke(['exec', '--prefix', temp, '--offline', '--', 'data-master', ...args]);
    assert.match(exec('--version'), /0\.2\.0/);
    assert.equal(JSON.parse(exec('doctor', '--json')).healthy, true);
    const out = path.join(temp, 'report with spaces');
    exec('demo', '--out', out);
    assert.equal(JSON.parse(exec('verify', out, '--json')).valid, true);
    exec('resume', path.join(out, 'state.json'));
    assert.equal(JSON.parse(exec('verify', out, '--json')).valid, true);
    assert.equal(fs.existsSync(env.DATA_MASTER_CACHE), false, 'ordinary commands must not install dependencies');
  } finally { fs.rmSync(temp, { recursive: true, force: true }); }
});
