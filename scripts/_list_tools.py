import asyncio

from yonsei_portal_mcp.server import mcp


async def main() -> None:
    tools = await mcp.list_tools()
    print("TOOLS:", [t.name for t in tools])


if __name__ == "__main__":
    asyncio.run(main())
