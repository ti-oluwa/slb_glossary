import asyncio

import slb_glossary as slb


async def main():
    policy = slb.BackoffPolicy.exponential(base_delay=0.5, attempts=5, max_delay=8.0)
    async with slb.search_session(
        backoff=policy,
        headless=True,
        use_stealth=True,
        language=slb.Language.SPANISH,
    ) as session:
        await slb.print_results_async(slb.search(session, "autotracking", limit=5))


if __name__ == "__main__":
    asyncio.run(main())
