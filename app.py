import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
from dotenv import load_dotenv
import requests
from datetime import datetime, timezone

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Zoho API Configuration loaded from environment variables
ZOHO_API_URL = os.getenv("ZOHO_API_URL")
ZOHO_REFRESH_URL = os.getenv("ZOHO_REFRESH_URL")
ACCESS_TOKEN = os.getenv("ZOHO_ACCESS_TOKEN")
ORGANIZATION_ID = os.getenv("ZOHO_ORG_ID")
WAREHOUSE_REQUIRED = os.getenv(
    "WAREHOUSE_REQUIRED", "Surulere Store,Lekki Store"
).split(",")
LOCATION_NAME_REQUIRED = os.getenv(
    "LOCATION_NAME_REQUIRED", "Surul/Stock,Lekki/Stock"
).split(",")

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


@app.route("/odoo/webhook", methods=["POST"], strict_slashes=False)
def odoo_webhook():
    """
    Endpoint to receive webhooks from Odoo and update Zoho Inventory item quantity.
    """
    try:
        data = request.json
        model_action = data.get("x_model_action")
        # logging.info("Webhook payload: %s", data)

        if not model_action:
            logging.warning("Ignoring webhook with missing or empty x_model_action")
            return (
                jsonify(
                    {"status": "ignored", "message": "Missing or empty x_model_action"}
                ),
                200,
            )

        if model_action.startswith("stock."):

            logging.info("Processing stock-related webhook action: %s", model_action)

            # Extract necessary data from the webhook payload
            warehouse_info = data.get("company_id")
            product_info = data.get("product_id")
            location_info = data.get("location_id")
            location_dest_info = data.get("location_dest_id")
            quantity = data.get("quantity_done", 0.0)

            # Validate the webhook payload and check if the warehouse is in scope
            if not is_valid_webhook_payload(
                warehouse_info,
                product_info,
                location_info,
                location_dest_info,
                quantity,
            ):
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Invalid webhook payload or warehouse not in scope",
                        }
                    ),
                    400,
                )

            # Access the second element from the lists
            warehouse_name = warehouse_info[1]
            product_name = product_info[1]
            location_name = location_info[1]
            location_dest_name = location_dest_info[1]

            # process quantity
            quantity = get_adjusted_quantity(
                location_name, location_dest_name, quantity
            )
            logging.info(
                "Adjusted quantity for product '%s' in warehouse '%s' and from location '%s' to location '%s': %s ",
                product_name,
                warehouse_name,
                location_name,
                location_dest_name,
                quantity,
            )

            # Dont proceed if quantity is zero (internal transfer)
            if quantity == 0:
                logging.info("No net stock change detected, skipping update.")
                return (
                    jsonify(
                        {
                            "status": "ignored",
                            "message": "No net stock change detected",
                        }
                    ),
                    200,
                )

            # Fetch item ID from Zoho based on product and warehouse
            item_warehouse_id = fetch_zoho_item_id(product_name, warehouse_name)
            if not item_warehouse_id:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Product not found in Zoho Inventory or warehouse not in scope",
                        }
                    ),
                    404,
                )

            # Prepare the data for Zoho API update
            item_id = item_warehouse_id["item_id"]
            warehouse_id = item_warehouse_id["warehouse_id"]
            zoho_data = {
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "reason": "Webhook triggered adjustment",
                "description": f"Adjustment from Odoo for {product_name}",
                "reference_number": f"Webhook-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                "adjustment_type": "quantity",
                "location_id": warehouse_id,
                "line_items": [
                    {
                        "item_id": item_id,
                        "name": product_name,
                        "description": f"Stock updated from Odoo webhook",
                        "quantity_adjusted": quantity,
                        "unit": "pcs",
                        # "location_id": warehouse_id,
                    }
                ],
            }

            # Call Zoho API to update inventory
            update_response = update_zoho_inventory(item_id, zoho_data)

            if update_response.status_code in [200, 201]:
                logging.info(
                    "Successfully updated Zoho Inventory for item: %s",
                    product_name,
                )
                return (
                    jsonify(
                        {
                            "status": "success",
                            "message": "Zoho Inventory updated successfully",
                        }
                    ),
                    200,
                )
            else:
                logging.error(
                    "Failed to update Zoho Inventory: %s", update_response.text
                )
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Failed to update Zoho Inventory",
                        }
                    ),
                    500,
                )
        elif model_action.startswith("product."):
            # validate required name field for product actions if any
            item_name = data.get("name")
            if not item_name:
                logging.warning("Ignoring product webhook with missing or empty name")
                return (
                    jsonify(
                        {
                            "status": "ignored",
                            "message": "Missing or empty product name",
                        }
                    ),
                    200,
                )
            # prepare zoho_item_payload object
            create_status = create_zoho_item(data)
            # check if response status is not None
            if create_status is None:
                logging.error("Failed to create Zoho Inventory item: No response")
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Failed to create Zoho Inventory item",
                        }
                    ),
                    500,
                )
            if create_status.status_code in [200, 201]:
                logging.info(
                    "Successfully created Zoho Inventory item: %s",
                    item_name,
                )
                return (
                    jsonify(
                        {
                            "status": "success",
                            "message": "Zoho Inventory item created successfully",
                        }
                    ),
                    200,
                )
            else:
                logging.error(
                    "Failed to create Zoho Inventory item: %s", create_status.text
                )
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Failed to create Zoho Inventory item",
                        }
                    ),
                    500,
                )

        else:
            logging.info("Ignoring non-stock-related webhook action: %s", model_action)
            return (
                jsonify({"status": "ignored", "message": "Non-stock-related action"}),
                200,
            )

    except requests.exceptions.RequestException as e:
        logging.error("API request failed: %s", str(e))
        return (
            jsonify({"status": "error", "message": "External API request failed"}),
            500,
        )
    except Exception as e:
        logging.error("An internal server error occurred: %s", str(e))
        return jsonify({"status": "error", "message": "Internal Server Error"}), 500


def get_adjusted_quantity(location_name, location_dest_name, quantity):
    """
    Determine the adjusted quantity based on the model action and locations.
    """
    # Default to zero if quantity is None or not a number
    if not isinstance(quantity, (int, float)):
        quantity = 0.0
        logging.warning("Invalid quantity type, defaulting to 0.0")

    # Determine the adjustment based on locations
    if location_name in LOCATION_NAME_REQUIRED:
        # Stock is going out from a tracked warehouse to an untracked location
        return -abs(quantity)
    elif location_dest_name in LOCATION_NAME_REQUIRED:
        # Stock is coming into a tracked warehouse from an untracked location
        return abs(quantity)
    else:
        # Internal transfer, no net change
        return 0.0


def is_valid_webhook_payload(
    warehouse_info, product_info, location_info, location_dest_info, quantity
):
    """
    Validate webhook payload fields.
    """
    # Ensure that warehouse_info and product_info are lists and contain the necessary data
    return (
        isinstance(warehouse_info, list)
        and len(warehouse_info) > 1
        and warehouse_info[1] in WAREHOUSE_REQUIRED
        and isinstance(product_info, list)
        and len(product_info) > 1
        and isinstance(quantity, (int, float))
        and isinstance(location_info, list)
        and len(location_info) > 1
        and isinstance(location_dest_info, list)
        and len(location_dest_info) > 1
    )


def fetch_zoho_item_id(product_name: str, warehouse: str, retry=True) -> dict | None:
    """
    Fetch Zoho item ID and warehouse ID by product name and warehouse.
    Retry once if token refresh is needed.

    Returns:
        dict with keys 'item_id' and 'warehouse_id' if found,
        or None if not found or error occurs.
    """
    global ACCESS_TOKEN  # to update it after refresh

    try:
        headers = {
            "Authorization": f"Zoho-oauthtoken {ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }

        # Search item by product name
        response = requests.get(
            f"{ZOHO_API_URL}/items",
            headers=headers,
            params={"organization_id": ORGANIZATION_ID, "name": product_name},
        )
        response.raise_for_status()

        items = response.json().get("items", [])

        if not items:
            logging.warning("Product not found in Zoho Inventory: %s", product_name)
            return None

        # Assume the first result is the correct item
        zoho_item = items[0]
        item_id = zoho_item.get("item_id")
        if not item_id:
            logging.warning("Item ID missing in search result for product: %s", product_name)
            return None

        logging.info("Fetched Zoho item ID: %s for product: %s", item_id, product_name)

        # Fetch detailed item info by item ID
        response = requests.get(
            f"{ZOHO_API_URL}/items/{item_id}",
            headers=headers,
            params={"organization_id": ORGANIZATION_ID},
        )
        response.raise_for_status()

        data = response.json()
        item = data.get("item")
        if not item or "item_id" not in item:
            logging.warning("Product not found or missing item_id in item details: %s", product_name)
            return None

        warehouses = item.get("warehouses", [])
        if not isinstance(warehouses, list):
            logging.warning("Unexpected format for 'warehouses'. Expected list but got: %s", type(warehouses))
            return None

        # No warehouses means global stock update allowed
        if not warehouses:
            logging.info(f"Item '{product_name}' has no warehouses listed. Assuming global stock update.")
            return {
                "item_id": item["item_id"],
                "warehouse_id": None
            }

        # Get warehouse ID from helper
        warehouse_id = get_warehouse_id(warehouse)
        if not warehouse_id:
            logging.warning(f"Warehouse '{warehouse}' not recognized or missing ID.")
            return None

        # Check if item is in the specified warehouse
        for warehouse_info in warehouses:
            if isinstance(warehouse_info, dict):
                if warehouse_info.get("warehouse_id") == warehouse_id:
                    logging.info(f"Product '{product_name}' found in warehouse '{warehouse}'.")
                    return {
                        "item_id": item["item_id"],
                        "warehouse_id": warehouse_id
                    }
            else:
                logging.warning("Unexpected warehouse info format. Expected dict but got %s", type(warehouse_info))

        logging.warning(f"Product '{product_name}' not found in the specified warehouse '{warehouse}'.")
        return None

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401 and retry:
            logging.warning("401 Unauthorized - refreshing token and retrying fetch_zoho_item_id")
            if refresh_token():
                ACCESS_TOKEN = os.getenv("ZOHO_ACCESS_TOKEN")
                return fetch_zoho_item_id(product_name, warehouse, retry=False)
            else:
                logging.error("Token refresh failed during fetch_zoho_item_id")
                return None
        else:
            logging.error("API request failed in fetch_zoho_item_id: %s", e)
            return None
    except Exception as e:
        logging.error("Error in fetch_zoho_item_id: %s", e)
        return None

def get_warehouse_id(warehouse_name: str) -> str:
    """
    Get the Zoho warehouse ID based on the warehouse name.
    """
    if warehouse_name == WAREHOUSE_REQUIRED[0]:
        return os.getenv("ZOHO_WAREHOUSE_SURULERE_ID")
    elif warehouse_name == WAREHOUSE_REQUIRED[1]:
        return os.getenv("ZOHO_WAREHOUSE_LEKKI_ID")
    else:
        return None

def update_zoho_inventory(item_id, zoho_data, retry=True):
    """
    Update Zoho Inventory with the provided item ID and data.
    Retry once on 401.
    """
    global ACCESS_TOKEN
    try:
        response = requests.post(
            f"{ZOHO_API_URL}/inventoryadjustments?organization_id={ORGANIZATION_ID}",
            headers={
                "Authorization": f"Zoho-oauthtoken {ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            json=zoho_data,
        )
        response.raise_for_status()
        return response

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401 and retry:
            logging.warning(
                "401 Unauthorized - refreshing token and retrying update_zoho_inventory"
            )
            if refresh_token():
                ACCESS_TOKEN = os.getenv("ZOHO_ACCESS_TOKEN")
                return update_zoho_inventory(item_id, zoho_data, retry=False)
            else:
                logging.error("Token refresh failed during update_zoho_inventory")
                return e.response
        else:
            logging.error("API request failed in update_zoho_inventory: %s", e)
            return e.response
    except Exception as e:
        logging.error("Error in update_zoho_inventory: %s", e)
        return None


def refresh_token() -> bool:
    """
    Refresh Zoho access token synchronously.
    Returns True if refresh successful, False otherwise.
    """
    logging.info("Refreshing Zoho access token...")
    response = requests.post(
        f"{ZOHO_REFRESH_URL}",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "refresh_token": os.getenv("ZOHO_REFRESH_TOKEN"),
            "client_id": os.getenv("ZOHO_CLIENT_ID"),
            "client_secret": os.getenv("ZOHO_CLIENT_SECRET"),
            "grant_type": "refresh_token",
        },
    )
    if response.status_code in [200, 201]:
        access_token_data = response.json()
        new_access_token = access_token_data.get("access_token")
        if new_access_token:
            os.environ["ZOHO_ACCESS_TOKEN"] = new_access_token
            logging.info("Successfully refreshed Zoho access token")
            return True
        else:
            logging.error("Failed to get new access token from Zoho")
            return False
    else:
        logging.error("Failed to refresh Zoho access token: %s", response.text)
        return False


def process_zoho_item_payload(data):
    """
    Process the webhook data to create a Zoho item payload.
    """
    # check for company id in a list to determine warehouse
    company = data.get("company_id")[1] if data.get("company_id") else None
    if company in WAREHOUSE_REQUIRED:
        logging.info("Company '%s' requires location assignment.", company)
        warehouse_id = (
            os.getenv("ZOHO_WAREHOUSE_SURULERE_ID")
            if company == WAREHOUSE_REQUIRED[0]
            else os.getenv("ZOHO_WAREHOUSE_LEKKI_ID")
        )   
    else:
        logging.info("Company '%s' doesn't require location assignment.", company)
        warehouse_id = None
    logging.info("Assigned warehouse ID: %s", warehouse_id)

    zoho_item_payload = {
        "name": data.get("name"),
        "unit": data.get("uom_name", "pcs"),
        "item_type": "inventory" if data.get("type") == "product" else "sales",
        "product_type": "goods",
        "tax_id": data["taxes_id"][0] if data.get("taxes_id") else None,
        "description": data.get("product_tooltip", "No description available"),
        "rate": data.get("list_price", 0.0),
        "purchase_rate": data.get("standard_price", 0.0),
        "reorder_level": 0,
        "track_inventory": True,
        "sku": data.get("barcode") or data.get("id"),
        "purchase_description": data.get("description_purchase")
        or "No purchase description",
        "item_tax_preferences": (
            [{"tax_id": data["taxes_id"][0], "tax_specification": "intra"}]
            if data.get("taxes_id")
            else []
        )
    }
    if warehouse_id:
        zoho_item_payload["locations"] = [
            {
                "location_id": warehouse_id,
                "initial_stock": data.get("qty_available", 0.0),
                "initial_stock_rate": data.get("list_price", 0.0),
            }
        ]
    return zoho_item_payload

def create_zoho_item(data, retry=True):
    """
    Create a new item in Zoho Inventory.
    """
    global ACCESS_TOKEN
    try:
        zoho_item_payload = process_zoho_item_payload(data)
        logging.info(f"Creating Zoho item with payload: {zoho_item_payload}")

        response = requests.post(
            f"{ZOHO_API_URL}/items?organization_id={ORGANIZATION_ID}",
            headers={
                "Authorization": f"Zoho-oauthtoken {ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            json=zoho_item_payload,
        )
        response.raise_for_status()
        return response

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401 and retry:
            logging.warning(
                "401 Unauthorized - refreshing token and retrying create_zoho_inventory_item"
            )
            if refresh_token():
                ACCESS_TOKEN = os.getenv("ZOHO_ACCESS_TOKEN")
                return create_zoho_item(data, retry=False)
            else:
                logging.error("Token refresh failed during create_zoho_item")
                return e.response
        else:
            logging.error("API request failed in create_zoho_item: %s", e)
            return e.response
    except Exception as e:
        logging.error("Error in create_zoho_item: %s", e)
        return None

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
