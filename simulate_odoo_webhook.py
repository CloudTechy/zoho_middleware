import json
import os
import logging

# Optional: use dotenv for token/organization_id if needed
from dotenv import load_dotenv
load_dotenv()

# Logging config
logging.basicConfig(level=logging.INFO)

# Constants / Mock config
REQUIRED_LOCATION_ID = 32
MOCK_ZOHO_ITEM_ID = "9876543210"

# Optional: Use real values from env
ZOHO_ACCESS_TOKEN = os.getenv("ZOHO_ACCESS_TOKEN")
ZOHO_ORG_ID = os.getenv("ZOHO_ORG_ID")

def load_odoo_webhook_payload(filepath: str) -> dict:
    """Load JSON payload from file."""
    with open(filepath, 'r') as f:
        return json.load(f)

def process_odoo_webhook(data: dict, simulate=True):
    """Process a webhook payload as if received from Odoo."""
    try:
        location = data.get("location_id")
        product_info = data.get("product_id")
        uom_info = data.get("product_uom_id")
        quantity = data.get("quantity", 0.0)

        # Validate required fields
        if not (
            isinstance(location, list) and location[0] == REQUIRED_LOCATION_ID and
            isinstance(product_info, list) and len(product_info) >= 2 and
            isinstance(uom_info, list) and len(uom_info) >= 1 and
            isinstance(quantity, (int, float)) and quantity > 0
        ):
            logging.warning("Invalid webhook — skipping")
            return

        product_name = product_info[1]
        product_uom_id = uom_info[0]

        logging.info("Processing webhook for product: %s", product_name)

        # Simulate Zoho item search
        logging.info("Simulating Zoho search for: %s", product_name)

        zoho_item_id = MOCK_ZOHO_ITEM_ID  # replace with actual search if needed

        # Build update payload
        update_payload = {
            "inventory_details": [{
                "item_id": zoho_item_id,
                "quantity": quantity,
                "uom_id": product_uom_id
            }]
        }

        if simulate:
            logging.info("Simulated update payload:\n%s", json.dumps(update_payload, indent=2))
        else:
            logging.info("Would perform real Zoho update here...")

            # You could insert live Zoho API logic here
            # e.g., requests.put(...) with headers/auth
            pass

        logging.info("Webhook processing complete.")

    except Exception as e:
        logging.exception("Error processing simulated webhook: %s", e)

# === Entry point ===
if __name__ == "__main__":
    sample_file = "sample_odoo_webhook.json"
    logging.info("Loading sample Odoo webhook from file: %s", sample_file)
    payload = load_odoo_webhook_payload(sample_file)
    process_odoo_webhook(payload, simulate=True)  # Set simulate=False to go live later
