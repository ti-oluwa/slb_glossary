import asyncio

import slb_glossary as slb


async def main():
    policy = slb.RetryPolicy.exponential(base_delay=0.5, attempts=5, max_delay=5.0)
    async with (
        slb.search_session(
            retry=policy,
            headless=True,
            use_stealth=True,
            language=slb.Language.ENGLISH,
        ) as session,
        slb.local.local_db() as db,
    ):
        await slb.local.sync_all(db, session, concurrency=3)
        await slb.local.count(db)


if __name__ == "__main__":
    asyncio.run(main())
