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
| GET | `/customers/{id}/addresses` | List addresses, each with `isDefault` |
| POST | `/customers/{id}/addresses` | Add address. Body `{line}`. 201 |
| DELETE | `/customers/{id}/addresses/{addressId}` | Remove address. 204 |
