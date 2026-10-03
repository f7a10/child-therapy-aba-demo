"""Run the ABA visual assistant on loopback: python -m aba_demo.live

The home page analyses a new video (upload, select the child, run the channels)
and lists the analysed sessions for review. The synthetic live-session tests are
engineering-only (``--with-simulations``).
"""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LIBRARY = Path.home() / "ABA Visual Assistant" / "sessions"
CONTEXT_MODEL = "deepseek/deepseek-v4.1-flash"
CONTEXT_PROVIDER = "Wafer"


def _device():
    """The local GPU when available; otherwise the models choose (CPU)."""
    try:
        import torch
    except ImportError:
        return None
    return 0 if torch.cuda.is_available() else None


def main() -> None:
    parser = argparse.ArgumentParser(description="ABA visual assistant (local, loopback only)")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--dev", action="store_true",
                        help="also accept requests from the Vite dev server on port 5173")
    parser.add_argument("--library", metavar="DIR", default=str(DEFAULT_LIBRARY),
                        help="folder of analysed sessions (one sub-folder with session.json each); "
                             "new analyses are saved here. Keep it outside the repository.")
    parser.add_argument("--weights", metavar="PATH", default=str(ROOT / "yolo11s-pose.pt"))
    parser.add_argument("--context-model", default=CONTEXT_MODEL)
    parser.add_argument("--context-provider", default=CONTEXT_PROVIDER)
    parser.add_argument("--key-file", metavar="PATH", default=str(ROOT / ".env"),
                        help="local file holding OPENROUTER_API_KEY (never printed)")
    parser.add_argument("--with-simulations", action="store_true",
                        help="also list the synthetic engineering scenarios (shell tests)")
    parser.add_argument("--replay-video", metavar="PATH",
                        help="engineering: local video for a file-as-live precomputed replay")
    parser.add_argument("--replay-observations", metavar="PATH",
                        help="matching precomputed observation JSON exported for that video")
    parser.add_argument("--replay-channel", metavar="PATH", action="append", default=[],
                        help="observation-channel document for the replayed video (repeatable)")
    args = parser.parse_args()
    if args.replay_channel and not args.replay_video:
        parser.error("--replay-channel needs --replay-video and --replay-observations")
    if bool(args.replay_video) != bool(args.replay_observations):
        parser.error("--replay-video and --replay-observations must be given together")
    try:
        import uvicorn
        from .analysis import AnalysisManager, Pipeline
        from .api import DEV_UI_ORIGINS, create_app
        from .library import SessionLibrary
        from .runtime import SessionManager
        from .scenarios import ReplayScenario
    except ImportError as exc:
        raise SystemExit("Live shell dependencies missing: pip install -r requirements-live.txt") from exc
    library_root = Path(args.library).resolve()
    if library_root.is_relative_to(ROOT):
        raise SystemExit("Keep the session library outside the repository (recordings are private).")
    try:
        library = SessionLibrary(library_root)
    except ValueError as exc:
        raise SystemExit(f"Session library not available: {exc}") from exc
    extra = ()
    if args.replay_video:
        try:
            extra = (ReplayScenario(args.replay_video, args.replay_observations,
                                    channels=args.replay_channel),)
        except (OSError, ValueError) as exc:
            raise SystemExit(f"Replay not available: {exc}") from exc
    pipeline = Pipeline(weights=args.weights, device=_device(), key_file=args.key_file,
                        context_model=args.context_model, context_provider=args.context_provider)
    app = create_app(SessionManager(extra_scenarios=extra, include_synthetic=args.with_simulations),
                     port=args.port, dev_origins=DEV_UI_ORIGINS if args.dev else (),
                     library=library, analyses=AnalysisManager(library, pipeline))
    print(f"ABA visual assistant: http://127.0.0.1:{args.port}", flush=True)
    print(f"Session library: {library_root}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
