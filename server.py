import os
import json
from pathlib import Path
from datetime import datetime

import uvicorn
import odoorpc
from dotenv import load_dotenv

from mcp.server.fastmcp import FastMCP

# Load environment variables from .env file at project root
load_dotenv(Path(__file__).resolve().parent / ".env")


# ============================================================
# Configuration
# ============================================================

BASE_DIR = Path(__file__).parent / "data"
BASE_DIR.mkdir(exist_ok=True)

PERMISSIONS_FILE = BASE_DIR / "server_permissions.json"
AUDIT_FILE = BASE_DIR / "server_audit.log"

ODOO_HOST = os.getenv("ODOO_HOST", "localhost")
ODOO_PORT = int(os.getenv("ODOO_PORT", "8069"))
ODOO_DB = os.getenv("ODOO_DB", "app_one")
ODOO_USER = os.getenv("ODOO_USER", "admin")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "admin")


# ============================================================
# Permission Layer
# ============================================================

def load_permissions():
    if PERMISSIONS_FILE.exists():
        return json.loads(PERMISSIONS_FILE.read_text())

    default = {
        "get_product_by_name": "allow",
        "get_product_by_type": "allow",
        "add_product": "ask",
        "update_product": "ask",
        "archive_product": "ask",
        "search_partners": "allow",
        "get_partner_details": "allow",
        "create_partner": "ask",
        "get_sale_orders": "allow",
        "get_sale_order_details": "allow",
        "create_sale_order": "ask",
        "confirm_sale_order": "ask",
        "get_invoices": "allow",
        "get_invoice_details": "allow",
        "create_invoice": "ask",
        "confirm_invoice": "ask",
        "get_stock_quantities": "allow",
        "get_warehouses": "allow",
        "get_stock_picking": "allow",
        "get_leads": "allow",
        "create_lead": "ask",
        "update_lead_stage": "ask",
        "get_purchase_orders": "allow",
        "create_purchase_order": "ask",
        "confirm_purchase_order": "ask",
        "get_employees": "allow",
        "get_employee_details": "allow",
    }

    PERMISSIONS_FILE.write_text(json.dumps(default, indent=2))
    return default


SERVER_PERMISSIONS = load_permissions()


def check_permission(tool_name: str):
    return SERVER_PERMISSIONS.get(tool_name, "allow")


def log_audit(tool: str, decision: str):
    entry = f"{datetime.now().isoformat()} | {tool} | {decision}\n"
    with open(AUDIT_FILE, "a") as f:
        f.write(entry)


# ============================================================
# Odoo Connection
# ============================================================

odoo = odoorpc.ODOO(ODOO_HOST, port=ODOO_PORT)
odoo.login(ODOO_DB, ODOO_USER, ODOO_PASSWORD)


# ============================================================
# MCP Server
# ============================================================

mcp = FastMCP("odoo-mcp-server")


# ============================================================
# Secure Tools
# ============================================================

@mcp.tool()
def get_product_by_name(name: str) -> list:
    """
    Get products by name (case-insensitive search).
    """

    if check_permission("get_product_by_name") != "allow":
        log_audit("get_product_by_name", "DENIED")
        return {"error": "Permission denied by server policy"}

    log_audit("get_product_by_name", "ALLOWED")

    products = odoo.env["product.product"].search_read(
        [("name", "ilike", name)],
        ["name", "list_price", "categ_id"]
    )

    return products


@mcp.tool()
def get_product_by_type(product_type: str) -> list:
    """
    Get products by type: product, consu, or service.
    """

    if check_permission("get_product_by_type") != "allow":
        log_audit("get_product_by_type", "DENIED")
        return {"error": "Permission denied by server policy"}

    log_audit("get_product_by_type", "ALLOWED")

    products = odoo.env["product.product"].search_read(
        [("detailed_type", "=", product_type)],
        ["name", "list_price", "detailed_type"]
    )

    return products


@mcp.tool()
def add_product(name: str, price: float, product_type: str = "consu") -> dict:
    """
    Add a new product to the Odoo database.
    Requires permission before execution.

    Args:
        name: The name of the product.
        price: The list/sale price of the product.
        product_type: The type of product — 'consu' (consumable), 'service', or 'product' (storable). Defaults to 'consu'.
    """

    permission = check_permission("add_product")

    if permission == "deny":
        log_audit("add_product", "DENIED")
        return {"error": "Permission denied by server policy"}

    if permission == "ask":
        log_audit("add_product", "ASK — deferred to client")

    log_audit("add_product", "ALLOWED")

    try:
        product_id = odoo.env["product.product"].create({
            "name": name,
            "list_price": price,
            "type": product_type,
        })

        return {
            "success": True,
            "product_id": product_id,
            "name": name,
            "price": price,
            "type": product_type,
        }
    except Exception as e:
        log_audit("add_product", f"ERROR: {e}")
        return {"error": str(e)}


@mcp.tool()
def update_product(product_id: int, name: str = None, price: float = None, product_type: str = None) -> dict:
    """
    Update an existing product in Odoo.

    Args:
        product_id: The ID of the product to update.
        name: New name for the product (optional).
        price: New list/sale price (optional).
        product_type: New product type — 'consu', 'service', or 'product' (optional).
    """

    permission = check_permission("update_product")

    if permission == "deny":
        log_audit("update_product", "DENIED")
        return {"error": "Permission denied by server policy"}

    if permission == "ask":
        log_audit("update_product", "ASK — deferred to client")

    log_audit("update_product", "ALLOWED")

    try:
        vals = {}
        if name is not None:
            vals["name"] = name
        if price is not None:
            vals["list_price"] = price
        if product_type is not None:
            vals["type"] = product_type

        if not vals:
            return {"error": "No fields to update"}

        odoo.env["product.product"].write(product_id, vals)

        return {"success": True, "product_id": product_id, "updated_fields": list(vals.keys())}
    except Exception as e:
        log_audit("update_product", f"ERROR: {e}")
        return {"error": str(e)}


@mcp.tool()
def archive_product(product_id: int, archive: bool = True) -> dict:
    """
    Archive or unarchive a product in Odoo.

    Args:
        product_id: The ID of the product.
        archive: True to archive (deactivate), False to unarchive (reactivate). Defaults to True.
    """

    permission = check_permission("archive_product")

    if permission == "deny":
        log_audit("archive_product", "DENIED")
        return {"error": "Permission denied by server policy"}

    if permission == "ask":
        log_audit("archive_product", "ASK — deferred to client")

    log_audit("archive_product", "ALLOWED")

    try:
        odoo.env["product.product"].write(product_id, {"active": not archive})
        action = "archived" if archive else "unarchived"
        return {"success": True, "product_id": product_id, "action": action}
    except Exception as e:
        log_audit("archive_product", f"ERROR: {e}")
        return {"error": str(e)}


# ============================================================
# Partner / Customer Tools
# ============================================================

@mcp.tool()
def search_partners(name: str = None, is_customer: bool = None, is_supplier: bool = None, limit: int = 20) -> list:
    """
    Search partners (customers/suppliers) in Odoo.

    Args:
        name: Search partners by name (case-insensitive, optional).
        is_customer: Filter by customer flag (optional).
        is_supplier: Filter by supplier flag (optional).
        limit: Maximum number of results to return. Defaults to 20.
    """

    if check_permission("search_partners") != "allow":
        log_audit("search_partners", "DENIED")
        return {"error": "Permission denied by server policy"}

    log_audit("search_partners", "ALLOWED")

    domain = []
    if name:
        domain.append(("name", "ilike", name))
    if is_customer is not None:
        domain.append(("customer_rank", ">", 0) if is_customer else ("customer_rank", "=", 0))
    if is_supplier is not None:
        domain.append(("supplier_rank", ">", 0) if is_supplier else ("supplier_rank", "=", 0))

    partners = odoo.env["res.partner"].search_read(
        domain,
        ["name", "email", "phone", "city", "country_id", "customer_rank", "supplier_rank"],
        limit=limit,
    )
    return partners


@mcp.tool()
def get_partner_details(partner_id: int) -> dict:
    """
    Get detailed information about a specific partner.

    Args:
        partner_id: The ID of the partner to retrieve.
    """

    if check_permission("get_partner_details") != "allow":
        log_audit("get_partner_details", "DENIED")
        return {"error": "Permission denied by server policy"}

    log_audit("get_partner_details", "ALLOWED")

    try:
        partners = odoo.env["res.partner"].search_read(
            [("id", "=", partner_id)],
            [
                "name", "email", "phone", "mobile", "street", "street2",
                "city", "zip", "country_id", "state_id", "vat",
                "website", "customer_rank", "supplier_rank",
                "credit_limit", "total_invoiced",
            ],
        )
        if not partners:
            return {"error": f"Partner with ID {partner_id} not found"}
        return partners[0]
    except Exception as e:
        log_audit("get_partner_details", f"ERROR: {e}")
        return {"error": str(e)}


@mcp.tool()
def create_partner(
    name: str,
    email: str = None,
    phone: str = None,
    is_company: bool = False,
    street: str = None,
    city: str = None,
    zip_code: str = None,
    country_code: str = None,
) -> dict:
    """
    Create a new partner (customer/supplier) in Odoo.

    Args:
        name: Partner name.
        email: Email address (optional).
        phone: Phone number (optional).
        is_company: True if company, False if individual. Defaults to False.
        street: Street address (optional).
        city: City (optional).
        zip_code: ZIP / postal code (optional).
        country_code: Two-letter country code, e.g. 'US', 'FR' (optional).
    """

    permission = check_permission("create_partner")

    if permission == "deny":
        log_audit("create_partner", "DENIED")
        return {"error": "Permission denied by server policy"}

    if permission == "ask":
        log_audit("create_partner", "ASK — deferred to client")

    log_audit("create_partner", "ALLOWED")

    try:
        vals = {"name": name, "is_company": is_company}
        if email:
            vals["email"] = email
        if phone:
            vals["phone"] = phone
        if street:
            vals["street"] = street
        if city:
            vals["city"] = city
        if zip_code:
            vals["zip"] = zip_code
        if country_code:
            countries = odoo.env["res.country"].search_read(
                [("code", "=", country_code.upper())], ["id"], limit=1
            )
            if countries:
                vals["country_id"] = countries[0]["id"]

        partner_id = odoo.env["res.partner"].create(vals)
        return {"success": True, "partner_id": partner_id, "name": name}
    except Exception as e:
        log_audit("create_partner", f"ERROR: {e}")
        return {"error": str(e)}


# ============================================================
# Sale Order Tools
# ============================================================

@mcp.tool()
def get_sale_orders(state: str = None, partner_name: str = None, limit: int = 20) -> list:
    """
    List sale orders from Odoo.

    Args:
        state: Filter by state — 'draft' (quotation), 'sale' (confirmed), 'done', 'cancel' (optional).
        partner_name: Filter by customer name (case-insensitive, optional).
        limit: Maximum number of results. Defaults to 20.
    """

    if check_permission("get_sale_orders") != "allow":
        log_audit("get_sale_orders", "DENIED")
        return {"error": "Permission denied by server policy"}

    log_audit("get_sale_orders", "ALLOWED")

    domain = []
    if state:
        domain.append(("state", "=", state))
    if partner_name:
        domain.append(("partner_id.name", "ilike", partner_name))

    orders = odoo.env["sale.order"].search_read(
        domain,
        ["name", "partner_id", "date_order", "state", "amount_total", "currency_id"],
        limit=limit,
        order="date_order desc",
    )
    return orders


@mcp.tool()
def get_sale_order_details(order_id: int) -> dict:
    """
    Get full details of a specific sale order including its lines.

    Args:
        order_id: The ID of the sale order.
    """

    if check_permission("get_sale_order_details") != "allow":
        log_audit("get_sale_order_details", "DENIED")
        return {"error": "Permission denied by server policy"}

    log_audit("get_sale_order_details", "ALLOWED")

    try:
        orders = odoo.env["sale.order"].search_read(
            [("id", "=", order_id)],
            [
                "name", "partner_id", "date_order", "state",
                "amount_untaxed", "amount_tax", "amount_total",
                "currency_id", "note", "order_line",
            ],
        )
        if not orders:
            return {"error": f"Sale order with ID {order_id} not found"}

        order = orders[0]
        line_ids = order.pop("order_line", [])

        if line_ids:
            lines = odoo.env["sale.order.line"].search_read(
                [("id", "in", line_ids)],
                ["product_id", "name", "product_uom_qty", "price_unit", "price_subtotal"],
            )
            order["lines"] = lines
        else:
            order["lines"] = []

        return order
    except Exception as e:
        log_audit("get_sale_order_details", f"ERROR: {e}")
        return {"error": str(e)}


@mcp.tool()
def create_sale_order(partner_id: int, order_lines: list) -> dict:
    """
    Create a new sale order (quotation) in Odoo.

    Args:
        partner_id: The ID of the customer.
        order_lines: A list of order line dicts, each with 'product_id' (int), 'quantity' (float), and optional 'price_unit' (float).
    """

    permission = check_permission("create_sale_order")

    if permission == "deny":
        log_audit("create_sale_order", "DENIED")
        return {"error": "Permission denied by server policy"}

    if permission == "ask":
        log_audit("create_sale_order", "ASK — deferred to client")

    log_audit("create_sale_order", "ALLOWED")

    try:
        lines = []
        for line in order_lines:
            vals = {
                "product_id": line["product_id"],
                "product_uom_qty": line.get("quantity", 1),
            }
            if "price_unit" in line:
                vals["price_unit"] = line["price_unit"]
            lines.append((0, 0, vals))

        order_id = odoo.env["sale.order"].create({
            "partner_id": partner_id,
            "order_line": lines,
        })

        order = odoo.env["sale.order"].search_read(
            [("id", "=", order_id)], ["name", "amount_total", "state"]
        )
        return {"success": True, "order_id": order_id, **order[0]}
    except Exception as e:
        log_audit("create_sale_order", f"ERROR: {e}")
        return {"error": str(e)}


@mcp.tool()
def confirm_sale_order(order_id: int) -> dict:
    """
    Confirm a draft quotation into a sale order.

    Args:
        order_id: The ID of the sale order to confirm.
    """

    permission = check_permission("confirm_sale_order")

    if permission == "deny":
        log_audit("confirm_sale_order", "DENIED")
        return {"error": "Permission denied by server policy"}

    if permission == "ask":
        log_audit("confirm_sale_order", "ASK — deferred to client")

    log_audit("confirm_sale_order", "ALLOWED")

    try:
        odoo.env["sale.order"].action_confirm([order_id])
        order = odoo.env["sale.order"].search_read(
            [("id", "=", order_id)], ["name", "state"]
        )
        return {"success": True, "order_id": order_id, **order[0]}
    except Exception as e:
        log_audit("confirm_sale_order", f"ERROR: {e}")
        return {"error": str(e)}


# ============================================================
# Invoice / Accounting Tools
# ============================================================

@mcp.tool()
def get_invoices(state: str = None, partner_name: str = None, move_type: str = "out_invoice", limit: int = 20) -> list:
    """
    List invoices (or bills) from Odoo.

    Args:
        state: Filter by state — 'draft', 'posted', 'cancel' (optional).
        partner_name: Filter by partner name (optional).
        move_type: Type of accounting entry — 'out_invoice' (customer invoice), 'in_invoice' (vendor bill), 'out_refund' (credit note), 'in_refund' (debit note). Defaults to 'out_invoice'.
        limit: Maximum number of results. Defaults to 20.
    """

    if check_permission("get_invoices") != "allow":
        log_audit("get_invoices", "DENIED")
        return {"error": "Permission denied by server policy"}

    log_audit("get_invoices", "ALLOWED")

    domain = [("move_type", "=", move_type)]
    if state:
        domain.append(("state", "=", state))
    if partner_name:
        domain.append(("partner_id.name", "ilike", partner_name))

    invoices = odoo.env["account.move"].search_read(
        domain,
        ["name", "partner_id", "invoice_date", "state", "amount_total", "amount_residual", "currency_id"],
        limit=limit,
        order="invoice_date desc",
    )
    return invoices


@mcp.tool()
def get_invoice_details(invoice_id: int) -> dict:
    """
    Get full details of an invoice including its lines.

    Args:
        invoice_id: The ID of the invoice.
    """

    if check_permission("get_invoice_details") != "allow":
        log_audit("get_invoice_details", "DENIED")
        return {"error": "Permission denied by server policy"}

    log_audit("get_invoice_details", "ALLOWED")

    try:
        invoices = odoo.env["account.move"].search_read(
            [("id", "=", invoice_id)],
            [
                "name", "partner_id", "invoice_date", "invoice_date_due",
                "state", "move_type", "amount_untaxed", "amount_tax",
                "amount_total", "amount_residual", "currency_id", "invoice_line_ids",
            ],
        )
        if not invoices:
            return {"error": f"Invoice with ID {invoice_id} not found"}

        invoice = invoices[0]
        line_ids = invoice.pop("invoice_line_ids", [])

        if line_ids:
            lines = odoo.env["account.move.line"].search_read(
                [("id", "in", line_ids), ("display_type", "=", "product")],
                ["product_id", "name", "quantity", "price_unit", "price_subtotal"],
            )
            invoice["lines"] = lines
        else:
            invoice["lines"] = []

        return invoice
    except Exception as e:
        log_audit("get_invoice_details", f"ERROR: {e}")
        return {"error": str(e)}


@mcp.tool()
def create_invoice(partner_id: int, invoice_lines: list, move_type: str = "out_invoice") -> dict:
    """
    Create a draft invoice in Odoo.

    Args:
        partner_id: The ID of the partner (customer/supplier).
        invoice_lines: A list of line dicts, each with 'product_id' (int), 'quantity' (float), and optional 'price_unit' (float).
        move_type: Invoice type — 'out_invoice' (customer invoice), 'in_invoice' (vendor bill). Defaults to 'out_invoice'.
    """

    permission = check_permission("create_invoice")

    if permission == "deny":
        log_audit("create_invoice", "DENIED")
        return {"error": "Permission denied by server policy"}

    if permission == "ask":
        log_audit("create_invoice", "ASK — deferred to client")

    log_audit("create_invoice", "ALLOWED")

    try:
        lines = []
        for line in invoice_lines:
            vals = {
                "product_id": line["product_id"],
                "quantity": line.get("quantity", 1),
            }
            if "price_unit" in line:
                vals["price_unit"] = line["price_unit"]
            lines.append((0, 0, vals))

        invoice_id = odoo.env["account.move"].create({
            "partner_id": partner_id,
            "move_type": move_type,
            "invoice_line_ids": lines,
        })

        inv = odoo.env["account.move"].search_read(
            [("id", "=", invoice_id)], ["name", "amount_total", "state"]
        )
        return {"success": True, "invoice_id": invoice_id, **inv[0]}
    except Exception as e:
        log_audit("create_invoice", f"ERROR: {e}")
        return {"error": str(e)}


@mcp.tool()
def confirm_invoice(invoice_id: int) -> dict:
    """
    Post (confirm) a draft invoice so it gets a number and becomes payable.

    Args:
        invoice_id: The ID of the draft invoice to confirm.
    """

    permission = check_permission("confirm_invoice")

    if permission == "deny":
        log_audit("confirm_invoice", "DENIED")
        return {"error": "Permission denied by server policy"}

    if permission == "ask":
        log_audit("confirm_invoice", "ASK — deferred to client")

    log_audit("confirm_invoice", "ALLOWED")

    try:
        odoo.env["account.move"].action_post([invoice_id])
        inv = odoo.env["account.move"].search_read(
            [("id", "=", invoice_id)], ["name", "state"]
        )
        return {"success": True, "invoice_id": invoice_id, **inv[0]}
    except Exception as e:
        log_audit("confirm_invoice", f"ERROR: {e}")
        return {"error": str(e)}


# ============================================================
# Inventory / Stock Tools
# ============================================================

@mcp.tool()
def get_stock_quantities(product_name: str = None, warehouse_name: str = None, limit: int = 50) -> list:
    """
    Get current stock quantities for products.

    Args:
        product_name: Filter by product name (case-insensitive, optional).
        warehouse_name: Filter by warehouse name (optional).
        limit: Maximum number of results. Defaults to 50.
    """

    if check_permission("get_stock_quantities") != "allow":
        log_audit("get_stock_quantities", "DENIED")
        return {"error": "Permission denied by server policy"}

    log_audit("get_stock_quantities", "ALLOWED")

    domain = [("location_id.usage", "=", "internal")]
    if product_name:
        domain.append(("product_id.name", "ilike", product_name))
    if warehouse_name:
        domain.append(("location_id.warehouse_id.name", "ilike", warehouse_name))

    quants = odoo.env["stock.quant"].search_read(
        domain,
        ["product_id", "location_id", "quantity", "reserved_quantity"],
        limit=limit,
    )
    return quants


@mcp.tool()
def get_warehouses() -> list:
    """
    List all warehouses configured in Odoo.
    """

    if check_permission("get_warehouses") != "allow":
        log_audit("get_warehouses", "DENIED")
        return {"error": "Permission denied by server policy"}

    log_audit("get_warehouses", "ALLOWED")

    warehouses = odoo.env["stock.warehouse"].search_read(
        [],
        ["name", "code", "partner_id", "lot_stock_id"],
    )
    return warehouses


@mcp.tool()
def get_stock_picking(state: str = None, picking_type: str = None, limit: int = 20) -> list:
    """
    List stock picking (transfers) from Odoo.

    Args:
        state: Filter by state — 'draft', 'waiting', 'confirmed', 'assigned', 'done', 'cancel' (optional).
        picking_type: Filter by operation type name, e.g. 'Delivery Orders', 'Receipts' (optional).
        limit: Maximum number of results. Defaults to 20.
    """

    if check_permission("get_stock_picking") != "allow":
        log_audit("get_stock_picking", "DENIED")
        return {"error": "Permission denied by server policy"}

    log_audit("get_stock_picking", "ALLOWED")

    domain = []
    if state:
        domain.append(("state", "=", state))
    if picking_type:
        domain.append(("picking_type_id.name", "ilike", picking_type))

    pickings = odoo.env["stock.picking"].search_read(
        domain,
        ["name", "partner_id", "picking_type_id", "state", "scheduled_date", "origin"],
        limit=limit,
        order="scheduled_date desc",
    )
    return pickings


# ============================================================
# CRM Lead / Opportunity Tools
# ============================================================

@mcp.tool()
def get_leads(stage_name: str = None, partner_name: str = None, lead_type: str = None, limit: int = 20) -> list:
    """
    Search CRM leads and opportunities.

    Args:
        stage_name: Filter by stage name, e.g. 'New', 'Qualified' (optional).
        partner_name: Filter by customer name (optional).
        lead_type: Filter by type — 'lead' or 'opportunity' (optional).
        limit: Maximum number of results. Defaults to 20.
    """

    if check_permission("get_leads") != "allow":
        log_audit("get_leads", "DENIED")
        return {"error": "Permission denied by server policy"}

    log_audit("get_leads", "ALLOWED")

    domain = []
    if stage_name:
        domain.append(("stage_id.name", "ilike", stage_name))
    if partner_name:
        domain.append(("partner_id.name", "ilike", partner_name))
    if lead_type:
        domain.append(("type", "=", lead_type))

    leads = odoo.env["crm.lead"].search_read(
        domain,
        [
            "name", "partner_id", "email_from", "phone",
            "stage_id", "type", "expected_revenue", "probability",
            "user_id", "create_date",
        ],
        limit=limit,
        order="create_date desc",
    )
    return leads


@mcp.tool()
def create_lead(
    name: str,
    partner_name: str = None,
    email: str = None,
    phone: str = None,
    expected_revenue: float = 0.0,
    lead_type: str = "opportunity",
) -> dict:
    """
    Create a new CRM lead or opportunity.

    Args:
        name: Title/name of the lead.
        partner_name: Customer or contact name (optional).
        email: Contact email (optional).
        phone: Contact phone (optional).
        expected_revenue: Expected revenue amount. Defaults to 0.
        lead_type: 'lead' or 'opportunity'. Defaults to 'opportunity'.
    """

    permission = check_permission("create_lead")

    if permission == "deny":
        log_audit("create_lead", "DENIED")
        return {"error": "Permission denied by server policy"}

    if permission == "ask":
        log_audit("create_lead", "ASK — deferred to client")

    log_audit("create_lead", "ALLOWED")

    try:
        vals = {
            "name": name,
            "type": lead_type,
            "expected_revenue": expected_revenue,
        }
        if partner_name:
            vals["partner_name"] = partner_name
        if email:
            vals["email_from"] = email
        if phone:
            vals["phone"] = phone

        lead_id = odoo.env["crm.lead"].create(vals)
        return {"success": True, "lead_id": lead_id, "name": name, "type": lead_type}
    except Exception as e:
        log_audit("create_lead", f"ERROR: {e}")
        return {"error": str(e)}


@mcp.tool()
def update_lead_stage(lead_id: int, stage_name: str) -> dict:
    """
    Move a CRM lead/opportunity to a different stage.

    Args:
        lead_id: The ID of the lead to update.
        stage_name: The name of the target stage, e.g. 'Qualified', 'Proposition', 'Won'.
    """

    permission = check_permission("update_lead_stage")

    if permission == "deny":
        log_audit("update_lead_stage", "DENIED")
        return {"error": "Permission denied by server policy"}

    if permission == "ask":
        log_audit("update_lead_stage", "ASK — deferred to client")

    log_audit("update_lead_stage", "ALLOWED")

    try:
        stages = odoo.env["crm.stage"].search_read(
            [("name", "ilike", stage_name)], ["id", "name"], limit=1
        )
        if not stages:
            return {"error": f"Stage '{stage_name}' not found"}

        odoo.env["crm.lead"].write(lead_id, {"stage_id": stages[0]["id"]})
        return {"success": True, "lead_id": lead_id, "new_stage": stages[0]["name"]}
    except Exception as e:
        log_audit("update_lead_stage", f"ERROR: {e}")
        return {"error": str(e)}


# ============================================================
# Purchase Order Tools
# ============================================================

@mcp.tool()
def get_purchase_orders(state: str = None, partner_name: str = None, limit: int = 20) -> list:
    """
    List purchase orders from Odoo.

    Args:
        state: Filter by state — 'draft' (RFQ), 'sent', 'purchase' (confirmed), 'done', 'cancel' (optional).
        partner_name: Filter by supplier name (optional).
        limit: Maximum number of results. Defaults to 20.
    """

    if check_permission("get_purchase_orders") != "allow":
        log_audit("get_purchase_orders", "DENIED")
        return {"error": "Permission denied by server policy"}

    log_audit("get_purchase_orders", "ALLOWED")

    domain = []
    if state:
        domain.append(("state", "=", state))
    if partner_name:
        domain.append(("partner_id.name", "ilike", partner_name))

    orders = odoo.env["purchase.order"].search_read(
        domain,
        ["name", "partner_id", "date_order", "state", "amount_total", "currency_id"],
        limit=limit,
        order="date_order desc",
    )
    return orders


@mcp.tool()
def create_purchase_order(partner_id: int, order_lines: list) -> dict:
    """
    Create a new purchase order (RFQ) in Odoo.

    Args:
        partner_id: The ID of the supplier.
        order_lines: A list of line dicts, each with 'product_id' (int), 'quantity' (float), and optional 'price_unit' (float).
    """

    permission = check_permission("create_purchase_order")

    if permission == "deny":
        log_audit("create_purchase_order", "DENIED")
        return {"error": "Permission denied by server policy"}

    if permission == "ask":
        log_audit("create_purchase_order", "ASK — deferred to client")

    log_audit("create_purchase_order", "ALLOWED")

    try:
        lines = []
        for line in order_lines:
            vals = {
                "product_id": line["product_id"],
                "product_qty": line.get("quantity", 1),
            }
            if "price_unit" in line:
                vals["price_unit"] = line["price_unit"]
            lines.append((0, 0, vals))

        po_id = odoo.env["purchase.order"].create({
            "partner_id": partner_id,
            "order_line": lines,
        })

        po = odoo.env["purchase.order"].search_read(
            [("id", "=", po_id)], ["name", "amount_total", "state"]
        )
        return {"success": True, "purchase_order_id": po_id, **po[0]}
    except Exception as e:
        log_audit("create_purchase_order", f"ERROR: {e}")
        return {"error": str(e)}


@mcp.tool()
def confirm_purchase_order(order_id: int) -> dict:
    """
    Confirm a draft purchase order (RFQ → Purchase Order).

    Args:
        order_id: The ID of the purchase order to confirm.
    """

    permission = check_permission("confirm_purchase_order")

    if permission == "deny":
        log_audit("confirm_purchase_order", "DENIED")
        return {"error": "Permission denied by server policy"}

    if permission == "ask":
        log_audit("confirm_purchase_order", "ASK — deferred to client")

    log_audit("confirm_purchase_order", "ALLOWED")

    try:
        odoo.env["purchase.order"].button_confirm([order_id])
        po = odoo.env["purchase.order"].search_read(
            [("id", "=", order_id)], ["name", "state"]
        )
        return {"success": True, "purchase_order_id": order_id, **po[0]}
    except Exception as e:
        log_audit("confirm_purchase_order", f"ERROR: {e}")
        return {"error": str(e)}


# ============================================================
# Employee / HR Tools
# ============================================================

@mcp.tool()
def get_employees(name: str = None, department: str = None, limit: int = 50) -> list:
    """
    Search employees in Odoo HR module.

    Args:
        name: Filter by employee name (optional).
        department: Filter by department name (optional).
        limit: Maximum number of results. Defaults to 50.
    """

    if check_permission("get_employees") != "allow":
        log_audit("get_employees", "DENIED")
        return {"error": "Permission denied by server policy"}

    log_audit("get_employees", "ALLOWED")

    domain = []
    if name:
        domain.append(("name", "ilike", name))
    if department:
        domain.append(("department_id.name", "ilike", department))

    employees = odoo.env["hr.employee"].search_read(
        domain,
        [
            "name", "job_title", "department_id", "work_email",
            "work_phone", "parent_id", "coach_id",
        ],
        limit=limit,
    )
    return employees


@mcp.tool()
def get_employee_details(employee_id: int) -> dict:
    """
    Get detailed information about an employee.

    Args:
        employee_id: The ID of the employee.
    """

    if check_permission("get_employee_details") != "allow":
        log_audit("get_employee_details", "DENIED")
        return {"error": "Permission denied by server policy"}

    log_audit("get_employee_details", "ALLOWED")

    try:
        employees = odoo.env["hr.employee"].search_read(
            [("id", "=", employee_id)],
            [
                "name", "job_id", "job_title", "department_id",
                "work_email", "work_phone", "mobile_phone",
                "parent_id", "coach_id", "work_location_id",
                "resource_calendar_id",
            ],
        )
        if not employees:
            return {"error": f"Employee with ID {employee_id} not found"}
        return employees[0]
    except Exception as e:
        log_audit("get_employee_details", f"ERROR: {e}")
        return {"error": str(e)}


# ============================================================
# Streamable HTTP App
# ============================================================

app = mcp.streamable_http_app()


# ============================================================
# Entrypoint
# ============================================================

if __name__ == "__main__":
    host = os.getenv("MCP_SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_SERVER_PORT", "8001"))
    uvicorn.run(app, host=host, port=port)