import argparse
import sys

from src.config import DEFAULT_CONFIG, with_target_coordinates
from src.feed import FeedPoller
from src.monitor import main


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the live Dutch train radar dashboard for a target latitude/longitude."
    )
    parser.add_argument("--lat", type=float, help="Override target latitude")
    parser.add_argument("--lon", type=float, help="Override target longitude")
    return parser.parse_args()


def cli() -> int:
    args = parse_args()
    config = with_target_coordinates(
        DEFAULT_CONFIG,
        target_lat=args.lat,
        target_lon=args.lon,
    )
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
            return 1

        return main(poller=poller, static_gtfs=static_gtfs, config=config)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1
    finally:
        poller.close()


if __name__ == "__main__":
    raise SystemExit(cli())
