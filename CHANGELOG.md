# Changelog

Versions are the module's own, not the API revision — the two mean different
things, and a dashboard reading one field for both is wrong about every module
it does not special-case. A change to the shape of `/health` or any endpoint is
a contract change and gets its own entry.

## 0.2.0

**The vault stored provider credentials in plaintext.** "Write-only" is a
property of the HTTP surface — no route returns a value — but that says nothing
about the file, and anyone with file access read every key. Values are now
Fernet tokens behind an `enc:v1:` prefix, with the key derived by scrypt from an
install-time secret held deliberately *outside* the values file: either
`TOOLGATE_VAULT_SECRET`, or a `0600` key file on its own volume, so copying the
data directory does not carry the key that decrypts it. The scrypt salt sits
beside the values because a salt is not a secret and keeping it there is what
lets a passphrase survive a restart. `encrypt_values_at_rest()` migrates an
existing plaintext file.

**`/health` probed nothing** and returned a fixed answer, so a dependency could
be gone while health said otherwise. It now probes the control plane database,
the vault, searxng, MemoryGate and the planner, reporting `degraded` naming what
failed. It distinguishes `not_configured` from `unavailable`, because "nothing
here yet" and "it broke" are different facts and collapsing them is how a
dashboard starts lying. Answers are cached with their age, since the route is
unauthenticated.

**`/health` now answers in the shared module contract shape** — adding `service`
and changing `version` from the API revision `"v2"` to this module's own version.

**The stdio MCP bridge is renamed and described honestly.** Behaviour is
unchanged: it reads no execution key, never calls `is_scoped`, and attributes
everything to one hardcoded actor. It is now the single-operator console bridge
and says so in its first paragraph, alongside what still applies — lockdown,
validation, approval binding, limits and audit. Agents use the keyed HTTP API,
which enforces the identity and scope this cannot. See
`docs/SINGLE_OPERATOR_MCP_BRIDGE.md`.

Also fixes a pre-existing test failure on Windows, where runtime paths were
compared as strings across a platform separator difference.

## 0.1.0

First release. Services, tools, automations and requests; per-tool policy;
rotatable scoped execution keys; approvals bound to an exact object, version,
argument digest, nonce and expiry, consumed once; signed verification callbacks;
lockdown mode; redacted audit trail; stdio MCP bridge.
