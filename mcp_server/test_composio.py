import asyncio
from mcp_server.tools.composio_tool import handle   # adjust path if needed

async def test_connect():
    result = await handle(
        action="connect",
        app="GMAIL",
        user_id="test_user_123"
    )

    print("\n=== CONNECT RESULT ===")
    print(result)

if __name__ == "__main__":
    asyncio.run(test_connect())
