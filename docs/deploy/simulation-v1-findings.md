# Simulation v1: findings, 2026-10-24

## Result

One full simulated day ran against printarr (file mode, scheduler off, fake Home Assistant):
two morning briefings and releases, seven messages between the two of you in different moods,
one raw speech message, a note, a shopping list, a timed reminder, a water leak alert, a fun
fact, the evening rundown with a graph, the arrival and request releases, and six mistakes.

- 32 calls, 0 unexpected failures.
- All six mistakes returned 422 with a problem list.
- Strips drawn: 8 standalone and release images in the first run, with a manifest of every call.

Run it yourself with [simulation-v1.md](simulation-v1.md).

## Fixed in this run (PR #50, merged)

| Defect seen in the strips | Fix |
| --- | --- |
| `0.079 GBP/kWh` printed as `0.1`, both in briefings and in composed metric rows | One number formatter keeps small values' digits |
| `6120steps` ran the value into the unit | Letter units get a space, `%` does not |
| Receipts read `TO: yannic` and `FROM: hermes` when Allyson wrote the message | Receipts use the names, and `from_user` wins over the sender label |

## Open, not fixed in this run

These are design or renderer changes. Each needs a decision, so none was changed here.

1. **Briefings have no graphs.** Template 101 prints each metric as a text value with dot
   leaders. The sparklines and graphs the morning design calls for are not drawn. This is
   known (status report item 5). The morning briefing does not yet match the design system.
2. **Strip order breaks the greeting rule.** The evening rundown's greeting lands after the
   legacy text notes in the same pile strip. The rule that a greeting starts a new strip is
   not implemented (status report item 7).
3. **Legacy notes do not match the cards.** Notes from `/tickets` and template 102 print as
   plain text with a large heading and rules. Message cards print as outlined cards. In one
   strip the two styles sit together. Suggest sending notes through the message card.
4. **Dog counts are unreadable.** `P5 O1 F2 R0` does not say what each letter means, and `O1`
   reads like a zero. Options: words (`PEE 5 POO 1 FOOD 2 RUN 0`) on a second line, or icons.
   This is a taste call, so it is left for you.
5. **Some 422 messages leak internal wording.** `Value error, give a value or an entity_id`
   has a Pydantic prefix. `template 999 is not a slot template` does not say where to look
   (`GET /api/v1/slot-templates`). The `/tickets` recipient error is generic. These belong to
   the API thread, so they are reported here and not changed.
6. **Metric rows use checkbox squares as bullets.** They read as a checklist. Taste call.
7. **Setup wizard not built.** The first-run wizard you asked for is not in the code. Home
   Assistant settings exist on the settings page, but nothing walks a new install through
   them. This needs its own thread.

## Caveats on this run

- The printer simulator is not in this repo, and this cloud container cannot reach your
  laptop. The PNGs were drawn by `tools/simulate/escpos_decode.py`. Raster rows are exact. Text
  uses an approximate monospace font, so judge text in the real simulator.
- The taste review was done by reading the strips against the taste profile. Yannic, please
  check the morning briefing and the dog counts on the real simulator first.

## What looks right

- Message cards: the mood reads at a glance. Loving has a heart, sad a wave, confused a
  dashed rule, excited and happy a sun arc. Outlined cards and light type match the taste
  profile.
- The urgent alert with a filled label and the barcode top reads clearly.
- The shopping list with checked items is easy to scan.
- The graph card with min and max labels reads well at this size.
- Every API mistake I tried was refused before anything was queued, so no bad ticket reached
  the pile.

## Questions for you

1. Dog counts: words, icons, or keep the letters?
2. Should notes from `/tickets` become message cards? That changes how every note prints.
3. Keep the morning briefing as text until the graphs are ready, or hold it until they are?
