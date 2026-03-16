import argparse
import sys

from config import VROLIKSTRAAT_CONFIG, with_target_coordinates
from feed import FeedPoller
from monitor import main


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the live Dutch train radar dashboard for a target latitude/longitude."
    )
    parser.add_argument("--lat", type=float, help="Override target latitude")
    parser.add_argument("--lon", type=float, help="Override target longitude")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    config = with_target_coordinates(
        VROLIKSTRAAT_CONFIG,
        target_lat=args.lat,
        target_lon=args.lon,
    )
    print(config)
    print("Loading static GTFS...")
    poller = FeedPoller(config)
    try:
        load_result = poller.load_static_gtfs()
        if load_result.error:
            print(load_result.error, file=sys.stderr)
            raise SystemExit(1)

        static_gtfs = load_result.data
        if static_gtfs is None:
            print("Static GTFS load failed for an unknown reason.", file=sys.stderr)
            raise SystemExit(1)

        print(
            "Loaded static GTFS: "
            f"routes={len(static_gtfs.routes)}, "
            f"trips={len(static_gtfs.trips)}, "
            f"stops={len(static_gtfs.stops)}, "
            f"target_windows={len(static_gtfs.target_windows)}"
        )
        print("Trips with shapes near target: " f"{len(static_gtfs.target_windows)}")
        print("Target stop pairs:")
        for stop_pair in static_gtfs.summarize_target_stop_pairs():
            print(f"  {stop_pair}")

        raise SystemExit(main(poller=poller, static_gtfs=static_gtfs, config=config))
    except KeyboardInterrupt:
        print("\nStopped.")
        raise SystemExit(0)
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    finally:
        poller.close()
