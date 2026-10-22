"""CLI entrypoint: python -m support_portal --num-accounts 300

A plain `uvicorn main:app` can't take custom flags, so this wrapper sets
environment variables from CLI args before importing config/main -- the
pydantic-settings Settings() singleton reads the environment at import
time, so the override must happen first.
"""

import argparse
import os


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fake e-commerce support portal")
    parser.add_argument("--num-accounts", type=int, default=None, help="Size of the real check-in account pool")
    parser.add_argument("--port", type=int, default=None)
    generator_group = parser.add_mutually_exclusive_group()
    generator_group.add_argument("--enable-generator", dest="enable_generator", action="store_true", default=None)
    generator_group.add_argument("--disable-generator", dest="enable_generator", action="store_false")
    parser.add_argument("--generator-rate", type=float, default=None, help="Baseline synthetic tickets/sec")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.num_accounts is not None:
        os.environ["ACCOUNT_POOL_SIZE"] = str(args.num_accounts)
    if args.port is not None:
        os.environ["PORT"] = str(args.port)
    if args.enable_generator is not None:
        os.environ["ENABLE_GENERATOR"] = "true" if args.enable_generator else "false"
    if args.generator_rate is not None:
        os.environ["GENERATOR_RATE"] = str(args.generator_rate)

    import uvicorn

    from support_portal.config import settings

    uvicorn.run("support_portal.main:app", host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
