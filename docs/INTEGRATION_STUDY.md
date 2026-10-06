# Pre-integration study: live-session site (Salih2369/ABA) × observation channels

Status: study only, nothing merged. Studied in a local clone
(own `.venv` and `live-ui/node_modules`; nothing installed in this repository).

## 1. What the site is

- Same git history as this repository: its `main` = our `606363a` plus **additive**
  commits (`aba_demo/live/`, `live-ui/`, `docs/live-session-design.md`,
  `LIVE_WORKSTREAM.md`, `requirements-live.txt`, `tests/test_live_*`). Only
  `README.md` is modified, so a merge conflicts only there.
- Backend: FastAPI + WebSocket on `127.0.0.1:8767` (`python -m aba_demo.live`), a session
  state machine (open → lock target → start → pause/resume → end), a simulated recorder
  ledger, providers `SyntheticProvider` (8 scripted scenarios) and `PrecomputedProvider`
  (replays our old `observations.json` rows causally, SHA-bound to the video).
- Frontend: React 19 + TypeScript + Vite + Tailwind, English, dark/light.
- Data model: every frame row → the **old `Engine`** → five indicator tiles
  (orientation, body_motion, out_of_seat, hand_motion, posture_change) and one
  candidate card from `Engine.alert`.
- Verified here: UI build OK, 9/9 frontend tests, live tests pass; 12 old Colab tests
  error only because the clone's venv lacks Pillow (environment, not code). Ran the
  "Leaves seat" scenario end to end: target lock, live tiles, candidate card, event log.

## 2. Fit with the product (doctor's assistant, timeline strip, 3 activities)

| Site part | Verdict | Why / change |
|---|---|---|
| Session lifecycle, explicit target lock, identity gating, "not observable ≠ absent" | **Keep** | Same principles as ours |
| Activity switch (table / movement / break, therapist-set) | **Keep** | Same three activities; must drive our flag rules |
| Banners for stale / lost / late / failure, causal "no future results", SHA binding | **Keep** | Matches our causal + bound design |
| Event log | **Modify** | Becomes the session strip: our grouped moments with seek |
| Five indicator tiles from the old Engine | **Replace** | Old pose signals proved weak (posture transitions never detected); replace with our channels: posture state, large movement, facing direction, context note |
| Candidate card from `Engine.alert` | **Replace** | Driven by our flag rules (provisional-1: leaving the seat during table work) |
| Synthetic stage (drawn figure, no video) | **Modify** | Review after the session needs the real video with seek (our dashboard has it) |
| Scenario launcher (8 synthetic scripts) | **Modify** | Keep for demos; add "open recorded session" (video + tracking + channel files) |
| Session facts (recorder ledger, analysis p95, late results) | **Shrink** | Engineering detail; fold into a collapsed "technical" section |
| English copy, LTR | **Modify** | Arabic RTL for therapists (decision) |
| Old `Engine` / `PrecomputedProvider` of five signals | **Retire later** | Kept only while synthetic scenarios need it |

## 3. How we would integrate

1. Commit our work locally, then fetch the site as a branch and merge (one README
   conflict). Nothing pushed without Fahad's approval.
2. New provider `ChannelTimelineProvider`: loads the bound channel documents, builds the
   timeline (`session_timeline.build_timeline`), and on each frame emits the groups whose
   `detected_time` has passed (causal, like `PrecomputedProvider`).
3. New WebSocket event `timeline_moment` (group + entries + activity + level, context as
   "suggested"); activity changes from the live switch re-derive levels server-side with
   the same rules (no client copy of the rules).
4. UI: `SessionStrip` (marks on a bar + grouped list + seek), channel tiles replacing
   `IndicatorGrid`, candidate card fed by flags, a real `<video>` in review mode.
5. Analysis stays offline for now (our scripts produce the channel files); live inference
   is a later step (channels are already causal, so the contract does not change).

## 4. Decisions for Fahad

1. Which app becomes the main one: the site (recommended) with our `static/index.html`
   kept only as a test page?
2. Arabic RTL copy for the therapist UI?
3. Remove the five old tiles now, or keep them hidden behind a "legacy" toggle?
4. Accept FastAPI/React (needs `pip`/`npm` installs) as the product stack?
5. Coordination: integrate on our repository (`f7a10/child-therapy-aba-demo`) and ask the
   colleague to review via PR, or work on his repository?
