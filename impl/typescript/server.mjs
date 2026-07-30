// Generated from the knowledge tree. See customer/knowledge and orders/knowledge.
//
// No framework and no dependencies, so the demo runs anywhere Node does.
// Storage is in memory: persistence would add plumbing without adding anything
// to the argument this repository is making.

import { createServer } from 'node:http'

const PORT = Number(process.env.PORT ?? 8080)

// ---------------------------------------------------------------- state

let state
const reset = () => {
  state = { customers: new Map(), addresses: new Map(), orders: new Map(), seq: 0 }
}
reset()

const nextId = (prefix) => `${prefix}_${++state.seq}`

// BR-001: comparison is case-insensitive and ignores surrounding whitespace.
const normaliseEmail = (email) => String(email ?? '').trim().toLowerCase()

const addressesOf = (customerId) =>
  [...state.addresses.values()].filter((a) => a.customerId === customerId && !a.deleted)

/**
 * BR-002: exactly one address is the default, at all times.
 * The first address added becomes the default. Deleting the default promotes
 * the most recently used remaining address, or the oldest if none was used.
 */
function ensureDefault(customerId) {
  const list = addressesOf(customerId)
  if (!list.length) return
  if (list.some((a) => a.isDefault)) return

  const used = list.filter((a) => a.usedAt !== null)
  const promote = used.length
    ? used.reduce((best, a) => (a.usedAt > best.usedAt ? a : best))
    : list.reduce((best, a) => (a.createdAt < best.createdAt ? a : best))
  promote.isDefault = true
}

// ---------------------------------------------------------------- helpers

const send = (res, status, body) => {
  const payload = body === undefined ? '' : JSON.stringify(body)
  res.writeHead(status, payload ? { 'content-type': 'application/json' } : {})
  res.end(payload)
}

async function readBody(req) {
  const chunks = []
  for await (const c of req) chunks.push(c)
  if (!chunks.length) return {}
  try {
    return JSON.parse(Buffer.concat(chunks).toString())
  } catch {
    return {}
  }
}

// ---------------------------------------------------------------- routes

const routes = [
  ['GET', /^\/health$/, () => ({ status: 200, body: { ok: true } })],

  ['POST', /^\/reset$/, () => {
    reset()
    return { status: 204 }
  }],

  // BR-001: an email identifies at most one account, and a deleted customer
  // keeps theirs, so it is never released for reuse (ADR-001).
  ['POST', /^\/customers$/, (_m, body) => {
    const email = normaliseEmail(body.email)
    if (!email) return { status: 400, body: { message: 'email required' } }

    const taken = [...state.customers.values()].some((c) => c.email === email)
    // The message is deliberately generic: revealing that an account exists
    // would disclose account existence to anyone who can guess an address.
    if (taken) return { status: 409, body: { message: 'unable to register with those details' } }

    const customer = { id: nextId('cus'), email, deleted: false }
    state.customers.set(customer.id, customer)
    return { status: 201, body: { id: customer.id } }
  }],

  // BR-003: a deleted customer cannot authenticate, and the failure is
  // indistinguishable from an unknown account.
  ['POST', /^\/auth$/, (_m, body) => {
    const email = normaliseEmail(body.email)
    const customer = [...state.customers.values()].find((c) => c.email === email)
    if (!customer || customer.deleted) return { status: 401, body: { message: 'authentication failed' } }
    return { status: 200, body: { id: customer.id } }
  }],

  // ADR-001: deletion is soft. The record is retained so orders that reference
  // it survive.
  ['POST', /^\/customers\/([^/]+)\/delete$/, ([id]) => {
    const customer = state.customers.get(id)
    if (!customer) return { status: 404 }
    customer.deleted = true
    return { status: 204 }
  }],

  ['GET', /^\/customers\/([^/]+)\/addresses$/, ([id]) => {
    if (!state.customers.get(id)) return { status: 404 }
    return {
      status: 200,
      body: addressesOf(id)
        .sort((a, b) => a.createdAt - b.createdAt)
        .map((a) => ({ id: a.id, line: a.line, isDefault: a.isDefault })),
    }
  }],

  ['POST', /^\/customers\/([^/]+)\/addresses$/, ([id], body) => {
    if (!state.customers.get(id)) return { status: 404 }
    const line = String(body.line ?? '').trim()
    if (!line) return { status: 400, body: { message: 'line required' } }

    const address = {
      id: nextId('adr'),
      customerId: id,
      line,
      // BR-002: the first address added becomes the default.
      isDefault: addressesOf(id).length === 0,
      createdAt: ++state.seq,
      usedAt: null,
      deleted: false,
    }
    state.addresses.set(address.id, address)
    return { status: 201, body: { id: address.id, line: address.line, isDefault: address.isDefault } }
  }],

  ['PATCH', /^\/customers\/([^/]+)\/addresses\/([^/]+)$/, ([id, addressId], body) => {
    const address = state.addresses.get(addressId)
    if (!address || address.customerId !== id || address.deleted) return { status: 404 }
    const line = String(body.line ?? '').trim()
    if (!line) return { status: 400, body: { message: 'line required' } }
    // BR-010: orders hold their own copy, so editing here cannot reach them.
    address.line = line
    return { status: 200, body: { id: address.id, line: address.line, isDefault: address.isDefault } }
  }],

  ['DELETE', /^\/customers\/([^/]+)\/addresses\/([^/]+)$/, ([id, addressId]) => {
    const address = state.addresses.get(addressId)
    if (!address || address.customerId !== id || address.deleted) return { status: 404 }
    address.deleted = true
    address.isDefault = false
    ensureDefault(id)
    return { status: 204 }
  }],

  // BR-010: an order requires an address, ships to the default unless another
  // of the customer's own addresses is chosen, and copies it.
  ['POST', /^\/orders$/, (_m, body) => {
    const customer = state.customers.get(body.customerId)
    if (!customer) return { status: 400, body: { message: 'unknown customer' } }

    const list = addressesOf(customer.id)
    if (!list.length) return { status: 400, body: { message: 'customer has no address' } }

    let address
    if (body.addressId) {
      address = list.find((a) => a.id === body.addressId)
      if (!address) return { status: 400, body: { message: 'address does not belong to customer' } }
    } else {
      address = list.find((a) => a.isDefault)
      if (!address) return { status: 400, body: { message: 'customer has no default address' } }
    }

    address.usedAt = ++state.seq

    const order = {
      id: nextId('ord'),
      customerId: customer.id,
      // A copy, not a reference. Editing or deleting the address later must not
      // change where a past order was sent.
      shippingAddress: { line: address.line },
    }
    state.orders.set(order.id, order)
    return { status: 201, body: order }
  }],

  ['GET', /^\/orders\/([^/]+)$/, ([id]) => {
    const order = state.orders.get(id)
    if (!order) return { status: 404 }
    return { status: 200, body: order }
  }],
]

createServer(async (req, res) => {
  const path = new URL(req.url, 'http://localhost').pathname
  for (const [method, pattern, handler] of routes) {
    const match = pattern.exec(path)
    if (!match || req.method !== method) continue
    try {
      const { status, body } = await handler(match.slice(1), await readBody(req))
      return send(res, status, body)
    } catch (e) {
      return send(res, 500, { message: String(e) })
    }
  }
  send(res, 404, { message: 'not found' })
}).listen(PORT, () => console.log(`typescript implementation listening on ${PORT}`))
