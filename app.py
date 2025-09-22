import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
from dotenv import load_dotenv
import requests
from datetime import datetime, timezone
from helper import *

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# memory cache for odoo stock moves still in progress
in_progress_moves = {}


@app.route("/odoo/webhook", methods=["POST"], strict_slashes=False)
def odoo_webhook():
    """
    Endpoint to receive webhooks from Odoo and update Zoho Inventory item quantity.
    """
    try:
        data = request.json
        model_action = data.get("x_model_action")
        id = data.get("id")
        update_state = data.get("state")
        logging.info("items in memory cache: %s", in_progress_moves)
        # logging.info("Webhook payload: %s", data)

        if not model_action:
            logging.warning("enable Ignoring webhook with missing or empty x_model_action")
            # return (
            #     jsonify(
            #         {"status": "ignored", "message": "Missing or empty x_model_action"}
            #     ),
            #     200,
            # )

        if model_action and model_action.startswith("stock."):

            logging.info("Processing stock adjustment webhook action: %s", model_action)

            # Extract necessary data from the webhook payload
            company_info = data.get("company_id")
            product_info = data.get("product_id")
            location_info = data.get("location_id")
            location_dest_info = data.get("location_dest_id")
            quantity = data.get("product_qty", 0.0)

            # Validate the webhook payload and check if the warehouse is in scope
            if not is_valid_webhook_payload(
                company_info,
                product_info,
                location_info,
                location_dest_info,
                quantity,
            ):
                logging.warning("Invalid webhook payload or warehouse not in scope")
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Invalid webhook payload or warehouse not in scope",
                        }
                    ),
                    400,
                )
            logging.info("Valid webhook payload received")
            

            # Access the second element from the lists
            company_name = company_info[1]
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
                company_name,
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

            # Fetch item ID from Zoho based on product
            item_id = fetch_zoho_item_id(product_name)
            if not item_id:
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
            warehouse_id = get_warehouse_id(company_name)
            logging.info("Using warehouse ID: %s for company: %s", warehouse_id, company_name)
            if not warehouse_id:
                logging.error("Warehouse ID not found for company: %s", company_name)
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Warehouse ID not found for the given company",
                        }
                    ),
                    400,
                )
            
            zoho_data = {
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "reason": "Webhook triggered adjustment",
                "description": f"Adjustment from Odoo for {product_name}",
                "reference_number": f"Webhook-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                "adjustment_type": "quantity",
                "warehouse_id": warehouse_id,
                "line_items": [
                    {
                        "item_id": item_id,
                        "name": product_name,
                        "description": f"Stock updated from Odoo webhook",
                        "quantity_adjusted": quantity,
                        "unit": "pcs",
                        "warehouse_id": warehouse_id,
                    }
                ],
            }
           
            # Call Zoho API to update inventory
            if model_action == "stock.move_confirmed":
                update_response = update_zoho_inventory_stock(item_id, zoho_data)

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
            elif model_action == "stock.move_draft":
                # store in memory cache
                in_progress_moves[id] = zoho_data
                logging.info(
                    "Stored draft stock move in progress cache for id: %s", id
                )
                return (
                    jsonify(
                        {
                            "status": "success",
                            "message": "Draft stock move stored successfully",
                        }
                    ),
                    200,
                )
        elif id in in_progress_moves and update_state == "done":
            # process completed draft move
            logging.info("Processing completed draft stock move for id: %s", id)
            zoho_data = in_progress_moves.pop(id)
            item_id = zoho_data["line_items"][0]["item_id"]
            product_name = zoho_data["line_items"][0]["name"]
            update_response = update_zoho_inventory_stock(item_id, zoho_data)

            if update_response.status_code in [200, 201]:
                logging.info(
                    "Successfully updated Zoho Inventory for item from draft move: %s",
                    product_name,
                )
                return (
                    jsonify(
                        {
                            "status": "success",
                            "message": "Zoho Inventory updated successfully from draft move",
                        }
                    ),
                    200,
                )
            else:
                logging.error(
                    "Failed to update Zoho Inventory from draft move: %s", update_response.text
                )
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "Failed to update Zoho Inventory from draft move",
                        }
                    ),
                    500,
                )
        elif model_action and model_action.startswith("product."):
            # validate required name field for product actions if any
            item_name = data.get("name")
            # check if the zoho_item_payload has an image field
            item_image = data.get("image")
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




if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
