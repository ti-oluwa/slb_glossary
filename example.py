import asyncio

import slb_glossary as slb
from slb_glossary import query


async def main() -> None:
    async with slb.local.database() as db, slb.session() as session:
        # Local first; only opens a live page if the local DB has nothing.
        # persist=True writes whatever came back live into `db`.
        async for result in query.search("water saturation", db=db, session=session, persist=True):
            print(result.term, "-", result.definition)

        # A repeat call for the same query is now served from `db` alone.
        async for result in query.search("water saturation", db=db, source=query.Source.LOCAL):
            print("(cached)", result.term)


asyncio.run(main())
