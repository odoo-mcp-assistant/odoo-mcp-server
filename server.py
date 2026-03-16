import os
from pathlib import Path

import uvicorn
import odoorpc
from dotenv import load_dotenv

from mcp.server.fastmcp import FastMCP

from typing import Optional

# Load environment variables from .env file at project root
load_dotenv(Path(__file__).resolve().parent / ".env")


# ============================================================
# Configuration
# ============================================================

ODOO_HOST = os.getenv("ODOO_HOST", "localhost")
ODOO_PORT = int(os.getenv("ODOO_PORT", "8069"))
ODOO_DB = os.getenv("ODOO_DB", "pfe_v1")
ODOO_USER = os.getenv("ODOO_USER", "admin")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "admin")


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
# Product Tools
# ============================================================

@mcp.tool()
def get_product_by_name(name: str) -> list:
    """
    Get products by name (case-insensitive search).
    """

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

    products = odoo.env["product.product"].search_read(
        [("type", "=", product_type)],
        ["name", "list_price", "type"]
    )

    return products


@mcp.tool()
def add_product(name: str, price: float, product_type: str = "consu") -> dict:
    """
    Add a new product to the Odoo database.
    Args:
        name: The name of the product.
        price: The list/sale price of the product.
        product_type: The type of product — 'consu' (consumable), 'service', or 'product' (storable). Defaults to 'consu'.
    """

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
        return {"error": str(e)}


# ============================================================
# Sale Order Tools
# ============================================================

@mcp.tool()
def get_orders(partner_id: Optional[int] = None) -> list:
    """
    Get sale orders for the current authenticated customer.
    IMPORTANT: Always pass partner_id as null. It is injected automatically by the system. Never fill it yourself.
    """

    # Guard: refuse None
    if partner_id == None:
        return [{
            "error": True,
            "code": "AUTH_REQUIRED",
            "message": "You need to log in to get orders",
            "suggestion": "Please log in to your account first"
        }]

    try:
        orders = odoo.env["sale.order"].search_read(
            [("partner_id", "=", partner_id)],
            [
                "name", "date_order", "state",
                "amount_total", "currency_id", "order_line",
            ],
            order="date_order desc",
        )

        result = []
        for order in orders:
            line_ids = order.pop("order_line", [])
            lines = []
            if line_ids:
                lines = odoo.env["sale.order.line"].search_read(
                    [("id", "in", line_ids)],
                    ["product_id", "product_uom_qty", "price_unit", "price_subtotal"],
                )
            result.append({**order, "lines": lines})

        return result
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def create_order(product_lines: list, partner_id: Optional[int] = None) -> dict:
    """
    Create a new sale order for the current authenticated customer.
    IMPORTANT: Always pass partner_id as null. It is injected automatically by the system. Never fill it yourself.

    Args:
        product_lines: List of dicts, each with:
                       - product_id (int): the product ID
                       - quantity (float): quantity to order
                       - price_unit (float, optional): unit price override
    Example:
        product_lines = [
            {"product_id": 12, "quantity": 2},
            {"product_id": 7,  "quantity": 1, "price_unit": 99.99}
        ]
    """
    if partner_id == None:
        return {
            "error": True,
            "code": "AUTH_REQUIRED",
            "message": "You need to log in to get orders",
            "suggestion": "Please log in to your account first"
        }

    try:
        # Create the order header
        order_id = odoo.env["sale.order"].create({
            "partner_id": partner_id,
        })

        # Add order lines
        for line in product_lines:
            product_id = line.get("product_id")
            quantity   = line.get("quantity", 1)
            price_unit = line.get("price_unit")

            if not product_id:
                continue

            line_vals = {
                "order_id":          order_id,
                "product_id":        product_id,
                "product_uom_qty":   quantity,
            }
            if price_unit is not None:
                line_vals["price_unit"] = price_unit

            odoo.env["sale.order.line"].create(line_vals)

        # Read back the created order to return useful info
        order = odoo.env["sale.order"].read(
            [order_id],
            ["name", "state", "amount_total", "partner_id"]
        )[0]

        return {"success": True, "order": order}

    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def confirm_order(order_name: str, partner_id: Optional[int] = None) -> dict:
    """
    Confirm a sale order (moves it from draft/quotation to confirmed/sale).
    IMPORTANT: Always pass partner_id as null. It is injected automatically by the system. Never fill it yourself.

    Args:
        order_name: The order reference name e.g. 'S00001'.
    """
    try:
        order_id = odoo.env["sale.order"].search([("name", "=", order_name), ("partner_id", "=", partner_id)])

        if not order_id:
            return {
                "error": f"Order '{order_name}' not found."
            }
        
        order = odoo.env["sale.order"].browse(order_id)
        
        if order.state not in ("draft", "sent"):
            return {
                "error": f"Order '{order_name}' cannot be confirmed. Current state: {order.state}."
            }

        order.action_confirm()

        return {
            "success": True,
            "order_name": order_name,
            "new_state": "sale",
            "message": f"Order {order_name} has been confirmed successfully.",
        }

    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def cancel_order(order_name: str, partner_id: Optional[int] = None) -> dict:
    """
    Cancel a sale order.
    IMPORTANT: Always pass partner_id as null. It is injected automatically by the system. Never fill it yourself.

    Args:
        order_name: The order reference name e.g. 'S00001'.
    """
    try:
        order_id = odoo.env["sale.order"].search([("name", "=", order_name), ("partner_id", "=", partner_id)])

        if not order_id:
            return {
                "error": f"Order '{order_name}' not found."
            }

        order = odoo.env["sale.order"].browse(order_id)

        if order.state == "cancel":
            return {
                "error": f"Order '{order_name}' is already cancelled."
            }

        if order.state not in ("draft", "sent", "sale"):
            return {
                "error": f"Order '{order_name}' cannot be cancelled. Current state: {order.state}."
            }

        order.action_cancel()

        return {
            "success": True,
            "order_name": order_name,
            "new_state": "cancel",
            "message": f"Order {order_name} has been cancelled successfully.",
        }

    except Exception as e:
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
    port = int(os.getenv("MCP_SERVER_PORT", "8010"))
    uvicorn.run(app, host=host, port=port)