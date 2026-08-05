#!/usr/bin/env python3
"""
Regeneration Test implementation, Python.

Generated from the knowledge specification only:
  knowledge/vision.md
  customer/knowledge/{overview.md, rules/BR-001..003, decisions/ADR-001, contracts/CT-001..003}
  orders/knowledge/{overview.md, rules/BR-010, contracts/CT-010}

Standard library only. In-memory storage only.
"""

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        # customer_id -> customer dict
        self.customers = {}
        # normalised email -> customer_id (BR-001: never released, ADR-001)
        self.emails = {}
        # order_id -> order dict
        self.orders = {}
        # Monotonic sequence shared by every entity. It gives address creation
        # order ("oldest") and order placement order ("most recently used"),
        # which is all BR-002 needs.
        self.seq = 0
        self.counters = {"cus": 0, "adr": 0, "ord": 0}

    def next_seq(self):
        self.seq += 1
        return self.seq

    def next_id(self, prefix):
        self.counters[prefix] += 1
        return "%s_%d" % (prefix, self.counters[prefix])


STORE = Store()


def normalise_email(value):
    """BR-001: comparison is case-insensitive and ignores surrounding whitespace."""
    return value.strip().lower()


# ---------------------------------------------------------------------------
# Representations
# ---------------------------------------------------------------------------


def customer_view(customer):
    """customer/overview.md: a customer is just its id."""
    return {"id": customer["id"]}


def address_view(customer, address):
    return {
        "id": address["id"],
        "line": address["line"],
        "isDefault": customer["defaultAddressId"] == address["id"],
    }


def order_view(order):
    """
    orders/overview.md. shippingAddress is an object and carries no id,
    deliberately, so nothing can follow it back to the address book.
    """
    return {
        "id": order["id"],
        "customerId": order["customerId"],
        "shippingAddress": {"line": order["shippingAddressLine"]},
    }


def error(message):
    """customer/overview.md: failures return {"message": ...}, no machine code."""
    return {"message": message}


# Generic, and identical between the two 401 cases, so neither discloses whether
# an account exists. Neither string contains exists / already / registered /
# taken / duplicate.
GENERIC_REGISTRATION_FAILURE = "Unable to complete request."
GENERIC_AUTH_FAILURE = "Authentication failed."

# BR-011: at most twenty addresses per customer. A product limit rather than a
# storage one, and deliberately not configurable (ASM-001), so it is a constant
# here rather than an environment variable.
ADDRESS_LIMIT = 20
# No code, no count, no remaining-slots figure: callers would parse them.
ADDRESS_BOOK_FULL = "The address book is full."


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------


def find_address(customer, address_id):
    for address in customer["addresses"]:
        if address["id"] == address_id:
            return address
    return None


def sorted_addresses(customer):
    """Oldest first."""
    return sorted(customer["addresses"], key=lambda a: a["createdSeq"])


def reestablish_default(customer):
    """
    BR-002. A customer with at least one address has exactly one default, a
    customer with none has none.

    - the most recently used remaining address wins, recency being order of
      placement
    - otherwise the oldest remaining address
    """
    addresses = customer["addresses"]
    if not addresses:
        customer["defaultAddressId"] = None
        return

    used = [a for a in addresses if a["usedSeq"] is not None]
    if used:
        winner = max(used, key=lambda a: a["usedSeq"])
    else:
        winner = min(addresses, key=lambda a: a["createdSeq"])
    customer["defaultAddressId"] = winner["id"]


# ---------------------------------------------------------------------------
# Customer handlers
# ---------------------------------------------------------------------------


def register_customer(body):
    email = body.get("email") if isinstance(body, dict) else None
    if not isinstance(email, str) or not email.strip():
        return 400, error("email is required")

    key = normalise_email(email)
    with _LOCK:
        if key in STORE.emails:
            # BR-001 / CT-001. Generic body, no disclosure.
            return 409, error(GENERIC_REGISTRATION_FAILURE)
        customer = {
            "id": STORE.next_id("cus"),
            "email": email.strip(),
            "emailKey": key,
            "deleted": False,
            "addresses": [],
            "defaultAddressId": None,
        }
        STORE.customers[customer["id"]] = customer
        STORE.emails[key] = customer["id"]
        return 201, customer_view(customer)


def authenticate(body):
    email = body.get("email") if isinstance(body, dict) else None
    if not isinstance(email, str):
        return 401, error(GENERIC_AUTH_FAILURE)

    key = normalise_email(email)
    with _LOCK:
        customer_id = STORE.emails.get(key)
        customer = STORE.customers.get(customer_id) if customer_id else None
        # BR-003: unknown and deleted are indistinguishable to the caller.
        if customer is None or customer["deleted"]:
            return 401, error(GENERIC_AUTH_FAILURE)
        return 200, customer_view(customer)


def soft_delete_customer(customer_id):
    with _LOCK:
        customer = STORE.customers.get(customer_id)
        if customer is None:
            return 404, error("customer not found")
        # ADR-001: mark deleted, retain the record and the email.
        # BR-003: this restricts authentication and nothing else.
        customer["deleted"] = True
    return 204, None


# ---------------------------------------------------------------------------
# Address handlers
# ---------------------------------------------------------------------------


def list_addresses(customer_id):
    with _LOCK:
        customer = STORE.customers.get(customer_id)
        if customer is None:
            return 404, error("customer not found")
        # A bare JSON array, oldest first. Still readable once the customer is
        # deleted (BR-003).
        return 200, [address_view(customer, a) for a in sorted_addresses(customer)]


def add_address(customer_id, body):
    line = body.get("line") if isinstance(body, dict) else None
    if not isinstance(line, str) or not line.strip():
        return 400, error("line is required")

    with _LOCK:
        customer = STORE.customers.get(customer_id)
        if customer is None:
            return 404, error("customer not found")
        # BR-011: checked last, so only a request that would otherwise have
        # succeeded gets the 409. Deleting an address removes it from this list
        # and so frees a slot immediately.
        if len(customer["addresses"]) >= ADDRESS_LIMIT:
            return 409, error(ADDRESS_BOOK_FULL)
        address = {
            "id": STORE.next_id("adr"),
            "line": line,
            "createdSeq": STORE.next_seq(),
            "usedSeq": None,
        }
        customer["addresses"].append(address)
        # BR-002: the first address becomes the default, later ones leave it
        # alone. This also covers adding again after the last one was deleted.
        if customer["defaultAddressId"] is None:
            customer["defaultAddressId"] = address["id"]
        return 201, address_view(customer, address)


def change_address(customer_id, address_id, body):
    line = body.get("line") if isinstance(body, dict) else None
    if not isinstance(line, str) or not line.strip():
        return 400, error("line is required")

    with _LOCK:
        customer = STORE.customers.get(customer_id)
        if customer is None:
            return 404, error("customer not found")
        address = find_address(customer, address_id)
        if address is None:
            return 404, error("address not found")
        # BR-010: an order holds a copy, so this must not reach any order.
        address["line"] = line
        return 200, address_view(customer, address)


def delete_address(customer_id, address_id):
    with _LOCK:
        customer = STORE.customers.get(customer_id)
        if customer is None:
            return 404, error("customer not found")
        address = find_address(customer, address_id)
        if address is None:
            return 404, error("address not found")

        was_default = customer["defaultAddressId"] == address_id
        customer["addresses"] = [
            a for a in customer["addresses"] if a["id"] != address_id
        ]
        # BR-002: only removing the default triggers promotion.
        if was_default:
            customer["defaultAddressId"] = None
            reestablish_default(customer)
        return 204, None


# ---------------------------------------------------------------------------
# Order handlers
# ---------------------------------------------------------------------------


def place_order(body):
    if not isinstance(body, dict):
        return 400, error("customerId is required")
    customer_id = body.get("customerId")
    address_id = body.get("addressId")

    with _LOCK:
        customer = STORE.customers.get(customer_id) if customer_id else None
        # A bad request body rather than a missing resource, so 400 not 404.
        if customer is None:
            return 400, error("unknown customer")

        if address_id is None:
            # Omitting addressId ships to the customer's current default.
            if customer["defaultAddressId"] is None:
                return 400, error("customer has no address")
            address = find_address(customer, customer["defaultAddressId"])
        else:
            # BR-010: an address that is not the customer's own is rejected.
            address = find_address(customer, address_id)

        if address is None:
            return 400, error("address does not belong to this customer")

        # BR-010 feeding BR-002: placing an order marks the address used, and
        # recency is the order of placement.
        address["usedSeq"] = STORE.next_seq()

        order = {
            "id": STORE.next_id("ord"),
            "customerId": customer["id"],
            # The copy. Deliberately detached from the address record.
            "shippingAddressLine": address["line"],
        }
        STORE.orders[order["id"]] = order
        return 201, order_view(order)


def get_order(order_id):
    with _LOCK:
        order = STORE.orders.get(order_id)
        if order is None:
            return 404, error("order not found")
        return 200, order_view(order)


# ---------------------------------------------------------------------------
# Test harness support, not part of the domain knowledge
# ---------------------------------------------------------------------------


def reset_state():
    with _LOCK:
        STORE.reset()
    return 204, None


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

RE_CUSTOMER_DELETE = re.compile(r"^/customers/([^/]+)/delete$")
RE_ADDRESSES = re.compile(r"^/customers/([^/]+)/addresses$")
RE_ADDRESS = re.compile(r"^/customers/([^/]+)/addresses/([^/]+)$")
RE_ORDER = re.compile(r"^/orders/([^/]+)$")


def route(method, path, body):
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/") or "/"

    if method == "GET" and path == "/health":
        return 200, {"status": "ok"}
    if method == "POST" and path == "/reset":
        return reset_state()

    if method == "POST" and path == "/customers":
        return register_customer(body)
    if method == "POST" and path == "/auth":
        return authenticate(body)
    if method == "POST" and path == "/orders":
        return place_order(body)

    m = RE_CUSTOMER_DELETE.match(path)
    if m and method == "POST":
        return soft_delete_customer(m.group(1))

    m = RE_ADDRESSES.match(path)
    if m:
        if method == "GET":
            return list_addresses(m.group(1))
        if method == "POST":
            return add_address(m.group(1), body)
        return 405, error("method not allowed")

    m = RE_ADDRESS.match(path)
    if m:
        # PATCH is the documented verb. PUT is accepted as a synonym so a
        # caller reaching for it is not silently wrong.
        if method in ("PATCH", "PUT"):
            return change_address(m.group(1), m.group(2), body)
        if method == "DELETE":
            return delete_address(m.group(1), m.group(2))
        return 405, error("method not allowed")

    m = RE_ORDER.match(path)
    if m and method == "GET":
        return get_order(m.group(1))

    return 404, error("no such route")


# ---------------------------------------------------------------------------
# HTTP plumbing
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "regen-python/1.0"

    def log_message(self, fmt, *args):  # noqa: A003 - suppress per-request logging
        pass

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def _respond(self, status, payload):
        if status == 204 or payload is None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, method):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        body = self._read_body()
        if body is None:
            self._respond(400, error("malformed body"))
            return
        try:
            status, payload = route(method, path, body)
        except Exception as exc:  # pragma: no cover - defensive
            self._respond(500, error(str(exc)))
            return
        self._respond(status, payload)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_HEAD(self):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        try:
            status, _payload = route("GET", path, {})
        except Exception:  # pragma: no cover - defensive
            status = 500
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "0")
        self.end_headers()


def main():
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    print("python impl listening on http://127.0.0.1:%d" % port, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
