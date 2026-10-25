#!/usr/bin/env python3
"""Print a hello world message with a randomly funny extra line."""

from random import choice


FUNNY_EXTRAS = (
    "Today, even the semicolons are taking a vacation.",
    "A rubber duck somewhere just approved this message.",
    "The coffee compiled successfully.",
    "No bugs were harmed in the making of this greeting.",
    "The keyboard says hi, but only in lowercase.",
)


def build_message() -> str:
    """Return the hello world greeting plus one random funny extra."""
    return f"Hello, world! {choice(FUNNY_EXTRAS)}"


def main() -> None:
    print(build_message())


if __name__ == "__main__":
    main()
