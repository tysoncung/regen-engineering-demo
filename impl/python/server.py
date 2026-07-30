"""Generated from the knowledge tree. See customer/knowledge and orders/knowledge.

No framework and no dependencies, so the demo runs anywhere Python does.
Storage is in memory: persistence would add plumbing without adding anything to
the argument this repository is making.

This is not a translation of the TypeScript implementation. Both were produced
from the same knowledge, and both are verified by the same contracts.
"""

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8080"))

# ---------------------------------------------------------------- state

state = {}


def reset():
    state.clear()
    state.update(customers={}, addresses={}, orders={}, seq=0)


reset()


def next_seq():
    state["seq"] += 1
    return state["seq"]


def next_id(prefix):
    return f"{prefix}_{next_seq()}"


def normalise_email(email):
    """BR-001: comparison is case-insensitive and ignores surrounding whitespace."""
    return str(email or "").strip().lower()


def addresses_of(customer_id):
    return [
        a
        for a in state["addresses"].values()
        if a["customerId"] == customer_id and not a["deleted"]
    ]


def ensure_default(customer_id):
    """BR-002: exactly one address is the default, at all times.

    The first address added becomes the default. Deleting the default promotes
    the most recently used remaining address, or the oldest if none was used.
    """
    current = addresses_of(customer_id)
    if not current or any(a["isDefault"] for a in current):
        return

    used = [a for a in current if a["usedAt"] is not None]
    if used:
        promote = max(used, key=lambda a: a["usedAt"])
    else:
        promote = min(current, key=lambda a: a["createdAt"])
    promote["isDefault"] = True


# ---------------------------------------------------------------- handlers
# Each returns (status, body). A body of None sends no content.


def health(_m, _b):
    return 200, {"ok": True}


def do_reset(_m, _b):
    reset()
    return 204, None


def register(_m, body):
    """BR-001: an email identifies at most one account, and a deleted customer
    keeps theirs, so it is never released for reuse (ADR-001)."""
    email = normalise_email(body.get("email"))
    if not email:
        return 400, {"message": "email required"}

    if any(c["email"] == email for c in state["customers"].values()):
        # Deliberately generic: naming the cause would disclose account
        # existence to anyone who can guess an address.
        return 409, {"message": "unable to register with those details"}

    customer = {"id": next_id("cus"), "email": email, "deleted": False}
    state["customers"][customer["id"]] = customer
    return 201, {"id": customer["id"]}


def authenticate(_m, body):
    """BR-003: a deleted customer cannot authenticate, and the failure is
    indistinguishable from an unknown account."""
    email = normalise_email(body.get("email"))
    customer = next(
        (c for c in state["customers"].values() if c["email"] == email), None
    )
    if customer is None or customer["deleted"]:
        return 401, {"message": "authentication failed"}
    return 200, {"id": customer["id"]}


def delete_customer(m, _b):
    """ADR-001: deletion is soft, so orders referencing the customer survive."""
    customer = state["customers"].get(m[0])
    if customer is None:
        return 404, None
    customer["deleted"] = True
    return 204, None


def list_addresses(m, _b):
    if m[0] not in state["customers"]:
        return 404, None
    ordered = sorted(addresses_of(m[0]), key=lambda a: a["createdAt"])
    return 200, [
        {"id": a["id"], "line": a["line"], "isDefault": a["isDefault"]} for a in ordered
    ]


def add_address(m, body):
    if m[0] not in state["customers"]:
        return 404, None
    line = str(body.get("line") or "").strip()
    if not line:
        return 400, {"message": "line required"}

    address = {
        "id": next_id("adr"),
        "customerId": m[0],
        "line": line,
        # BR-002: the first address added becomes the default.
        "isDefault": len(addresses_of(m[0])) == 0,
        "createdAt": next_seq(),
        "usedAt": None,
        "deleted": False,
    }
    state["addresses"][address["id"]] = address
    return 201, {
        "id": address["id"],
        "line": address["line"],
        "isDefault": address["isDefault"],
    }


def edit_address(m, body):
    address = state["addresses"].get(m[1])
    if address is None or address["customerId"] != m[0] or address["deleted"]:
        return 404, None
    line = str(body.get("line") or "").strip()
    if not line:
        return 400, {"message": "line required"}
    # BR-010: orders hold their own copy, so editing here cannot reach them.
    address["line"] = line
    return 200, {
        "id": address["id"],
        "line": address["line"],
        "isDefault": address["isDefault"],
    }


def delete_address(m, _b):
    address = state["addresses"].get(m[1])
    if address is None or address["customerId"] != m[0] or address["deleted"]:
        return 404, None
    address["deleted"] = True
    address["isDefault"] = False
    ensure_default(m[0])
    return 204, None


def place_order(_m, body):
    """BR-010: an order requires an address, ships to the default unless another
    of the customer's own addresses is chosen, and copies it."""
    customer = state["customers"].get(body.get("customerId"))
    if customer is None:
        return 400, {"message": "unknown customer"}

    available = addresses_of(customer["id"])
    if not available:
        return 400, {"message": "customer has no address"}

    if body.get("addressId"):
        address = next((a for a in available if a["id"] == body["addressId"]), None)
        if address is None:
            return 400, {"message": "address does not belong to customer"}
    else:
        address = next((a for a in available if a["isDefault"]), None)
        if address is None:
            return 400, {"message": "customer has no default address"}

    address["usedAt"] = next_seq()

    order = {
        "id": next_id("ord"),
        "customerId": customer["id"],
        # A copy, not a reference. Editing or deleting the address later must
        # not change where a past order was sent.
        "shippingAddress": {"line": address["line"]},
    }
    state["orders"][order["id"]] = order
    return 201, order


def get_order(m, _b):
    order = state["orders"].get(m[0])
    if order is None:
        return 404, None
    return 200, order


ROUTES = [
    ("GET", re.compile(r"^/health$"), health),
    ("POST", re.compile(r"^/reset$"), do_reset),
    ("POST", re.compile(r"^/customers$"), register),
    ("POST", re.compile(r"^/auth$"), authenticate),
    ("POST", re.compile(r"^/customers/([^/]+)/delete$"), delete_customer),
    ("GET", re.compile(r"^/customers/([^/]+)/addresses$"), list_addresses),
    ("POST", re.compile(r"^/customers/([^/]+)/addresses$"), add_address),
    ("PATCH", re.compile(r"^/customers/([^/]+)/addresses/([^/]+)$"), edit_address),
    ("DELETE", re.compile(r"^/customers/([^/]+)/addresses/([^/]+)$"), delete_address),
    ("POST", re.compile(r"^/orders$"), place_order),
    ("GET", re.compile(r"^/orders/([^/]+)$"), get_order),
]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass  # keep contract output readable

    def _dispatch(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {}

        for method, pattern, handler in ROUTES:
            match = pattern.match(path)
            if match and self.command == method:
                try:
                    return handler(list(match.groups()), body)
                except Exception as exc:  # noqa: BLE001
                    return 500, {"message": str(exc)}
        return 404, {"message": "not found"}

    def _respond(self):
        status, body = self._dispatch()
        payload = b"" if body is None else json.dumps(body).encode()
        self.send_response(status)
        if payload:
            self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    do_GET = do_POST = do_PATCH = do_DELETE = _respond


if __name__ == "__main__":
    print(f"python implementation listening on {PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
