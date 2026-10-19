#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const metadata = require('../package.json');

function managedPaths(env = process.env) {
  const base = env.DATA_MASTER_CACHE || (process.platform === 'win32'
    ? path.join(env.LOCALAPPDATA || os.homedir(), 'data-master')
    : path.join(env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache'), 'data-master'));
  const hash = crypto.createHash('sha256').update(fs.readFileSync(path.join(root, 'requirements.txt')))
    .digest('hex').slice(0, 12);
  const directory = path.resolve(base, `python-${metadata.version}-${hash}`);
  return { directory, python: path.join(directory,
    process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python') };
}

function findPython(env = process.env, run = spawnSync) {
  const candidates = env.DATA_MASTER_PYTHON ? [[env.DATA_MASTER_PYTHON]]
    : process.platform === 'win32' ? [['py', '-3'], ['python'], ['python3']]
      : [['python3'], ['python']];
  for (const [command, ...prefix] of candidates) {
    const result = run(command, [...prefix, '-c',
      'import json,sys; print(json.dumps({"path":sys.executable,"version":list(sys.version_info[:2])}))'],
    { encoding: 'utf8', env, windowsHide: true, timeout: 15000 });
    if (result.error || result.status !== 0) continue;
    try {
      const probe = JSON.parse(result.stdout);
      if (probe.version[0] === 3 && probe.version[1] >= 11) return probe.path;
    } catch { /* Not a working Python interpreter. Try the next candidate. */ }
  }
  return null;
}

function child(command, args, options = {}, run = spawnSync) {
  const result = run(command, args, { stdio: 'inherit', windowsHide: true,
    env: { ...process.env, PYTHONUTF8: '1' }, ...options });
  if (result.error) throw result.error;
  return result.status ?? (result.signal === 'SIGINT' ? 130 : 1);
}

function skillTarget(args, env = process.env) {
  let target = path.join(env.CODEX_HOME || path.join(os.homedir(), '.codex'), 'skills', 'data-master');
  for (let i = 0; i < args.length; i += 1) {
    if (args[i] === '--target' && args[i + 1]) {
      target = args[++i];
    } else {
      throw new Error('Usage: data-master skill install [--target DIR]');
    }
  }
  return path.resolve(target);
}

function installSkill(args, env = process.env) {
  if (args[0] !== 'install') {
    console.error('Usage: data-master skill install [--target DIR]');
    return 2;
  }
  let target;
  try { target = skillTarget(args.slice(1), env); } catch (error) {
    console.error(error.message);
    return 2;
  }
  if (fs.existsSync(target)) {
    console.error('Skill destination already exists: ' + target + '\nRemove it or choose --target DIR. Existing files were not changed.');
    return 2;
  }
  const manifest = JSON.parse(fs.readFileSync(path.join(root, 'skill-package.json'), 'utf8'));
  const parent = path.dirname(target);
  const staging = path.join(parent, `.data-master-install-${process.pid}-${Date.now()}`);
  const filter = source => !['__pycache__', '.git', 'outputs'].includes(path.basename(source))
    && !source.endsWith('.pyc');
  fs.mkdirSync(parent, { recursive: true });
  try {
    fs.mkdirSync(staging);
    for (const relative of manifest.include) {
      const source = path.join(root, relative);
      if (!fs.existsSync(source)) throw new Error('Packaged skill resource is missing: ' + relative);
      const destination = path.join(staging, relative);
      fs.mkdirSync(path.dirname(destination), { recursive: true });
      fs.cpSync(source, destination, { recursive: true, filter });
    }
    fs.renameSync(staging, target);
    console.log('Installed data-master skill: ' + target);
    console.log('Restart Codex, then ask it to analyze a dataset with data-master.');
    return 0;
  } catch (error) {
    fs.rmSync(staging, { recursive: true, force: true });
    console.error('Skill installation failed: ' + error.message);
    return 2;
  }
}

function setup(args, env = process.env, run = spawnSync) {
  if (args.length) {
    console.error('Usage: data-master setup (set DATA_MASTER_PYTHON to select Python)');
    return 2;
  }
  const python = findPython(env, run);
  if (!python) {
    console.error('Python 3.11+ is required. Install Python or set DATA_MASTER_PYTHON to its executable.');
    return 2;
  }
  const managed = managedPaths(env);
  fs.mkdirSync(path.dirname(managed.directory), { recursive: true });
  const lock = managed.directory + '.lock';
  try { fs.mkdirSync(lock); } catch (error) {
    if (error.code !== 'EEXIST') throw error;
    console.error('Setup is already running, or a previous setup left a lock: ' + lock);
    return 2;
  }
  const options = { env: { ...env, PYTHONUTF8: '1' } };
  try {
    console.log('Creating isolated Python environment: ' + managed.directory);
    let code = child(python, ['-m', 'venv', managed.directory], options, run);
    if (code) return code;
    console.log('Installing the declared Python dependencies (network access may be needed).');
    code = child(managed.python, ['-m', 'pip', 'install', '-r', path.join(root, 'requirements.txt')], options, run);
    if (code) return code;
    console.log('Setup complete. Run data-master doctor, then data-master demo --out outputs/demo.');
    return 0;
  } finally { fs.rmdirSync(lock); }
}

function main(args = process.argv.slice(2), env = process.env, run = spawnSync) {
  if (args[0] === '--version') {
    console.log('data-master ' + metadata.version);
    return 0;
  }
  if (!args.length || ['--help', '-h'].includes(args[0])) {
    console.log(`data-master ${metadata.version}
Usage: data-master <setup|skill|doctor|demo|analyze|resume|verify> [arguments]
  setup             Create an isolated Python environment and install dependencies
  skill install     Install the bundled Codex skill (supports --target DIR)
  doctor --json     Check runtime resources and Python dependencies
  demo --out DIR    Analyze the bundled synthetic dataset
  analyze FILE      Analyze a dataset; use analyze --help for pipeline options
  resume STATE      Resume a saved run
  verify DIR        Verify the saved evidence (supports --json)
Requires Python 3.11+. npm installation does not install Python dependencies.
DATA_MASTER_PYTHON selects an interpreter; DATA_MASTER_CACHE selects the setup cache.`);
    return 0;
  }
  try {
    if (args[0] === 'setup') return setup(args.slice(1), env, run);
    if (args[0] === 'skill') return installSkill(args.slice(1), env);
    const managed = managedPaths(env);
    const python = env.DATA_MASTER_PYTHON ? findPython(env, run)
      : fs.existsSync(managed.python) ? managed.python : findPython(env, run);
    if (!python) {
      console.error('Python 3.11+ was not found. Install Python or set DATA_MASTER_PYTHON.');
      return 2;
    }
    const bootstrap = 'import sys; sys.path.insert(0,sys.argv.pop(1)); from data_master.cli import main; sys.exit(main())';
    return child(python, ['-c', bootstrap, root, ...args],
      { env: { ...env, PYTHONUTF8: '1' } }, run);
  } catch (error) {
    console.error('data-master: ' + error.message + '\nRun data-master setup or select DATA_MASTER_PYTHON.');
    return 2;
  }
}

module.exports = { main, findPython, managedPaths, setup, installSkill, skillTarget };
if (require.main === module) process.exitCode = main();
