# Project instructions

## Purpose and scope

This is an experimental ABA visual-observation demo: a therapist selects a child in an authorized recording and reviews evidence-linked visual observations. The current product is a recorded-video analysis/replay demo, not a deployed live-session system or clinically validated product. The longer-term goal is local/on-prem, live therapist assistance; do not describe that goal as implemented.

Describe observable evidence only. Do not infer attention, hyperactivity, intent, emotion, diagnosis, behavior function, or treatment. Keep behavior hypotheses and clinical decisions with the therapist. Generalize to different recordings; do not encode one child's IDs, timing, clothes, or scene as product logic.

## Architecture and locations

- `aba_demo/vision.py`: optional YOLO pose/person tracking, target selection, identity gating and experimental pose-derived signals. `botsort_reid.yaml` is the reviewed tracker profile. Tracker IDs are temporary associations, not a persistent person identity.
- `aba_demo/colab_workflow.py`: `ReviewSession` keeps the analyzer alive through preview, selection/reselection and sequential decoding; creates causal audit/evidence, pending tracking/context candidates, review reports and explicit publication.
- `aba_demo/export.py`: observation validation, source SHA-256, provenance and quality checks.
- `aba_demo/engine.py`: deterministic temporal candidates from measured observations. This is not a VLM movement reader.
- `aba_demo/context_schema.py`, `openrouter_context.py`, `context_review.py`: bounded context contract, provider adapter, and human review. Context is separate from pose measurements and cannot establish identity.
- `aba_demo/server.py` + `aba_demo/static/index.html`: loopback server and precomputed replay dashboard. Opening replay does not itself run inference or upload the selected recording.
- `notebooks/ABA_Colab_Ready.ipynb`, `scripts/prepare_demo_colab_bundle.py`: reviewed Colab entry point and code-only bundle with pinned integrity checks.
- `tests/`: standard-library `unittest` tests, including served-JavaScript checks through Node.js. See `README.md` for user-facing setup; `docs/HANDOFF.md` contains temporary state and plan references.

## Non-negotiable contracts

- No attributed observation without a currently confirmed target. Preserve causal identity audits; later reselection must not retroactively fill unknown frames. A quality-passing session can still contain identity gaps.
- `null`/not observable is not `False`, no movement, or absence of behavior. Preserve per-signal quality gates and the five pose signal keys: `orientation`, `body_motion`, `out_of_seat`, `hand_motion`, `posture_change`.
- Context evidence must be tied to the selected child and exact supplied frames/times, without crossing identity gaps. Adult-only handling of toys is not child-material interaction; an adult hand inside the child's crop is not the child's hand. Ambiguous evidence requires abstention.
- Bind source video by SHA-256 and derived context by the exact tracking-candidate bytes. Keep pending candidates distinct from published artifacts; publication requires explicit review of the exact hashes. HTTP 200, valid JSON and passing unit tests do not establish semantic or clinical accuracy.
- OpenRouter requests retain strict structured output and `require_parameters=True`, `data_collection='deny'`, `allow_fallbacks=False`. Preserve bounded responses, provenance validation and sanitized errors. Do not weaken validation or silently substitute a provider/model. These settings are not a zero-data-retention guarantee.
- VLM context must not replace identity, overwrite pose `signals`, or fill missing measurements. A new movement-reading channel needs its own reviewed contract.

## Privacy and repository boundary

Never commit or share recordings, scene frames/crops, participant notes, generated observation/review JSON, model weights, private notebook backups, `.env` or credentials. Ignore rules are not a privacy audit. Keep real-session outputs outside the public source tree. Obtain explicit authorization covering everyone visible and the external service before real footage is processed remotely; scene images can include the therapist. The existing demo is not guaranteed offline: missing weights/dependencies can trigger downloads.

Use only approved compute for heavy inference; Colab and a separately validated local GPU environment are development options. Keep notebook outputs, execution counts and attachments clean in shareable code bundles. If bundle contents change, regenerate and verify the notebook's pinned digest/member checks together.

## Development and commands

Use Python 3.11+, four-space indentation, small modules, explicit validation and existing `unittest` conventions. Keep project Markdown in English. There is no frontend package/build pipeline; Node.js is needed for JS tests, not to serve the UI.

From the repository root, using the intended Python environment:

```bash
python -m aba_demo.server
python -m unittest discover -s tests -q
python scripts/prepare_demo_colab_bundle.py --output ../demo_colab_bundle.zip
```

The server defaults to loopback port `8766`; do not expose it publicly. The full test suite needs Pillow (`Pillow>=10,<13`) and Node.js. Heavy inference dependencies are separately listed in `requirements-demo-vision.txt`; do not install them just to run logic/replay tests. Use `python -m pip`, not an unqualified `pip` that may target another interpreter.

Inspect Git state and relevant tests before editing. Preserve pre-existing dirty files; do not reset, clean, stash or discard them to obtain a clean baseline. Work in small vertical RED → GREEN → REFACTOR slices and run relevant tests plus the full suite. Do not erase a user's notebook outputs/selections just to force tests green.

Plans are proposals, not execution authorization or proof of implemented features. Do not commit, push or publish unless the user authorizes it. Stage only explicitly approved paths; do not include Markdown in code uploads under the existing owner rule. Documentation transfer needs separate authorization. Keep durable rules here and temporary progress in `docs/HANDOFF.md`, without copying conversation history.
