# Security

## Reporting a vulnerability

Email **security@kairos.trade**. Please don't open a public issue for anything exploitable.

## If an API key leaks

Do this in order:

1. **Generate a replacement.** kairos.trade → profile picture → Settings → API Keys.
2. **Cut over** your bot to the new key.
3. **Delete the old key.** Deletion is what stops the bleeding — rotating without
   deleting leaves the leaked credential live.
4. **Check `GET /orders`** for orders you didn't place, and `GET /positions/exposure`
   for positions you didn't open.

A key committed to git is compromised even after a force-push: it persists in forks,
clones, CI logs and caching proxies. Rotate; don't rewrite history and hope.

## Scope your keys

Give each key the narrowest scope set that does its job — `trade:read` alone for a
scanner, `trade:execute` only where orders are actually placed. Use a separate key per
bot so one can be killed without killing the rest. Where your egress IP is stable, turn
on the credential's IP whitelist.

## Keys and AI assistants

Letting an agent build against this API is fine and expected. Letting it *see* your
secret is not. Keep credentials in `.env` or a secret manager, referenced by environment
variable — prompts and chat transcripts are logged, and a secret pasted into one is a
secret you no longer control.
