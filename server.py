import os
import random
import time
import threading
from datetime import datetime, timedelta, timezone
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
# Simple In-Memory Cache
# ============================================================

CACHE_TTL = 300  # 5 minutes
PAGE_SIZE = 5

_cache: dict = {}
_cache_lock = threading.Lock()


def _get_cache(key: str):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.time() < entry["expires"]:
            return entry["data"]
    return None


def _set_cache(key: str, data):
    with _cache_lock:
        _cache[key] = {"data": data, "expires": time.time() + CACHE_TTL}


# ============================================================
# Product Tools
# ============================================================

@mcp.tool()
def get_catalogue_overview() -> dict:
    """Get a compact overview of the entire product catalogue in a single call: categories with product counts and sample products. Use this for broad or exploratory questions like 'what do you sell?' instead of calling search_products multiple times."""
    cached = _get_cache("catalogue_overview")
    if cached is not None:
        return cached
    try:
        categories = odoo.env["product.public.category"].search_read(
            [], ["name", "parent_id"], order="sequence asc",
        )

        overview = []
        for cat in categories:
            domain = [
                ("sale_ok", "=", True),
                ("is_published", "=", True),
                ("public_categ_ids", "in", [cat["id"]]),
            ]
            count = odoo.env["product.template"].search_count(domain)
            if count == 0:
                continue
            sample = odoo.env["product.template"].search_read(
                domain, ["name", "list_price"], limit=3,
            )
            overview.append({
                "category": cat["name"],
                "parent": cat["parent_id"][1] if cat["parent_id"] else None,
                "product_count": count,
                "sample_products": [{"name": p["name"], "price": p["list_price"]} for p in sample],
            })

        result = {"categories": overview}
        _set_cache("catalogue_overview", result)
        return result
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def search_products(query: str, category_name: Optional[str] = None, min_price: Optional[float] = None, max_price: Optional[float] = None, page: int = 1) -> dict:
    """Search products by name/keyword with optional category and price filters (paginated, 5 per page).

    Args:
        query: Search keyword or product name.
        category_name: Optional category name to filter by.
        min_price: Optional minimum price.
        max_price: Optional maximum price.
        page: Page number starting from 1 (default 1).
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

        if min_price is not None:
            domain.append(("list_price", ">=", min_price))
        if max_price is not None:
            domain.append(("list_price", "<=", max_price))

        total_count = odoo.env["product.template"].search_count(domain)
        total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE if total_count else 0

        if page < 1 or (total_pages and page > total_pages):
            return {"error": f"Invalid page {page}. Valid range: 1-{total_pages}."}

        offset = (page - 1) * PAGE_SIZE

        products = odoo.env["product.template"].search_read(
            domain,
            ["name", "list_price", "public_categ_ids", "description_sale"],
            order="list_price asc",
            limit=PAGE_SIZE,
            offset=offset,
        )

        returned = len(products)
        hint = f"Showing {returned} of {total_count} products (page {page}/{total_pages})."
        if page < total_pages:
            hint += f" Call search_products with same arguments and page={page + 1} to get more."

        return {
            "products": products,
            "current_page": page,
            "total_pages": total_pages,
            "total_products": total_count,
            "hint": hint,
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def get_product_details(name: str) -> dict:
    """Get full product details: price, description, stock, and attributes/specs.

    Args:
        name: Exact or partial product name.
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
def get_orders(page: int = 1, partner_id: Optional[int] = None) -> dict:
    """Get sale orders for the customer (paginated, 5 per page). partner_id is auto-injected, always pass null.

    Args:
        page: Page number starting from 1 (default 1).
    """

    if partner_id is None:
        return {
            "error": True,
            "code": "AUTH_REQUIRED",
            "message": "Authentication required. Please sign in to your account or verify your identity via email.",
        }

    try:
        domain = [("partner_id", "=", partner_id)]
        total_count = odoo.env["sale.order"].search_count(domain)
        total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE if total_count else 0

        if page < 1 or (total_pages and page > total_pages):
            return {"error": f"Invalid page {page}. Valid range: 1-{total_pages}."}

        offset = (page - 1) * PAGE_SIZE

        orders = odoo.env["sale.order"].search_read(
            domain,
            [
                "name", "date_order", "state",
                "amount_total", "currency_id", "order_line",
            ],
            order="date_order desc",
            limit=PAGE_SIZE,
            offset=offset,
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

        returned = len(result)
        hint = f"Showing {returned} of {total_count} orders (page {page}/{total_pages})."
        if page < total_pages:
            hint += f" Call get_orders with page={page + 1} to get more."

        return {
            "orders": result,
            "current_page": page,
            "total_pages": total_pages,
            "total_orders": total_count,
            "hint": hint,
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def create_order(product_lines: list, partner_id: Optional[int] = None) -> dict:
    """Create a sale order. partner_id is auto-injected, always pass null.

    Args:
        product_lines: List of {product_name: str, quantity: float}.
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
    """Confirm a sale order (draft → sale). partner_id is auto-injected, always pass null.

    Args:
        order_name: Order reference e.g. 'S00001'.
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
    """Cancel a sale order. partner_id is auto-injected, always pass null.

    Args:
        order_name: Order reference e.g. 'S00001'.
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
    """Get full details of an order with line items. partner_id is auto-injected, always pass null.

    Args:
        order_name: Order reference e.g. 'S00001'.
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
    """Get customer profile (name, email, phone, address). partner_id is auto-injected, always pass null."""
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
    """Get all invoices for the customer. partner_id is auto-injected, always pass null."""
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
    """Get invoice details with line items. partner_id is auto-injected, always pass null.

    Args:
        invoice_name: Invoice reference e.g. 'INV/2024/00001'.
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
    """Get unpaid/partially paid invoices. partner_id is auto-injected, always pass null."""
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
def simulate_cart(product_lines: list) -> dict:
    """Simulate total price before creating an order.

    Args:
        product_lines: List of {product_name: str, quantity: float}.
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
    """Send a 6-digit OTP code to verify an anonymous user's email.

    Args:
        email: User's email address.
    """
    email = email.strip().lower()
    if not email or "@" not in email:
        return {"error": "Invalid email address."}

    try:
        code = str(random.randint(100000, 999999))
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)

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
def verify_email_otp(email: str, otp_code: str, session_id: Optional[int] = None) -> dict:
    """Verify the 6-digit OTP code the user received by email. session_id is auto-injected, always pass null.

    Args:
        email: Email the code was sent to.
        otp_code: The 6-digit code.
    """
    email = email.strip().lower()
    otp_code = otp_code.strip()

    with _otp_lock:
        entry = _otp_store.get(email)

    if not entry:
        return {"error": "No verification code was requested for this email. Please call send_verification_email first."}

    if datetime.now(timezone.utc) > entry["expires_at"]:
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
        
        if session_id:
            session = odoo.env["mcp.chatbot.session"].browse(session_id)
            session.write({
                "partner_id": pid,
                "last_activity": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
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