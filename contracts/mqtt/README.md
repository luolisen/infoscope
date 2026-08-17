# MQTT display-events v1

`display-events-v1.schema.json` is the authoritative Contract v1 source for Infoscope display terminals. The committed example is the canonical fixture that device repositories may vendor byte-for-byte with a recorded upstream commit SHA and SHA-256.

## Delivery

| Field | Value |
| --- | --- |
| Topic | `infoscope/v1/devices/{device_id}/events` |
| QoS | `1` |
| Retain | `true` |
| Ordering | `events` is oldest to newest; terminals render the final three |
| Maximum events | `12` |
| Maximum serialized payload | `4096` UTF-8 bytes |
| Revision | opaque; a repeated accepted revision is ignored |

The broker is LAN-only. Every device has a distinct credential and an ACL that permits it to subscribe only to its own topic. Publisher credentials are distinct. Anonymous access and public exposure are prohibited.

## Ownership and compatibility

The Infoscope repository owns this schema and fixture. Consumers must not derive ordering from backend implementation details or introduce a second Event schema. Contract v1 is immutable after merge: breaking changes require a new versioned schema, fixture, and review in both repositories.

This Contract does not authorize a live publisher, a status topic, database access from a device, or a device-to-user binding implementation. Those integrations require separately reviewed work.
