// Trusted evaluator code stays outside the candidate workspace. This is not an OS sandbox.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('typescript');
const root = path.resolve(process.argv[2]);
const task = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const cache = new Map();
let tests = 0;
function load(relative) {
  let file = path.resolve(root, relative);
  if (!file.startsWith(root + path.sep)) throw new Error('Evaluator import escaped workspace');
  if (!path.extname(file)) file += '.ts';
  if (cache.has(file)) return cache.get(file).exports;
  const module = {exports: {}};
  cache.set(file, module);
  const source = fs.readFileSync(file, 'utf8');
  const output = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, esModuleInterop: true}}).outputText;
  function localRequire(name) {
    if (name === 'node:assert/strict') return assert;
    if (name === 'vitest') return {test: (_, fn) => {fn(); tests++;}, it: (_, fn) => {fn(); tests++;}};
    if (!name.startsWith('.')) throw new Error('Unexpected dependency in pure contract: ' + name);
    return load(path.relative(root, path.resolve(path.dirname(file), name)));
  }
  const fn = vm.runInThisContext('(function(require,module,exports){' + output + '\n})', {filename: file});
  fn(localRequire, module, module.exports);
  return module.exports;
}
function read(relative) {
  const file = path.resolve(root, relative);
  if (!file.startsWith(root + path.sep)) throw new Error('Evaluator read escaped workspace');
  return fs.readFileSync(file, 'utf8');
}
try {
  new Function('load', 'assert', 'read', task.acceptance_js)(load, assert, read);
  if (task.category === 'Add Test' && tests === 0) throw new Error('Candidate test did not execute any test body');
  console.log(JSON.stringify({task_id: task.task_id, passed: true, assertions: task.assertion_summary, candidate_tests_executed: tests}));
} catch (error) {
  console.error(JSON.stringify({task_id: task.task_id, passed: false, error: String(error.message).slice(0, 2000)}));
  process.exitCode = 1;
}
