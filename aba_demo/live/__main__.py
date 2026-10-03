"""Run the simulated live-session shell on loopback: python -m aba_demo.live"""
import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="ABA live-session shell (SIMULATION ONLY)")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--dev", action="store_true",
                        help="also accept requests from the Vite dev server on port 5173")
    parser.add_argument("--replay-video", metavar="PATH",
                        help="local video for a file-as-live precomputed replay (never uploaded)")
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
        from .api import DEV_UI_ORIGINS, create_app
        from .runtime import SessionManager
        from .scenarios import ReplayScenario
    except ImportError as exc:
        raise SystemExit("Live shell dependencies missing: pip install -r requirements-live.txt") from exc
    extra = ()
    if args.replay_video:
        try:
            extra = (ReplayScenario(args.replay_video, args.replay_observations,
                                    channels=args.replay_channel),)
        except (OSError, ValueError) as exc:
            raise SystemExit(f"Replay not available: {exc}") from exc
    app = create_app(SessionManager(extra_scenarios=extra), port=args.port,
                     dev_origins=DEV_UI_ORIGINS if args.dev else ())
    print(f"ABA live-session shell (simulation): http://127.0.0.1:{args.port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
