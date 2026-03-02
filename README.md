# odoo-mcp-server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that exposes Odoo business data and operations as tools that can be invoked by any MCP-compatible AI client (Claude Desktop, Cursor, etc.).

---

## Features

- **Products** — search by name or type, create, update, archive
- **Partners** — search customers/suppliers, get details, create
- **Sale Orders** — list, get details, create, confirm
- **Invoices** — list, get details, create, post
- **Inventory** — stock quantities, warehouses, stock pickings
- **CRM** — list leads/opportunities, create, move stage
- **Purchases** — list purchase orders, create, confirm
- **HR** — search employees, get details
- **Permission layer** — each tool is individually controlled (`allow` / `ask` / `deny`) via `data/server_permissions.json`
- **Audit log** — every tool call is logged to `data/server_audit.log`

---

## Project Structure

```
odoo-mcp-server/
├── server.py                  # MCP server — all tools defined here
├── main.py                    # Entrypoint used by the project script
├── pyproject.toml             # Project metadata and dependencies
├── .env                       # Environment variables (not committed)
└── data/
    ├── server_permissions.json  # Per-tool permission config (auto-created)
    └── server_audit.log         # Append-only audit trail
```

---

## Requirements

- Python 3.10+
- A running Odoo instance (v15, v16, or v17 recommended)
- [`uv`](https://github.com/astral-sh/uv) (recommended) **or** `pip`

---

## Installation

```bash
git clone https://github.com/MohamedDridii/odoo-mcp-server.git
cd odoo-mcp-server

# with uv (recommended)
uv sync

# or with pip
pip install -e .
```

---

## Configuration

Create a `.env` file at the project root:

```env
ODOO_HOST=localhost
ODOO_PORT=8069
ODOO_DB=your_database
ODOO_USER=admin
ODOO_PASSWORD=admin

# Optional — MCP server bind address
MCP_SERVER_HOST=0.0.0.0
MCP_SERVER_PORT=8001
```

---

## Running the Server

```bash
# with uv
uv run server.py

# or directly
python server.py

# or via the installed script
odoo-mcp-server
```

The server starts a **Streamable HTTP** MCP endpoint at `http://0.0.0.0:8001`.

---

## Permissions

On first run, `data/server_permissions.json` is created automatically with sensible defaults:

| Value | Behaviour |
|-------|-----------|
| `"allow"` | Tool executes immediately |
| `"ask"` | Tool executes but the client is advised to confirm first |
| `"deny"` | Tool is blocked and returns an error |

Edit the file at any time — changes take effect on the next server restart.

Example:

```json
{
  "add_product": "ask",
  "confirm_sale_order": "deny",
  "get_employees": "allow"
}
```

---

## Audit Log

Every tool invocation (allowed, denied, or error) is appended to `data/server_audit.log`:

```
2026-03-02T14:32:01.123456 | get_product_by_name | ALLOWED
2026-03-02T14:32:05.654321 | confirm_sale_order  | DENIED
```

---

## Connecting an MCP Client

### Claude Desktop

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "odoo": {
      "url": "http://localhost:8001/mcp"
    }
  }
}
```

### Cursor / other clients

Use the server URL `http://localhost:8001/mcp` in your client's MCP configuration.

---

## Available Tools

| Tool | Permission default |
|------|--------------------|
| `get_product_by_name` | allow |
| `get_product_by_type` | allow |
| `add_product` | ask |
| `update_product` | ask |
| `archive_product` | ask |
| `search_partners` | allow |
| `get_partner_details` | allow |
| `create_partner` | ask |
| `get_sale_orders` | allow |
| `get_sale_order_details` | allow |
| `create_sale_order` | ask |
| `confirm_sale_order` | ask |
| `get_invoices` | allow |
| `get_invoice_details` | allow |
| `create_invoice` | ask |
| `confirm_invoice` | ask |
| `get_stock_quantities` | allow |
| `get_warehouses` | allow |
| `get_stock_picking` | allow |
| `get_leads` | allow |
| `create_lead` | ask |
| `update_lead_stage` | ask |
| `get_purchase_orders` | allow |
| `create_purchase_order` | ask |
| `confirm_purchase_order` | ask |
| `get_employees` | allow |
| `get_employee_details` | allow |

---

## License

MIT
