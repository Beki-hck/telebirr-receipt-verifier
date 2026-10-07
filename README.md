# Telebirr Receipt Verifier

![tests](https://github.com/Beki-hck/telebirr-receipt-verifier/actions/workflows/tests.yml/badge.svg)

A small Python tool that checks whether a Telebirr payment really happened. Given the transaction number from a Telebirr SMS, it fetches the public receipt page from Ethio Telecom and pulls out the sender, receiver, amount, date and status.

Useful for small shops that want to confirm a customer's payment before handing over goods, without a merchant API.

> **Status: prototype.** The parser is tested against a sample receipt page. It has not yet been checked against a live receipt, and the field labels may need adjusting once it is.

## Usage

```bash
pip install -r requirements.txt
```

```python
from telebirr_verify import verify_telebirr

result = verify_telebirr("CE12345678AB")
if result.success:
    print(result.sender_name, result.amount, result.status)
else:
    print("Verification failed:", result.error)
```

## How it works

1. Builds the receipt URL: `https://transactioninfo.ethiotelecom.et/receipt/{receipt_no}`
2. Fetches the page with a timeout, so a slow request never hangs a checkout.
3. Reads label/value pairs from the page and maps them to fields.
4. Returns a result object with either the details or a clear error. It never guesses a value it could not find.

**Note:** Ethio Telecom only serves receipt pages to Ethiopian IP addresses, so this must run on a machine or server inside Ethiopia.

## Tests

```bash
pytest -q
```

The tests cover a successful parse, an unreachable page, and an invalid receipt number. Network calls are mocked.

## Roadmap

- [ ] Check the parser against a real receipt page and save it (with personal details removed) as a test fixture
- [ ] Small web form for shopkeepers to paste a transaction number
- [ ] Flag mismatches between the expected and paid amount
