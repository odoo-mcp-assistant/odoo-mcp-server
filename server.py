import os
import random
import threading
from datetime import datetime, timedelta
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
def get_categories() -> list:
    """
    Get all available product categories on the website.
    Use this when the customer asks what categories or types of products are available.
    """
    try:
        categories = odoo.env["product.public.category"].search_read(
            [],
            ["name", "parent_id", "sequence"],
            order="sequence asc",
        )
        return categories
    except Exception as e:
        return {"error": str(e)}
    

@mcp.tool()
def search_products(query: str, category_name: Optional[str] = None) -> list:
    """
    Search published products by name or keyword, with an optional category filter.
    Use this as the main product search tool for any customer query.
    Replaces get_product_by_name — do not use that tool anymore.
 
    Args:
        query: The search keyword or product name.
        category_name: Optional category to narrow results (use get_categories() to get valid names).
    """
    try:
        domain = [
            ("name", "ilike", query),
            ("sale_ok", "=", True),
            ("is_published", "=", True),
        ]
 
        if category_name:
            cat_ids = odoo.env["product.public.category"].search(
                [("name", "ilike", category_name)]
            )
            if cat_ids:
                domain.append(("public_categ_ids", "in", cat_ids))
 
        products = odoo.env["product.template"].search_read(
            domain,
            ["name", "list_price", "public_categ_ids", "description_sale"],
            order="list_price asc",
        )
        return products
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_products_by_category(category_name: str, min_price: Optional[float] = None, max_price: Optional[float] = None) -> list:
    """
    Get published products belonging to a given category, with optional price filtering.
    Always call get_categories() first to get the exact category name.
 
    Args:
        category_name: The category name to filter by (e.g. 'Laptops', 'TVs').
        min_price: Optional minimum price filter.
        max_price: Optional maximum price filter.
    """
    try:
        # Resolve category id from name
        cat_ids = odoo.env["product.public.category"].search(
            [("name", "ilike", category_name)]
        )
        if not cat_ids:
            return {"error": f"Category '{category_name}' not found. Call get_categories() to see available ones."}
 
        domain = [
            ("public_categ_ids", "in", cat_ids),
            ("sale_ok", "=", True),
            ("is_published", "=", True),
        ]
 
        if min_price is not None:
            domain.append(("list_price", ">=", min_price))
        if max_price is not None:
            domain.append(("list_price", "<=", max_price))
 
        products = odoo.env["product.template"].search_read(
            domain,
            ["name", "list_price", "public_categ_ids", "description_sale"],
            order="list_price asc",
        )
        return products
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_products_by_price_range(min_price: float, max_price: float) -> list:
    """
    Search products within a price range.

    Args:
        min_price: Minimum price (inclusive).
        max_price: Maximum price (inclusive).
    """
    try:
        products = odoo.env["product.product"].search_read(
            [
                ("list_price", ">=", min_price),
                ("list_price", "<=", max_price),
                ("sale_ok", "=", True),
                ("is_published", "=", True),
            ],
            ["name", "list_price", "categ_id"]
        )
        return products
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_product_details(name: str) -> dict:
    """
    Get full details of a product including price, description, stock, and all specs/attributes (RAM, storage, color, etc.).
    Use this when the customer asks for product specs, variants, or detailed information.
    This replaces the old get_product_details — always use this version.
 
    Args:
        name: The exact or partial product name.
    """
    try:
        products = odoo.env["product.template"].search_read(
            [
                ("name", "ilike", name),
                ("sale_ok", "=", True),
                ("is_published", "=", True),
            ],
            [
                "name", "list_price", "description_sale",
                "public_categ_ids", "attribute_line_ids",
                "qty_available", "virtual_available",
            ],
            limit=1,
        )
 
        if not products:
            return {"error": f"Product '{name}' not found."}
 
        product = products[0]
 
        # Fetch attribute lines (specs: RAM, Storage, Color, etc.)
        attr_line_ids = product.pop("attribute_line_ids", [])
        specs = []
 
        if attr_line_ids:
            attr_lines = odoo.env["product.template.attribute.line"].search_read(
                [("id", "in", attr_line_ids)],
                ["attribute_id", "value_ids"],
            )
 
            for line in attr_lines:
                attr_name = line["attribute_id"][1] if line.get("attribute_id") else "Unknown"
                value_ids = line.get("value_ids", [])
 
                values = []
                if value_ids:
                    value_records = odoo.env["product.attribute.value"].search_read(
                        [("id", "in", value_ids)],
                        ["name"],
                    )
                    values = [v["name"] for v in value_records]
 
                specs.append({
                    "attribute": attr_name,
                    "values": values,
                })
 
        product["specs"] = specs
        return product
 
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

    if partner_id is None:
        return {
            "error": True,
            "code": "AUTH_REQUIRED",
            "message": "Authentication required. Please sign in to your account or verify your identity via email.",
        }

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
                       - product_name (str): the product name to search for
                       - quantity (float): quantity to order
    Example:
        product_lines = [
            {"product_name": "TV Samsung", "quantity": 2},
            {"product_name": "Washing Machine", "quantity": 1}
        ]
    """
    if partner_id is None:
        return {
            "error": True,
            "code": "AUTH_REQUIRED",
            "message": "Authentication required. Please sign in to your account or verify your identity via email.",
        }

    try:
        # Create the order header
        order_id = odoo.env["sale.order"].create({
            "partner_id": partner_id,
        })

        # Add order lines
        for line in product_lines:
            product_name = line.get("product_name")
            quantity     = line.get("quantity", 1)

            if not product_name:
                continue

            # Search for the product by name
            product_ids = odoo.env["product.product"].search(
                [("name", "ilike", product_name)], limit=1
            )

            if not product_ids:
                # Product not found — delete the empty order and return error
                odoo.env["sale.order"].browse(order_id).action_cancel()
                return {
                    "error": True,
                    "message": f"Product '{product_name}' not found. Order was not created."
                }

            product_id = product_ids[0]

            line_vals = {
                "order_id":        order_id,
                "product_id":      product_id,
                "product_uom_qty": quantity,
            }

            odoo.env["sale.order.line"].create(line_vals)

        # Read back the created order
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
    if partner_id is None:
        return {
            "error": True,
            "code": "AUTH_REQUIRED",
            "message": "Authentication required. Please sign in to your account or verify your identity via email.",
        }

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
    if partner_id is None:
        return {
            "error": True,
            "code": "AUTH_REQUIRED",
            "message": "Authentication required. Please sign in to your account or verify your identity via email.",
        }

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


@mcp.tool()
def get_order_details(order_name: str, partner_id: Optional[int] = None) -> dict:
    """
    Get full details of a specific order by its reference name.
    IMPORTANT: Always pass partner_id as null. It is injected automatically by the system. Never fill it yourself.

    Args:
        order_name: The order reference e.g. 'S00001'.
    """
    if partner_id is None:
        return {
            "error": True,
            "code": "AUTH_REQUIRED",
            "message": "Authentication required. Please sign in to your account or verify your identity via email.",
        }
    try:
        orders = odoo.env["sale.order"].search_read(
            [("name", "=", order_name), ("partner_id", "=", partner_id)],
            ["name", "date_order", "state", "amount_total",
             "currency_id", "order_line", "note"],
        )
        if not orders:
            return {"error": f"Order '{order_name}' not found."}

        order = orders[0]
        line_ids = order.pop("order_line", [])
        if line_ids:
            order["lines"] = odoo.env["sale.order.line"].search_read(
                [("id", "in", line_ids)],
                ["product_id", "product_uom_qty", "price_unit", "price_subtotal"],
            )
        return order
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_my_profile(partner_id: Optional[int] = None) -> dict:
    """
    Get the current authenticated customer profile including name, email, phone, and address.
    IMPORTANT: Always pass partner_id as null. It is injected automatically by the system. Never fill it yourself.
    """
    if partner_id is None:
        return {
            "error": True,
            "code": "AUTH_REQUIRED",
            "message": "Authentication required. Please sign in to your account or verify your identity via email.",
        }
    try:
        partners = odoo.env["res.partner"].search_read(
            [("id", "=", partner_id)],
            ["name", "email", "phone", "street", "city", "zip", "country_id"]
        )
        if not partners:
            return {"error": "Profile not found."}
        return partners[0]
    except Exception as e:
        return {"error": str(e)}

# ============================================================
# Invoice Tools
# ============================================================

@mcp.tool()
def get_invoices(partner_id: Optional[int] = None) -> list:
    """
    Get all invoices for the current authenticated customer.
    IMPORTANT: Always pass partner_id as null. It is injected automatically by the system. Never fill it yourself.
    """
    if partner_id is None:
        return {
            "error": True,
            "code": "AUTH_REQUIRED",
            "message": "Authentication required. Please sign in to your account or verify your identity via email.",
        }

    try:
        invoices = odoo.env["account.move"].search_read(
            [
                ("partner_id",  "=",  partner_id),
                ("move_type",   "=",  "out_invoice"),
                ("state",      "=", "posted"),
            ],
            ["name", "invoice_date", "invoice_date_due", "state",
             "payment_state", "amount_untaxed", "amount_tax",
             "amount_total", "amount_residual", "currency_id"],
            order="invoice_date desc",
        )
        return invoices
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_invoice_details(invoice_name: str, partner_id: Optional[int] = None) -> dict:
    """
    Get full details of a specific invoice by its reference number, including all line items.
    IMPORTANT: Always pass partner_id as null. It is injected automatically by the system. Never fill it yourself.

    Args:
        invoice_name: The invoice reference e.g. 'INV/2024/00001'.
    """
    if partner_id is None:
        return {
            "error": True,
            "code": "AUTH_REQUIRED",
            "message": "Authentication required. Please sign in to your account or verify your identity via email.",
        }

    try:
        invoices = odoo.env["account.move"].search_read(
            [
                ("name",       "=", invoice_name),
                ("partner_id", "=", partner_id),
                ("move_type",  "=", "out_invoice"),
                ("state",      "=", "posted"),
            ],
            ["name", "invoice_date", "invoice_date_due", "state",
             "payment_state", "amount_untaxed", "amount_tax",
             "amount_total", "amount_residual", "currency_id",
             "invoice_line_ids", "narration"],
        )

        if not invoices:
            return {"error": f"Invoice '{invoice_name}' not found."}

        invoice = invoices[0]
        line_ids = invoice.pop("invoice_line_ids", [])

        if line_ids:
            invoice["lines"] = odoo.env["account.move.line"].search_read(
                [
                    ("id",          "in", line_ids),
                    ("display_type", "=", "product"),
                ],
                ["name", "quantity", "price_unit", "price_subtotal", "tax_ids"],
            )

        return invoice
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_unpaid_invoices(partner_id: Optional[int] = None) -> list:
    """
    Get all unpaid or partially paid invoices for the current authenticated customer.
    IMPORTANT: Always pass partner_id as null. It is injected automatically by the system. Never fill it yourself.
    """
    if partner_id is None:
        return {
            "error": True,
            "code": "AUTH_REQUIRED",
            "message": "Authentication required. Please sign in to your account or verify your identity via email.",
        }

    try:
        invoices = odoo.env["account.move"].search_read(
            [
                ("partner_id",   "=",  partner_id),
                ("move_type",    "=",  "out_invoice"),
                ("state",        "=",  "posted"),
                ("payment_state", "in", ["not_paid", "partial"]),
            ],
            ["name", "invoice_date", "invoice_date_due", "payment_state",
             "amount_total", "amount_residual", "currency_id"],
            order="invoice_date_due asc",
        )
        return invoices
    except Exception as e:
        return {"error": str(e)}







@mcp.tool()
def check_stock(product_name: str) -> dict:
    """
    Check stock availability of a product.
    """
    product = odoo.env["product.product"].search(
        [("name", "ilike", product_name)], limit=1
    )

    if not product:
        return {"error": f"Product '{product_name}' not found."}

    return {
        "name": product.name,
        "available_qty": product.qty_available,
        "forecast_qty": product.virtual_available,
        "in_stock": product.qty_available > 0
    }




@mcp.tool()
def simulate_cart(product_lines: list) -> dict:
    """
    Simulate total price before creating an order.

    Args:
        product_lines: [{product_name, quantity}]
    """
    total = 0
    details = []

    for line in product_lines:
        product = odoo.env["product.product"].search(
            [("name", "ilike", line.get("product_name"))], limit=1
        )

        if not product:
            return {"error": f"Product '{line.get('product_name')}' not found."}

        qty = line.get("quantity", 1)
        subtotal = product.list_price * qty
        total += subtotal

        details.append({
            "product": product.name,
            "quantity": qty,
            "unit_price": product.list_price,
            "subtotal": subtotal
        })

    return {
        "total": total,
        "lines": details
    }

# ============================================================
# Email OTP Verification Tools
# ============================================================

# In-memory OTP store: { email_lower -> {"code": str, "expires_at": datetime} }
# Thread-safe via a simple lock — lightweight enough for chatbot traffic.
_otp_store: dict = {}
_otp_lock = threading.Lock()

OTP_EXPIRY_MINUTES = 10


@mcp.tool()
def send_verification_email(email: str) -> dict:
    """
    Send a 6-digit OTP verification code to the user's email address.
    Use this when an anonymous user wants to perform an action that requires
    authentication (e.g. viewing orders, creating an order).
    First ask the user for their email, then call this tool.

    Args:
        email: The user's email address to send the verification code to.
    """
    email = email.strip().lower()
    if not email or "@" not in email:
        return {"error": "Invalid email address."}

    try:
        code = str(random.randint(100000, 999999))
        expires_at = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)

        with _otp_lock:
            _otp_store[email] = {"code": code, "expires_at": expires_at}

        # Send via Odoo mail
        mail_id = odoo.env["mail.mail"].create({
            "subject": "Your verification code",
            "email_to": email,
            "body_html": (
                f"<p>Hello,</p>"
                f"<p>Your verification code is: "
                f"<strong style='font-size:18px;letter-spacing:4px'>{code}</strong></p>"
                f"<p>This code is valid for {OTP_EXPIRY_MINUTES} minutes.</p>"
            ),
            "auto_delete": True,
        })
        odoo.env["mail.mail"].send([mail_id])

        return {
            "success": True,
            "message": f"A 6-digit verification code has been sent to {email}. Please ask the user to enter it.",
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def verify_email_otp(email: str, otp_code: str) -> dict:
    """
    Verify the 6-digit OTP code the user received by email.
    If successful, the user's identity is confirmed and they can immediately
    proceed with authentication-required actions.

    Args:
        email: The email address the code was sent to.
        otp_code: The 6-digit code entered by the user.
    """
    email = email.strip().lower()
    otp_code = otp_code.strip()

    with _otp_lock:
        entry = _otp_store.get(email)

    if not entry:
        return {"error": "No verification code was requested for this email. Please call send_verification_email first."}

    if datetime.utcnow() > entry["expires_at"]:
        with _otp_lock:
            _otp_store.pop(email, None)
        return {"error": "The code has expired. Please request a new one."}

    if entry["code"] != otp_code:
        return {"error": "Invalid code. Please try again."}

    # Code is valid — consume it
    with _otp_lock:
        _otp_store.pop(email, None)

    try:
        # Find or create a res.partner for this email.
        # Use raw integer IDs from search/create — never browse().id,
        # which can return unexpected values in odoorpc.
        partner_ids = odoo.env["res.partner"].search([("email", "=ilike", email)])
        if partner_ids:
            pid = partner_ids[0]
        else:
            pid = odoo.env["res.partner"].create({
                "name": email.split("@")[0],
                "email": email,
            })

        info = odoo.env["res.partner"].read([pid], ["name", "email"])[0]

        return {
            "success": True,
            "partner_id": pid,
            "name": info["name"],
            "email": info["email"],
            "message": "Verification successful! Identity confirmed. You can now proceed with the user's request.",
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