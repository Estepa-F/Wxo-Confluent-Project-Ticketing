"""MCP tools called by Confluent Cloud's Flink TRIAGEAGENT.

Built on the `mcp` Python SDK (installed version 2.2.0). Note: mcp 2.x
renamed FastMCP to MCPServer (mcp.server.mcpserver.MCPServer) with
otherwise-equivalent .tool()/.streamable_http_app() APIs -- confirmed by
inspecting the installed package, since 1.x-era `FastMCP` examples online
will raise ModuleNotFoundError on this version. Mounting the resulting
streamable-HTTP ASGI app onto an existing FastAPI app requires its
session manager's lifespan to be entered manually (see main.py) --
Starlette does not propagate a mounted sub-app's lifespan automatically.
"""

from mcp.server.mcpserver import MCPServer

from support_portal.accounts.pool import AccountPool
from support_portal.incidents.known_issues import search_known_issues as _search_known_issues
from support_portal.incidents.state import PortalState
from support_portal.config import settings


def build_mcp_server(account_pool: AccountPool, state: PortalState) -> MCPServer:
    mcp = MCPServer("support-portal")

    @mcp.tool()
    def search_known_issues(ticket_text: str, subject: str = "") -> dict:
        """Fuzzy-match ticket free text against the known-issues list.
        Pass the ticket's subject line too when available -- it often
        carries more of the actual topic than the body text alone."""
        query = f"{subject}. {ticket_text}" if subject else ticket_text
        return _search_known_issues(query, settings.match_threshold)

    @mcp.tool()
    def get_account_context(user_id: int, service_hint: str = "") -> dict:
        """Look up a fake account's tier, recent ticket history (capped at
        5), and whether it has a recurring issue on the given service.
        service_hint should be the `service` value returned by
        search_known_issues for the current ticket."""
        account = account_pool.get(user_id)
        if account is None:
            return {"found": False}
        recurring = bool(service_hint) and any(
            t["service"] == service_hint for t in account.ticket_history
        )
        return {
            "found": True,
            "tier": account.tier,
            "ticket_history": account.ticket_history[:5],
            "recurring_issue_same_service": recurring,
        }

    return mcp
