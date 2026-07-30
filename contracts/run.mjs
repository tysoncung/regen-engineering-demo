#!/usr/bin/env node
// The contract runner.
//
// Contracts are knowledge: prose in given/when/then form, living in the
// knowledge tree. This file is the thin adapter that executes them against a
// running implementation over HTTP.
//
// It knows nothing about TypeScript or Python. It only speaks to the interface
// the knowledge describes, which is what lets one suite verify every stack.
//
//   node contracts/run.mjs --base http://localhost:8080
//   node contracts/run.mjs --base http://localhost:8080 --only CT-002

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, dirname, basename } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const argv = process.argv.slice(2)
const opt = (n, d) => {
  const i = argv.indexOf(n)
  return i === -1 ? d : argv[i + 1]
}
const BASE = opt('--base', process.env.REGEN_BASE_URL ?? 'http://localhost:8080')
const ONLY = opt('--only', null)

// ---------------------------------------------------------------- parsing

function findContracts(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === '.git') continue
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) findContracts(full, out)
    else if (basename(dirname(full)) === 'contracts' && entry.endsWith('.md')) out.push(full)
  }
  return out
}

/** A contract file is frontmatter plus `## Scenario:` blocks of steps. */
function parseContract(file) {
  const text = readFileSync(file, 'utf8')
  const end = text.indexOf('\n---', 3)
  const fm = text.slice(3, end)
  const id = /id:\s*(\S+)/.exec(fm)?.[1]
  const title = /title:\s*(.+)/.exec(fm)?.[1]?.trim()

  const scenarios = []
  let current = null
  for (const line of text.slice(end + 4).split('\n')) {
    const heading = /^##\s+Scenario:\s*(.+)$/.exec(line.trim())
    if (heading) {
      current = { name: heading[1].trim(), steps: [] }
      scenarios.push(current)
      continue
    }
    const step = /^(Given|When|Then|And)\s+(.+)$/.exec(line.trim())
    if (step && current) current.steps.push({ keyword: step[1], text: step[2].trim() })
  }
  return { id, title, file, scenarios }
}

// ---------------------------------------------------------------- http

async function call(method, path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'content-type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  let data = null
  const text = await res.text()
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }
  return { status: res.status, data }
}

// ---------------------------------------------------------------- steps
// Each step maps prose to interface calls. Nothing here references an internal
// class or function, which is what lets a contract survive regeneration into a
// different language.

const quoted = (s) => [...s.matchAll(/"([^"]*)"/g)].map((m) => m[1])

const steps = [
  // --- given / setup ---
  [
    /^a customer registered with "(.*)"$/,
    async (ctx, [email]) => {
      const r = await call('POST', '/customers', { email })
      ctx.lastStatus = r.status
      ctx.lastBody = r.data
      if (r.status === 201) ctx.customerId = r.data.id
      ctx.email = email
    },
  ],
  [
    /^the customer's account is deleted$/,
    async (ctx) => {
      const r = await call('POST', `/customers/${ctx.customerId}/delete`)
      if (r.status !== 204) throw new Error(`expected 204 deleting customer, got ${r.status}`)
    },
  ],
  [
    /^the customer has addresses (.+)$/,
    async (ctx, _m, raw) => {
      for (const line of quoted(raw)) {
        const r = await call('POST', `/customers/${ctx.customerId}/addresses`, { line })
        if (r.status !== 201) throw new Error(`expected 201 adding address, got ${r.status}`)
      }
    },
  ],
  [
    /^the customer used address "(.*)"$/,
    async (ctx, [line]) => {
      const id = await addressIdFor(ctx, line)
      const r = await call('POST', '/orders', { customerId: ctx.customerId, addressId: id })
      if (r.status !== 201) throw new Error(`expected 201 placing order to mark address used, got ${r.status}`)
      ctx.orderId = r.data.id
    },
  ],

  // --- when / actions ---
  [
    /^someone registers with "(.*)"$/,
    async (ctx, [email]) => {
      const r = await call('POST', '/customers', { email })
      ctx.lastStatus = r.status
      ctx.lastBody = r.data
    },
  ],
  [
    /^the customer adds address "(.*)"$/,
    async (ctx, [line]) => {
      const r = await call('POST', `/customers/${ctx.customerId}/addresses`, { line })
      ctx.lastStatus = r.status
      ctx.lastBody = r.data
    },
  ],
  [
    /^the customer deletes address "(.*)"$/,
    async (ctx, [line]) => {
      const id = await addressIdFor(ctx, line)
      const r = await call('DELETE', `/customers/${ctx.customerId}/addresses/${id}`)
      ctx.lastStatus = r.status
      if (r.status !== 204) throw new Error(`expected 204 deleting address, got ${r.status}`)
    },
  ],
  [
    /^the customer edits address "(.*)" to "(.*)"$/,
    async (ctx, [from, to]) => {
      const id = await addressIdFor(ctx, from)
      const r = await call('PATCH', `/customers/${ctx.customerId}/addresses/${id}`, { line: to })
      if (r.status !== 200) throw new Error(`expected 200 editing address, got ${r.status}`)
    },
  ],
  [
    /^the customer authenticates with "(.*)"$/,
    async (ctx, [email]) => {
      const r = await call('POST', '/auth', { email })
      ctx.lastStatus = r.status
      ctx.lastBody = r.data
    },
  ],
  [
    /^the customer places an order$/,
    async (ctx) => {
      const r = await call('POST', '/orders', { customerId: ctx.customerId })
      ctx.lastStatus = r.status
      ctx.lastBody = r.data
      if (r.status === 201) ctx.orderId = r.data.id
    },
  ],

  // --- then / assertions ---
  [
    /^registration succeeds$/,
    (ctx) => expect(ctx.lastStatus === 201, `expected 201, got ${ctx.lastStatus}`),
  ],
  [
    /^registration is rejected$/,
    (ctx) => expect(ctx.lastStatus === 409, `expected 409, got ${ctx.lastStatus}`),
  ],
  [
    /^the response does not disclose that an account exists$/,
    (ctx) => {
      const body = JSON.stringify(ctx.lastBody ?? '').toLowerCase()
      const leaks = ['already', 'exists', 'registered', 'taken', 'duplicate'].filter((w) => body.includes(w))
      expect(leaks.length === 0, `response leaks account existence via ${leaks.join(', ')}: ${body}`)
    },
  ],
  [
    /^the default address is "(.*)"$/,
    async (ctx, [line]) => {
      const list = await addresses(ctx)
      const def = list.find((a) => a.isDefault)
      expect(def, 'expected a default address, found none')
      expect(def.line === line, `expected default "${line}", got "${def.line}"`)
      expect(
        list.filter((a) => a.isDefault).length === 1,
        `expected exactly one default, found ${list.filter((a) => a.isDefault).length}`,
      )
    },
  ],
  [
    /^the customer has no default address$/,
    async (ctx) => {
      const list = await addresses(ctx)
      expect(!list.some((a) => a.isDefault), 'expected no default address, found one')
    },
  ],
  [
    /^the customer has (\d+) address(?:es)?$/,
    async (ctx, [n]) => {
      const list = await addresses(ctx)
      expect(list.length === Number(n), `expected ${n} addresses, got ${list.length}`)
    },
  ],
  [
    /^authentication succeeds$/,
    (ctx) => expect(ctx.lastStatus === 200, `expected 200, got ${ctx.lastStatus}`),
  ],
  [
    /^authentication fails$/,
    (ctx) => expect(ctx.lastStatus === 401, `expected 401, got ${ctx.lastStatus}`),
  ],
  [
    /^the order is rejected$/,
    (ctx) => expect(ctx.lastStatus === 400, `expected 400, got ${ctx.lastStatus}`),
  ],
  [
    /^the order shipping address is "(.*)"$/,
    async (ctx, [line]) => {
      const r = await call('GET', `/orders/${ctx.orderId}`)
      expect(r.status === 200, `expected 200 fetching order, got ${r.status}`)
      const got = r.data?.shippingAddress?.line
      expect(got === line, `expected shipping address "${line}", got "${got}"`)
    },
  ],
]

function expect(cond, msg) {
  if (!cond) throw new Error(msg)
}

async function addresses(ctx) {
  const r = await call('GET', `/customers/${ctx.customerId}/addresses`)
  expect(r.status === 200, `expected 200 listing addresses, got ${r.status}`)
  return r.data
}

async function addressIdFor(ctx, line) {
  const found = (await addresses(ctx)).find((a) => a.line === line)
  expect(found, `no address "${line}" in the customer's address book`)
  return found.id
}

// ---------------------------------------------------------------- execution

async function runStep(ctx, step) {
  for (const [pattern, fn] of steps) {
    const m = pattern.exec(step.text)
    if (m) return fn(ctx, m.slice(1), step.text)
  }
  throw new Error(`no step definition matches: ${step.keyword} ${step.text}`)
}

const contracts = findContracts(ROOT)
  .map(parseContract)
  .filter((c) => c.id && (!ONLY || c.id === ONLY))
  .sort((a, b) => a.id.localeCompare(b.id))

if (!contracts.length) {
  console.error('No contracts found.')
  process.exit(2)
}

// Wait for the implementation to accept connections before starting.
for (let i = 0; ; i++) {
  try {
    await fetch(`${BASE}/health`)
    break
  } catch (e) {
    if (i > 50) {
      console.error(`Nothing listening at ${BASE}. Start an implementation first.`)
      process.exit(2)
    }
    await new Promise((r) => setTimeout(r, 100))
  }
}

let passed = 0
const failures = []

console.log(`Contracts against ${BASE}\n`)

for (const contract of contracts) {
  const results = []
  for (const scenario of contract.scenarios) {
    // Each scenario starts from a clean slate so ordering can never hide a bug.
    await call('POST', '/reset')
    const ctx = {}
    try {
      for (const step of scenario.steps) await runStep(ctx, step)
      results.push({ scenario, ok: true })
      passed++
    } catch (e) {
      results.push({ scenario, ok: false, error: e.message })
      failures.push({ contract, scenario, error: e.message })
    }
  }
  const bad = results.filter((r) => !r.ok).length
  const mark = bad === 0 ? 'PASS' : 'FAIL'
  console.log(`${mark}  ${contract.id}  ${contract.title}  (${results.length - bad}/${results.length})`)
  for (const r of results.filter((r) => !r.ok)) console.log(`        ${r.scenario.name}: ${r.error}`)
}

const total = passed + failures.length
console.log(`\n${passed}/${total} scenarios passed across ${contracts.length} contracts`)
process.exit(failures.length ? 1 : 0)
