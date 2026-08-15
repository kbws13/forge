from mcp.server.fastmcp import FastMCP

server = FastMCP("test-tools")


@server.tool()
def add(left: int, right: int) -> int:
    """Add two integers."""
    return left + right


if __name__ == "__main__":
    server.run(transport="stdio")
