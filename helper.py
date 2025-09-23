import os
import logging
from dotenv import load_dotenv
import requests
import traceback
import urllib3

# Suppress SSL warnings for this test
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load environment variables from .env file
load_dotenv()

# Zoho API Configuration loaded from environment variables
ZOHO_API_URL = os.getenv("ZOHO_API_URL")
ZOHO_REFRESH_URL = os.getenv("ZOHO_REFRESH_URL")
ACCESS_TOKEN = os.getenv("ZOHO_ACCESS_TOKEN")
ORGANIZATION_ID = os.getenv("ZOHO_ORG_ID")
COMPANY_REQUIRED = os.getenv("COMPANY_REQUIRED", "Surulere Store, Lekki Store").split(
    ","
)
LOCATION_NAME_REQUIRED = os.getenv(
    "LOCATION_NAME_REQUIRED", "Su-Sh/Stock,Le-Sh/Stock"
).split(",")
WAREHOUSE_ID_MAP = os.getenv(
    "WAREHOUSE_ID_MAP", '{"Su-Sh/Stock" : "4167669000195495001", "Le-sh/Stock":"4167669000000923299"}'
)
ODOO_URL = os.getenv("ODOO_URL")
ODOO_DB = os.getenv("ODOO_DB")
ODOO_UID = os.getenv("ODOO_UID")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD")


# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def get_adjusted_quantity(location_name, location_dest_name, quantity):
    """
    Determine the adjusted quantity based on the location usage and locations.
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
    company_info, product_info, location_info, location_dest_info, quantity
):
    """
    Validate webhook payload fields.
    """
    # Ensure that company_info and product_info are lists and contain the necessary data
    return (
        isinstance(company_info, list)
        and len(company_info) > 1
        and company_info[1] in COMPANY_REQUIRED
        and isinstance(product_info, list)
        and len(product_info) > 1
        and isinstance(quantity, (int, float))
        and isinstance(location_info, list)
        and len(location_info) > 1
        and isinstance(location_dest_info, list)
        and len(location_dest_info) > 1
    )


def fetch_zoho_item_id(product_name, retry=True):
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
            logging.warning(
                "Item ID missing in search result for product: %s", product_name
            )
            return None

        logging.info("Fetched Zoho item ID: %s for product: %s", item_id, product_name)
        return item_id
    
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401 and retry:
            logging.warning(
                "401 Unauthorized - refreshing token and retrying fetch_zoho_item_id"
            )
            if refresh_token():
                ACCESS_TOKEN = os.getenv("ZOHO_ACCESS_TOKEN")
                return fetch_zoho_item_id(product_name, retry=False)
            else:
                logging.error("Token refresh failed during fetch_zoho_item_id")
                return None
        else:
            logging.error("API request failed in fetch_zoho_item_id: %s", e)
            return None
    except Exception as e:
        logging.error("Error in fetch_zoho_item_id: %s", e)
        return None

def fetch_zoho_item(item_id, retry=True):
    """
    Fetch Zoho item by item ID.
    Retry once if token refresh is needed.

    Returns:
        dict with keys 'item_id',
        or None if not found or error occurs.
    """
    global ACCESS_TOKEN  # to update it after refresh

    try:
        headers = {
            "Authorization": f"Zoho-oauthtoken {ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }
        # Search item by item ID
        response = requests.get(
            f"{ZOHO_API_URL}/items/{item_id}",
            headers=headers,
            params={"organization_id": ORGANIZATION_ID},
        )
        
        response.raise_for_status()
        item = response.json().get("item", None)
        return item
    
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401 and retry:
            logging.warning(
                "401 Unauthorized - refreshing token and retrying fetch_zoho_item"
            )
            if refresh_token():
                ACCESS_TOKEN = os.getenv("ZOHO_ACCESS_TOKEN")
                return fetch_zoho_item(item_id, retry=False)
            else:
                logging.error("Token refresh failed during fetch_zoho_item")
                return None
        else:
            logging.error("API request failed in fetch_zoho_item: %s", traceback.format_exc())
            return None
    except Exception as e:
        logging.error("Error in fetch_zoho_item: %s", traceback.format_exc())
        return None

def get_warehouse_id(company_name):
    """
    Get the Zoho warehouse ID based on the company name.
    """
    if company_name == COMPANY_REQUIRED[0].strip():
        return os.getenv("ZOHO_WAREHOUSE_SURULERE_ID")
    elif company_name == COMPANY_REQUIRED[1].strip():
        return os.getenv("ZOHO_WAREHOUSE_LEKKI_ID")
    return None

def get_item_warehouse_info(item_id, product_name, warehouse, headers, retry):
    """
    Get detailed warehouse information for a specific item.
    """
    global ACCESS_TOKEN
    try:
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
            logging.warning(
                "Product not found or missing item_id in item details: %s", product_name
            )
            return None

        warehouses = item.get("warehouses", [])
        if not isinstance(warehouses, list):
            logging.warning(
                "Unexpected format for 'warehouses'. Expected list but got: %s",
                type(warehouses),
            )
            return None

        # No warehouses means global stock update allowed
        if not warehouses:
            logging.info(
                f"Item '{product_name}' has no warehouses listed. Assuming global stock update."
            )
            return {"item_id": item["item_id"], "warehouse_id": None}

        # Get warehouse ID from helper
        warehouse_id = get_warehouse_id(warehouse)
        if not warehouse_id:
            logging.warning(f"Warehouse '{warehouse}' not recognized or missing ID.")
            return None

        # Check if item is in the specified warehouse
        for warehouse_info in warehouses:
            if isinstance(warehouse_info, dict):
                if warehouse_info.get("warehouse_id") == warehouse_id:
                    logging.info(
                        f"Product '{product_name}' found in warehouse '{warehouse}'."
                    )
                    return {"item_id": item["item_id"], "warehouse_id": warehouse_id}
            else:
                logging.warning(
                    "Unexpected warehouse info format. Expected dict but got %s",
                    type(warehouse_info),
                )

        logging.warning(
            f"Product '{product_name}' not found in the specified warehouse '{warehouse}'."
        )
        return None
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401 and retry:
            logging.warning(
                "401 Unauthorized - refreshing token and retrying get_item_warehouse_info"
            )
            if refresh_token():
                ACCESS_TOKEN = os.getenv("ZOHO_ACCESS_TOKEN")
                return get_item_warehouse_info(
                    item_id, product_name, warehouse, headers, retry=False
                )
            else:
                logging.error("Token refresh failed during get_item_warehouse_info")
                return None
        else:
            logging.error("API request failed in get_item_warehouse_info: %s", e)
            return None

    
def update_zoho_inventory_stock(item_id, zoho_data, retry=True):
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
                return update_zoho_inventory_stock(item_id, zoho_data, retry=False)
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
    if company in COMPANY_REQUIRED:
        logging.info("Company '%s' requires location assignment.", company)
        warehouse_id = (
            os.getenv("ZOHO_WAREHOUSE_SURULERE_ID")
            if company == COMPANY_REQUIRED[0]
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

def call_odoo(method, model, args, kwargs=None, rpc_id=999):
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": "object",
            "method": "execute_kw",
            "args": [ODOO_DB, ODOO_UID, ODOO_PASSWORD, model, method, args],
        },
        "id": rpc_id,
    }
    if kwargs:
        payload["params"]["args"].append(kwargs)

    logging.info("Sending payload: %s", payload)

    response = requests.post(ODOO_URL, json=payload, verify=False)
    response.raise_for_status()
    return response.json().get("result")

def upload_item_image(image, item_id):
    """This function uploads an image to a Zoho item."""
    global ACCESS_TOKEN
    try:
        response = requests.post(
            f"{ZOHO_API_URL}/items/{item_id}/image",
            headers={
                "Authorization": f"Zoho-oauthtoken {ACCESS_TOKEN}",
                "Content-Type": "multipart/form-data",
            },
            files={"image": image},
        )
        response.raise_for_status()
        logging.info("Image uploaded successfully.")
        return response

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            logging.warning(
                "401 Unauthorized - refreshing token and retrying upload_item_image"
            )
            if refresh_token():
                ACCESS_TOKEN = os.getenv("ZOHO_ACCESS_TOKEN")
                return upload_item_image(image, item_id)
            else:
                logging.error("Token refresh failed during upload_item_image")
                return e.response
        else:
            logging.error("API request failed in upload_item_image: %s", e)
            return e.response
    except Exception as e:
        logging.error("Error in upload_item_image: %s", e)
        return None
