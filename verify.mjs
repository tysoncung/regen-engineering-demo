#!/usr/bin/env node
// Runs the same contract suite against every implementation, in turn.
//
//   node verify.mjs             both stacks
//   node verify.mjs typescript  just one
//
// The point of this script is that it contains no per-stack logic beyond how to
// start a process. The contracts, the runner, and the assertions are identical
// for every stack, because they speak only to the interface the knowledge
// describes.

import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = dirname(fileURLToPath(import.meta.url))

const STACKS = {
  typescript: { cmd: 'node', args: ['impl/typescript/server.mjs'] },
  python: { cmd: 'python3', args: ['impl/python/server.py'] },
}

const wanted = process.argv.slice(2).filter((a) => !a.startsWith('-'))
const selected = wanted.length ? wanted : Object.keys(STACKS)

/** Ask the OS for a free port, so a busy 8080 cannot masquerade as a failure. */
const freePort = () =>
  new Promise((resolve, reject) => {
    const srv = createServer()
    srv.on('error', reject)
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address()
      srv.close(() => resolve(port))
    })
  })

const run = (cmd, args, opts = {}) =>
  new Promise((resolve) => {
    const child = spawn(cmd, args, { cwd: ROOT, stdio: 'inherit', ...opts })
    child.on('exit', (code) => resolve(code ?? 1))
  })

const results = []

for (const name of selected) {
  const stack = STACKS[name]
  if (!stack) {
    console.error(`Unknown stack "${name}". Known: ${Object.keys(STACKS).join(', ')}`)
    process.exit(2)
  }

  const port = await freePort()
  const base = `http://127.0.0.1:${port}`

  console.log(`\n${'='.repeat(60)}`)
  console.log(`${name}  ${base}`)
  console.log('='.repeat(60))

  const server = spawn(stack.cmd, stack.args, {
    cwd: ROOT,
    env: { ...process.env, PORT: String(port) },
    stdio: ['ignore', 'ignore', 'inherit'],
  })

  let code
  try {
    code = await run('node', ['contracts/run.mjs', '--base', base])
  } finally {
    server.kill()
  }
  results.push({ name, ok: code === 0 })
}

console.log(`\n${'='.repeat(60)}`)
for (const r of results) console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}`)

const allPassed = results.every((r) => r.ok)
if (allPassed && results.length > 1) {
  console.log('\nSame knowledge. Same contracts. Different stacks. All green.')
}
process.exit(allPassed ? 0 : 1)
