from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
from dotenv import load_dotenv
import requests
from datetime import datetime, timezone
from helper import *
import os
import ast


# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
WAREHOUSE_ODOO_ID_MAP = os.getenv(
    "WAREHOUSE_ODOO_ID_MAP", {"4167669000195495001": "32", "4167669000000923299": "22"}
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
            logging.warning(
                "enable Ignoring webhook with missing or empty x_model_action"
            )
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
            logging.info(
                "Using warehouse ID: %s for company: %s", warehouse_id, company_name
            )
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
                logging.info("Stored draft stock move in progress cache for id: %s", id)
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
                    "Failed to update Zoho Inventory from draft move: %s",
                    update_response.text,
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


@app.route("/zoho/webhook", methods=["POST"], strict_slashes=False)
def zoho_webhook():
    logging.info("Received Zoho Inventory webhook request")
    try:
        data = request.get_json()

        inventory_adjustment = data.get('inventory_adjustment')
        if inventory_adjustment is None:
            logging.warning("Unrecognized webhook payload")
            return (
                jsonify({"status": "ignored", "message": "Empty payload"}),
                200,
            )

        line_items = inventory_adjustment.get('line_items', [])[0]
        logging.info("Webhook item ID: %s", line_items.get("item_id"))
        logging.info("Webhook warehouse ID: %s", line_items.get("warehouse_id"))
        logging.info("Webhook quantity adjusted: %s", line_items.get("quantity_adjusted"))

        if not line_items.get("item_id") or not line_items.get("warehouse_id") or not line_items.get("quantity_adjusted"):
            logging.warning("Ignoring webhook with missing required fields")
            return (
                jsonify({"status": "ignored", "message": "Missing required fields"}),
                200,
            )

        item_id = line_items.get("item_id")
        warehouse_id = line_items.get("warehouse_id")
        quantity = line_items.get("quantity_adjusted")

        # Fetch item from Zoho
        zoho_item = fetch_zoho_item(item_id)
        warehouses = zoho_item.get("warehouses")
        warehouse = next((w for w in warehouses if w.get("warehouse_id") == warehouse_id), None)

        if not warehouse:
            logging.warning("Warehouse ID %s not found in Zoho item warehouses", warehouse_id)
            return (
                jsonify({"status": "error", "message": "Warehouse ID not found in Zoho item"}),
                404,
            )

        # Map warehouse ID to Odoo location ID
        if isinstance(WAREHOUSE_ODOO_ID_MAP, str):
            warehouse_mapping = ast.literal_eval(WAREHOUSE_ODOO_ID_MAP)
        else:
            warehouse_mapping = WAREHOUSE_ODOO_ID_MAP

        if warehouse_id not in warehouse_mapping:
            logging.warning("Warehouse ID %s not in scope, ignoring webhook", warehouse_id)
            return (
                jsonify({"status": "ignored", "message": "Warehouse ID not in scope"}),
                200,
            )

        warehouse_odooid = int(warehouse_mapping.get(warehouse_id))
        logging.info("Mapped Zoho warehouse ID %s to Odoo warehouse ID %s", warehouse_id, warehouse_odooid)

        # Get product in Odoo
        product_name = zoho_item.get("name", "").strip()
        logging.info("Looking up product in Odoo using name: %s", product_name)

        product_result = call_odoo(
            "search_read",
            "product.product",
            [[["name", "=", product_name]]],
            {"fields": ["id", "name"]}
        )

        if not product_result:
            logging.error("Product with name %s not found in Odoo", product_name)
            return jsonify({"status": "error", "message": "Product not found"}), 404

        product_id = product_result[0]["id"]
        logging.info("Found Odoo product ID: %s for name: %s", product_id, product_name)

        # Find stock quant in Odoo
        stock_quant_result = call_odoo(
            "search_read",
            "stock.quant",
            [[["product_id", "=", product_id], ["location_id", "=", warehouse_odooid]]],
            {"fields": ["id", "quantity"]}
        )

        quant_ids = [record["id"] for record in stock_quant_result] if stock_quant_result else []
        odoo_quantity = float(stock_quant_result[0]["quantity"]) if stock_quant_result else 0.0
        zoho_quantity = float(warehouse.get("warehouse_stock_on_hand", 0))

        logging.info("Odoo quantity at location %s: %s", warehouse_odooid, odoo_quantity)
        logging.info("Zoho warehouse quantity: %s", zoho_quantity)

        # ✅ Skip if quantities are equal
        if round(odoo_quantity, 2) == round(zoho_quantity, 2):
            logging.info(
                "No update needed. Odoo stock (%s) matches Zoho stock (%s) at location %s",
                odoo_quantity,
                zoho_quantity,
                warehouse_odooid
            )
            return jsonify({"status": "skipped", "message": "Stock already up-to-date"}), 200

        # ✅ Update if Odoo record exists
        if quant_ids:
            quant_id = quant_ids[0]
            logging.info("Updating stock quant ID %s to quantity %s (auto-apply)", quant_id, quantity)

            update_result = call_odoo(
                "write",
                "stock.quant",
                [[quant_id], {
                    "quantity": quantity,
                    "inventory_quantity_auto_apply": True
                }]
            )

            if not update_result:
                logging.error("Failed to update stock quantity via auto-apply")
                return jsonify({"status": "error", "message": "Failed to update stock"}), 500

            logging.info("Successfully updated stock for product ID %s", product_id)
            return jsonify({"status": "done", "message": "Webhook processed successfully"}), 200

        # ✅ Create if no existing quant
        else:
            logging.info("Stock quant not found. Creating new quant for product %s in location %s", product_id, warehouse_odooid)

            create_result = call_odoo(
                "create",
                "stock.quant",
                [{
                    "product_id": product_id,
                    "location_id": warehouse_odooid,
                    "quantity": zoho_quantity,
                    "inventory_quantity_auto_apply": True
                }]
            )

            if not create_result:
                logging.error("Failed to create stock quant for product %s in location %s", product_id, warehouse_odooid)
                return jsonify({"status": "error", "message": "Failed to create stock quant"}), 500

            logging.info("Successfully created and applied stock quant for product ID %s", product_id)
            return jsonify({"status": "done", "message": "Webhook processed successfully"}), 200

    except Exception as e:
        logging.error("Error processing webhook request: %s", traceback.format_exc())
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
