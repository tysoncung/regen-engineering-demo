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
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_LOCK = threading.RLock()

# Monotonic sequence used for both "created" ordering (oldest) and
# "used" ordering (most recently used). BR-002 needs both.
_SEQ = [0]


def _next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


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
        _SEQ[0] = 0


STORE = Store()


def normalise_email(value):
    """BR-001: comparison is case-insensitive and ignores surrounding whitespace."""
    return value.strip().lower()


def new_id(prefix):
    return "%s_%s" % (prefix, uuid.uuid4().hex[:12])


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------


def address_view(customer, address):
    return {
        "id": address["id"],
        "line": address["line"],
        "isDefault": customer["defaultAddressId"] == address["id"],
    }


def find_address(customer, address_id):
    for address in customer["addresses"]:
        if address["id"] == address_id:
            return address
    return None


def reestablish_default(customer):
    """
    BR-002. Exactly one default while at least one address exists.

    Called after a deletion, and after an add when there is no default.
    - most recently used remaining address wins
    - otherwise the oldest remaining address
    - no addresses means no default
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


def order_view(order):
    return {
        "id": order["id"],
        "customerId": order["customerId"],
        # BR-010: a copy, not a reference. Kept verbatim from placement time.
        "shippingAddress": order["shippingAddress"],
        "shippingAddressId": order["shippingAddressId"],
        "placedAt": order["placedAt"],
    }


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

GENERIC_REGISTRATION_FAILURE = "Unable to complete request."
GENERIC_AUTH_FAILURE = "Invalid credentials."


def register_customer(body):
    email = body.get("email") if isinstance(body, dict) else None
    if not isinstance(email, str) or not email.strip():
        return 400, {"error": "invalid_request", "message": "email is required"}

    key = normalise_email(email)
    with _LOCK:
        if key in STORE.emails:
            # BR-001 / CT-001. Generic body, no disclosure that an account exists.
            return 409, {
                "error": "conflict",
                "message": GENERIC_REGISTRATION_FAILURE,
            }
        customer = {
            "id": new_id("cus"),
            "email": email.strip(),
            "emailKey": key,
            "deleted": False,
            "addresses": [],
            "defaultAddressId": None,
            "createdSeq": _next_seq(),
        }
        STORE.customers[customer["id"]] = customer
        STORE.emails[key] = customer["id"]

    return 201, {"id": customer["id"], "email": customer["email"], "deleted": False}


def authenticate(body):
    email = body.get("email") if isinstance(body, dict) else None
    if not isinstance(email, str):
        # Same generic failure, so a malformed attempt discloses nothing either.
        return 401, {"error": "unauthorized", "message": GENERIC_AUTH_FAILURE}

    key = normalise_email(email)
    with _LOCK:
        customer_id = STORE.emails.get(key)
        customer = STORE.customers.get(customer_id) if customer_id else None
        # BR-003: unknown and deleted fail identically.
        if customer is None or customer["deleted"]:
            return 401, {"error": "unauthorized", "message": GENERIC_AUTH_FAILURE}
        return 200, {
            "id": customer["id"],
            "email": customer["email"],
            "authenticated": True,
        }


def soft_delete_customer(customer_id):
    with _LOCK:
        customer = STORE.customers.get(customer_id)
        if customer is None:
            return 404, {"error": "not_found", "message": "customer not found"}
        # ADR-001: mark deleted, retain the record and the email.
        customer["deleted"] = True
    return 204, None


def get_customer(customer_id):
    with _LOCK:
        customer = STORE.customers.get(customer_id)
        if customer is None:
            return 404, {"error": "not_found", "message": "customer not found"}
        return 200, {
            "id": customer["id"],
            "email": customer["email"],
            "deleted": customer["deleted"],
        }


def list_addresses(customer_id):
    with _LOCK:
        customer = STORE.customers.get(customer_id)
        if customer is None:
            return 404, {"error": "not_found", "message": "customer not found"}
        ordered = sorted(customer["addresses"], key=lambda a: a["createdSeq"])
        return 200, [address_view(customer, a) for a in ordered]


def add_address(customer_id, body):
    line = body.get("line") if isinstance(body, dict) else None
    if not isinstance(line, str) or not line.strip():
        return 400, {"error": "invalid_request", "message": "line is required"}

    with _LOCK:
        customer = STORE.customers.get(customer_id)
        if customer is None:
            return 404, {"error": "not_found", "message": "customer not found"}
        address = {
            "id": new_id("adr"),
            "line": line,
            "createdSeq": _next_seq(),
            "usedSeq": None,
        }
        customer["addresses"].append(address)
        # BR-002: the first address becomes the default, later ones do not
        # disturb it.
        if customer["defaultAddressId"] is None:
            customer["defaultAddressId"] = address["id"]
        return 201, address_view(customer, address)


def edit_address(customer_id, address_id, body):
    line = body.get("line") if isinstance(body, dict) else None
    if not isinstance(line, str) or not line.strip():
        return 400, {"error": "invalid_request", "message": "line is required"}

    with _LOCK:
        customer = STORE.customers.get(customer_id)
        if customer is None:
            return 404, {"error": "not_found", "message": "customer not found"}
        address = find_address(customer, address_id)
        if address is None:
            return 404, {"error": "not_found", "message": "address not found"}
        # BR-010: orders hold a copy, so editing here must not touch any order.
        address["line"] = line
        return 200, address_view(customer, address)


def set_default_address(customer_id, address_id):
    with _LOCK:
        customer = STORE.customers.get(customer_id)
        if customer is None:
            return 404, {"error": "not_found", "message": "customer not found"}
        address = find_address(customer, address_id)
        if address is None:
            return 404, {"error": "not_found", "message": "address not found"}
        customer["defaultAddressId"] = address["id"]
        return 200, address_view(customer, address)


def delete_address(customer_id, address_id):
    with _LOCK:
        customer = STORE.customers.get(customer_id)
        if customer is None:
            return 404, {"error": "not_found", "message": "customer not found"}
        address = find_address(customer, address_id)
        if address is None:
            return 404, {"error": "not_found", "message": "address not found"}

        was_default = customer["defaultAddressId"] == address_id
        customer["addresses"] = [
            a for a in customer["addresses"] if a["id"] != address_id
        ]
        # BR-002: only removing the default triggers promotion.
        if was_default:
            customer["defaultAddressId"] = None
            reestablish_default(customer)
        return 204, None


def place_order(body):
    if not isinstance(body, dict):
        return 400, {"error": "invalid_request", "message": "body is required"}
    customer_id = body.get("customerId")
    address_id = body.get("addressId")

    with _LOCK:
        customer = STORE.customers.get(customer_id) if customer_id else None
        if customer is None:
            return 400, {"error": "invalid_request", "message": "unknown customer"}

        if address_id is None:
            # Overview: omitting addressId ships to the current default.
            if customer["defaultAddressId"] is None:
                return 400, {
                    "error": "invalid_request",
                    "message": "customer has no address",
                }
            address = find_address(customer, customer["defaultAddressId"])
        else:
            # BR-010: an address that is not the customer's own is rejected.
            address = find_address(customer, address_id)

        if address is None:
            return 400, {"error": "invalid_request", "message": "invalid address"}

        seq = _next_seq()
        # BR-010 -> BR-002: placing an order marks the address used.
        address["usedSeq"] = seq

        order = {
            "id": new_id("ord"),
            "customerId": customer["id"],
            "shippingAddressId": address["id"],
            # The copy. Deliberately detached from the address record.
            "shippingAddress": address["line"],
            "placedAt": seq,
        }
        STORE.orders[order["id"]] = order
        return 201, order_view(order)


def get_order(order_id):
    with _LOCK:
        order = STORE.orders.get(order_id)
        if order is None:
            return 404, {"error": "not_found", "message": "order not found"}
        return 200, order_view(order)


def reset_state():
    with _LOCK:
        STORE.reset()
    return 204, None


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

RE_CUSTOMER = re.compile(r"^/customers/([^/]+)$")
RE_CUSTOMER_DELETE = re.compile(r"^/customers/([^/]+)/delete$")
RE_ADDRESSES = re.compile(r"^/customers/([^/]+)/addresses$")
RE_ADDRESS = re.compile(r"^/customers/([^/]+)/addresses/([^/]+)$")
RE_ADDRESS_DEFAULT = re.compile(r"^/customers/([^/]+)/addresses/([^/]+)/default$")
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

    m = RE_ADDRESS_DEFAULT.match(path)
    if m and method in ("POST", "PUT", "PATCH"):
        return set_default_address(m.group(1), m.group(2))

    m = RE_ADDRESSES.match(path)
    if m:
        if method == "GET":
            return list_addresses(m.group(1))
        if method == "POST":
            return add_address(m.group(1), body)
        return 405, {"error": "method_not_allowed"}

    m = RE_ADDRESS.match(path)
    if m:
        if method == "DELETE":
            return delete_address(m.group(1), m.group(2))
        if method in ("PUT", "PATCH", "POST"):
            return edit_address(m.group(1), m.group(2), body)
        if method == "GET":
            code, payload = list_addresses(m.group(1))
            if code != 200:
                return code, payload
            for item in payload:
                if item["id"] == m.group(2):
                    return 200, item
            return 404, {"error": "not_found", "message": "address not found"}
        return 405, {"error": "method_not_allowed"}

    m = RE_CUSTOMER.match(path)
    if m:
        if method == "GET":
            return get_customer(m.group(1))
        if method == "DELETE":
            return soft_delete_customer(m.group(1))
        return 405, {"error": "method_not_allowed"}

    m = RE_ORDER.match(path)
    if m and method == "GET":
        return get_order(m.group(1))

    return 404, {"error": "not_found", "message": "no such route"}


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
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return parsed

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
            self._respond(400, {"error": "invalid_json", "message": "malformed body"})
            return
        try:
            status, payload = route(method, path, body)
        except Exception as exc:  # pragma: no cover - defensive
            self._respond(500, {"error": "internal_error", "message": str(exc)})
            return
        self._respond(status, payload)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_PATCH(self):
        self._handle("PATCH")

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
