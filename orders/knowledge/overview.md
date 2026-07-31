# Orders

Places orders against a customer's address book.

## Responsibilities

- Order placement
- Resolving the shipping address at placement time and copying it onto the order
- Recording that an address was used, which feeds the default-promotion rule

## Out of scope

- The address book itself, owned by `customer`
- Payment, fulfilment, and shipping

## Interface

The authoritative wire-format contract is [`api.openapi.yaml`](api.openapi.yaml) in this package (REP-0002). The table below is a human summary; where they disagree, the OpenAPI file wins and validation flags it.

A known path with an undocumented method gives 405.

| Method | Path | Purpose |
|---|---|---|
| POST | `/orders` | Place an order. Body `{customerId, addressId?}`. 201 or 400 |
| GET | `/orders/{id}` | Retrieve an order. 200, or 404 if unknown |

Omitting `addressId` ships to the customer's current default.

An unknown `customerId` is rejected with 400, not 404, since it is a bad request body rather than a missing resource.

### Order representation

Both endpoints return an order in this shape:

```json
{
  "id": "ord_1",
  "customerId": "cus_1",
  "shippingAddress": { "line": "1 First St" }
}
```

`shippingAddress` is an **object**, not a bare string, and it is a copy rather than a reference. It carries no `id`, deliberately: an id would invite consumers to follow it back to the address book and undo the whole point of copying.
