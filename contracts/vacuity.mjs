#!/usr/bin/env node
// Vacuity check: does each contract actually assert anything?
//
// Traceability counts contracts that exist. It cannot tell whether a contract
// would fail if the rule it claims to verify were violated. Running the change
// loop on this repository produced exactly that failure: three of five new
// scenarios passed against an implementation that ignored the new rule
// entirely, while validation reported no problems and the debt report counted
// the rule as fully verified.
//
// The check is blunt and effective. Run the suite against a deliberately wrong
// implementation. Every scenario should fail. Any scenario that passes against
// an implementation that does nothing correct is asserting nothing, and the
// rule it claims to verify is unverified no matter what the metric says.
//
//   node contracts/vacuity.mjs
//
// This is the automated form of the advice in the `verify` skill: break it once
// and confirm a contract goes red. A contract nobody has seen fail is a
// contract nobody has tested.

import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = dirname(fileURLToPath(import.meta.url))
const REPO = join(ROOT, '..')

const freePort = () =>
  new Promise((resolve, reject) => {
    const s = createServer()
    s.on('error', reject)
    s.listen(0, '127.0.0.1', () => {
      const { port } = s.address()
      s.close(() => resolve(port))
    })
  })

const port = await freePort()
const base = `http://127.0.0.1:${port}`

// The straw implementation. It answers every request in a way that is
// syntactically plausible and semantically wrong: correct-looking JSON, wrong
// status codes, no state, no rules. Nothing here should satisfy any contract.
const straw = `
import { createServer } from 'node:http'
createServer((req, res) => {
  let body = ''
  req.on('data', (c) => (body += c))
  req.on('end', () => {
    const url = new URL(req.url, 'http://x')
    if (url.pathname === '/health') return void res.writeHead(200).end('{"ok":true}')
    if (url.pathname === '/reset') return void res.writeHead(204).end()
    // Everything else: a 200 with an empty object. Plausible shape, no behaviour.
    res.writeHead(200, { 'content-type': 'application/json' })
    res.end('{}')
  })
}).listen(${port}, '127.0.0.1')
`

const server = spawn('node', ['--input-type=module', '-e', straw], { stdio: ['pipe', 'ignore', 'inherit'] })
await new Promise((r) => setTimeout(r, 400))

const run = spawn('node', [join(ROOT, 'run.mjs'), '--base', base], { cwd: REPO, encoding: 'utf8' })
let out = ''
run.stdout.on('data', (d) => (out += d))
run.stderr.on('data', (d) => (out += d))
const code = await new Promise((r) => run.on('exit', r))
server.kill()

// Any scenario that survived the straw implementation is asserting nothing.
const survivors = []
for (const line of out.split('\n')) {
  const m = /^(PASS|FAIL)\s+(CT-\d+)\s+(.*?)\s+\((\d+)\/(\d+)\)/.exec(line.trim())
  if (m && Number(m[4]) > 0) survivors.push({ id: m[2], title: m[3], passed: Number(m[4]), total: Number(m[5]) })
}

console.log('Vacuity check: running the contract suite against a straw implementation.')
console.log('Every scenario should FAIL. Anything that passes asserts nothing.\n')

if (!survivors.length) {
  const total = /(\d+)\/(\d+) scenarios passed/.exec(out)
  console.log(`No scenario survived. ${total ? total[2] : 'All'} scenarios assert something real.`)
  process.exit(0)
}

console.log('VACUOUS SCENARIOS FOUND:\n')
for (const s of survivors) console.log(`  ${s.id}  ${s.passed} of ${s.total} scenarios passed against nothing  (${s.title})`)
console.log('\nThese contracts do not verify the rules they claim to. Traceability will')
console.log('still report them as verified, which is exactly why this check exists.')
console.log('Strengthen the assertions, or the rule is unverified.')
process.exit(1)
