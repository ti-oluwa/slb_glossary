"""Small, dependency-free helpers shared across the package."""

import asyncio
import typing

T = typing.TypeVar("T")


__all__ = ["parse_int", "retry_async"]


def parse_int(text: str) -> int:
    """
    Parse an integer out of glossary page text such as `"1,204"` or `" 42 "`.

    :param text: The text to parse.
    :return: The parsed integer.
    :raises ValueError: If `text` does not contain a valid integer once
        commas and surrounding whitespace are stripped.
    """
    return int(text.replace(",", "").replace(" ", ""))


async def retry_async(
    func: typing.Callable[[], typing.Awaitable[typing.Optional[T]]],
    *,
    attempts: int = 3,
    delay: float = 0.8,
) -> typing.Optional[T]:
    """
    Call `func` repeatedly until it returns a truthy value or attempts run out.

    Useful for glossary pages that briefly render empty content while their
    JavaScript search widget finishes loading.

    :param func: A zero-argument async callable to retry.
    :param attempts: Maximum number of times to call `func`.
    :param delay: Seconds to wait between attempts.
    :return: The first truthy result of `func`, or its last (falsy) result
        once `attempts` is exhausted.
    """
    result = None
    for attempt in range(attempts):
        result = await func()
        if result:
            return result
        if attempt < attempts - 1:
            await asyncio.sleep(delay)
    return result
