import asyncio

import slb_glossary as slb


async def main():
    policy = slb.RetryPolicy.exponential(base_delay=0.5, attempts=5, max_delay=8.0)
    async with slb.search_session(
        retry=policy,
        headless=False,
        use_stealth=True,
        language=slb.Language.ENGLISH,
    ) as session:
        await slb.print_results_async(slb.search(session, "borehole,bha", limit=5))


if __name__ == "__main__":
    asyncio.run(main())
