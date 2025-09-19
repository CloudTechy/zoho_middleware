import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Zoho API Configuration loaded from environment variables
ZOHO_API_URL = os.getenv("ZOHO_API_URL")
ACCESS_TOKEN = os.getenv("ZOHO_ACCESS_TOKEN")
ORGANIZATION_ID = os.getenv("ZOHO_ORG_ID")
LOCATION_ID_REQUIRED = int(os.getenv("LOCATION_ID_REQUIRED", 32))  # Default is 32 if not set in .env

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


data = '{"id": 9134, "product_id": [15514, "test product3"], "product_tmpl_id": [17873, "test product3"], "product_uom_id": [1, "Units"], "priority": "0", "company_id": [3, "Surulere Store"], "location_id": [32, "Surul/Stock"], "warehouse_id": [3, "Surulere Store"], "storage_category_id": false, "cyclic_inventory_frequency": 0, "lot_id": false, "sn_duplicated": false, "package_id": false, "owner_id": false, "quantity": 0.0, "reserved_quantity": 0.0, "available_quantity": 0.0, "in_date": "2025-09-19 09:42:27", "tracking": "none", "on_hand": false, "product_categ_id": [1, "All"], "inventory_quantity": 0.0, "inventory_quantity_auto_apply": 0.0, "inventory_diff_quantity": 0.0, "inventory_date": "2025-12-31", "last_count_date": false, "inventory_quantity_set": true, "is_outdated": false, "user_id": false, "__last_update": "2025-09-19 09:42:27.572966", "display_name": "test product3", "create_uid": [2, "Administrator"], "create_date": "2025-09-19 09:42:27.572966", "write_uid": [2, "Administrator"], "write_date": "2025-09-19 09:42:27.572966", "value": 0.0, "currency_id": [121, "NGN"], "accounting_date": false, "cost_method": "standard"}'
@app.route("/odoo/webhook", methods=["POST"], strict_slashes=False)
def odoo_webhook():
    """
    Endpoint to receive webhooks from Odoo and update Zoho Inventory item quantity.
    
    This function will:
    1. Parse the Odoo webhook data.
    2. Check if location_id is 32.
    3. Ensure only positive quantities are sent to Zoho Inventory.
    4. Use item name to find the product in Zoho.
    5. Update Zoho Inventory if all conditions are met.
    6. Log the operation and any errors.
    
    Returns:
        jsonify response indicating success or failure.
    """
    data = request.json  # Capture JSON payload from Odoo webhook
    logging.info("Received webhook from Odoo: %s", data)

    try:
        # Extract relevant fields from the Odoo webhook
        product_name = data.get("product_id", [None])[1]
        quantity = data.get("quantity", 0.0)
        location_id = data.get("location_id", None)
        product_uom_id = data.get("product_uom_id", [None])[0]

        # Check if location_id matches the required value
        if location_id != LOCATION_ID_REQUIRED:
            logging.warning("Ignored webhook: location_id is not %d, it's %d", LOCATION_ID_REQUIRED, location_id)
            return jsonify({"status": "error", "message": f"Location ID must be {LOCATION_ID_REQUIRED}."}), 400

        # Ensure positive quantity before updating Zoho Inventory
        if quantity > 0 and product_name:
            # Search for the item by name in Zoho Inventory
            search_payload = {
                "name": product_name,
                "organization_id": ORGANIZATION_ID
            }

            # Make a GET request to Zoho Inventory API to search for the product by name
            headers = {
                "Authorization": f"Bearer {ACCESS_TOKEN}",
                "Content-Type": "application/json"
            }

            # search_response = request.get(
            #     ZOHO_API_URL,
            #     headers=headers,
            #     params={"organization_id": ORGANIZATION_ID, "name": product_name}
            # )

            # if search_response.status_code == 200:
            #     zoho_items = search_response.json().get("items", [])
            #     if zoho_items:
            #         item_id = zoho_items[0].get("item_id")  # Get the first matching item ID
            #         logging.info("Found Zoho item: %s", zoho_items[0]["name"])

            #         # Prepare the payload for Zoho API (Update Product Quantity)
            #         zoho_payload = {
            #             "inventory_details": [{
            #                 "item_id": item_id,
            #                 "quantity": quantity,
            #                 "uom_id": product_uom_id
            #             }]
            #         }
            #         return jsonify({"status": "success", "message": "Zoho inventory update simulated successfully"}), 200

            #         # Call the Zoho API to update the item quantity
            #         # update_response = request.put(
            #         #     f"{ZOHO_API_URL}{item_id}",
            #         #     headers=headers,
            #         #     params={"organization_id": ORGANIZATION_ID},
            #         #     data=json.dumps(zoho_payload)
            #         # )

            #         # if update_response.status_code == 200:
            #         #     logging.info("Successfully updated Zoho Inventory: Product Name %s, Quantity %f", product_name, quantity)
            #         #     return jsonify({"status": "success", "message": "Zoho inventory updated successfully"}), 200
            #         # else:
            #         #     error_message = update_response.json().get("message", "Unknown error")
            #         #     logging.error("Error updating Zoho Inventory: %s", error_message)
            #         #     return jsonify({"status": "error", "message": error_message}), 500
            #     else:
            #         logging.warning("No matching item found in Zoho for product name: %s", product_name)
            #         return jsonify({"status": "error", "message": f"No item found in Zoho for product: {product_name}"}), 404
            # else:
                error_message = search_response.json().get("message", "Unknown error")
                logging.error("Error searching Zoho Inventory: %s", error_message)
                return jsonify({"status": "error", "message": error_message}), 500
        else:
            logging.warning("Invalid data: quantity is not positive or product name is missing.")
            return jsonify({"status": "error", "message": "Invalid data: quantity must be positive and product name is required."}), 400

    except Exception as e:
        logging.error("An error occurred while processing the Odoo webhook: %s", str(e))
        return jsonify({"status": "error", "message": "Internal Server Error"}), 500


if __name__ == "__main__":
    app.run(port=5000, debug=True)
