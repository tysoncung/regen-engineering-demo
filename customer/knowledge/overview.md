# Customer

Manages customer identity and the address book.

## Responsibilities

- Registration, with unique email
- Authentication
- Address book, including the default shipping address invariant
- Soft deletion

## Out of scope

- Orders, owned by `orders`
- Payment and billing

## Interface

| Method | Path | Purpose |
|---|---|---|
| POST | `/customers` | Register. Body `{email}`. 201 or 409 |
| POST | `/auth` | Authenticate. Body `{email}`. 200 or 401 |
| POST | `/customers/{id}/delete` | Soft delete. 204 |
| GET | `/customers/{id}/addresses` | List addresses. 200 |
| POST | `/customers/{id}/addresses` | Add address. Body `{line}`. 201 |
| PATCH | `/customers/{id}/addresses/{addressId}` | Change an address. Body `{line}`. 200 |
| DELETE | `/customers/{id}/addresses/{addressId}` | Remove address. 204 |

Unknown customer or address on any of these gives 404.

Deletion is idempotent: deleting an already-deleted account returns 204 again.
The operation asserts a state rather than performing a transition, and callers
retrying after a timeout must not receive an error for having succeeded.

### Representations

A customer, returned by `POST /customers` and `POST /auth`:

```json
{ "id": "cus_1" }
```

An address, returned by `POST` and `PATCH` on the address routes:

```json
{ "id": "adr_1", "line": "1 First St", "isDefault": true }
```

`GET /customers/{id}/addresses` returns a **bare JSON array** of those objects, not an object wrapping them, ordered oldest first.

### Error bodies

Failures return `{"message": "..."}`. The message is for humans and carries no machine-readable code.

For 409 on registration and 401 on authentication the message must be generic, because a specific one would disclose whether an account exists. It must not contain the words *exists*, *already*, *registered*, *taken*, or *duplicate*.
