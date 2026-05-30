"""End-to-end smoke test: log in (headless) and call a couple of tools."""
import asyncio
import os

os.environ.setdefault("YONSEI_HEADED", "false")

from yonsei_portal_mcp.session import get_session
from yonsei_portal_mcp.scrapers import learnus


async def main() -> None:
    session = get_session()
    async with session.page() as page:
        courses = await learnus.fetch_courses(page)
        course_map = {c["id"]: c["name"] for c in courses if c.get("id")}
        deadlines = await learnus.fetch_deadlines(page, course_map=course_map)

    print(f"courses: {len(courses)}")
    for c in courses[:3]:
        print(f"  - {c['name']} | code={c['code']} | prof={c['professor']} | {c['progress_percent']}%")
    print(f"deadlines: {len(deadlines)}")
    for d in deadlines[:3]:
        print(f"  - {d['title']} | due={d['due']} | course={d['course']}")

    await session.close()


if __name__ == "__main__":
    asyncio.run(main())
