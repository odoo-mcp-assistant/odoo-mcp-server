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

---

## Project Structure

```
odoo-mcp-server/
├── server.py                  # MCP server — all tools defined here
├── main.py                    # Entrypoint used by the project script
├── pyproject.toml             # Project metadata and dependencies
└── .env                       # Environment variables (not committed)
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

| Tool |
|------|
| `get_product_by_name` |
| `get_product_by_type` |
| `add_product` |
| `update_product` |
| `archive_product` |
| `search_partners` |
| `get_partner_details` |
| `create_partner` |
| `get_sale_orders` |
| `get_sale_order_details` |
| `create_sale_order` |
| `confirm_sale_order` |
| `get_invoices` |
| `get_invoice_details` |
| `create_invoice` |
| `confirm_invoice` |
| `get_stock_quantities` |
| `get_warehouses` |
| `get_stock_picking` |
| `get_leads` |
| `create_lead` |
| `update_lead_stage` |
| `get_purchase_orders` |
| `create_purchase_order` |
| `confirm_purchase_order` |
| `get_employees` |
| `get_employee_details` |

---

## License

MIT
