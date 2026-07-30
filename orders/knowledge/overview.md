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

| Method | Path | Purpose |
|---|---|---|
| POST | `/orders` | Place an order. Body `{customerId, addressId?}`. 201 or 400 |
| GET | `/orders/{id}` | Retrieve an order, including its copied `shippingAddress` |

Omitting `addressId` ships to the customer's current default.
