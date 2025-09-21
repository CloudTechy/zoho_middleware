```markdown
# 🔄 Zoho-Odoo Integration Middleware

This middleware integrates Odoo with Zoho Inventory, syncing product data and inventory updates in real time using webhook payloads from Odoo.

## 📦 Features

- Validates incoming webhook payloads from Odoo
- Adjusts inventory quantities based on stock movement
- Creates and updates products in Zoho Inventory
- Automatically refreshes Zoho OAuth tokens on expiry
- Supports multi-warehouse setup (e.g., Surulere and Lekki)

## 🚀 Getting Started

### 📁 Project Structure

```

zoho\_middleware/
├── app.py
├── helper.py
├── .env
├── requirements.txt
└── README.md

````

### 🔧 Requirements

- Python 3.10+
- Access to Zoho Inventory API
- Valid Zoho OAuth credentials (client ID, client secret, refresh token)
- Webhook source from Odoo

### 📥 Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/CloudTechy/zoho_middleware.git
   cd zoho_middleware
````

2. Create and activate a virtual environment:

   ```bash
   python -m venv venv
   venv\Scripts\activate    # On Windows
   # or
   source venv/bin/activate  # On macOS/Linux
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file and add the required environment variables (see below).

---

## 🔐 Environment Variables (`.env`)

```env
# Zoho API Base URLs
ZOHO_API_URL=https://www.zohoapis.com/inventory/v1
ZOHO_REFRESH_URL=https://accounts.zoho.com/oauth/v2/token

# Zoho OAuth Tokens and Org ID
ZOHO_ACCESS_TOKEN=your_initial_access_token
ZOHO_REFRESH_TOKEN=your_refresh_token
ZOHO_CLIENT_ID=your_client_id
ZOHO_CLIENT_SECRET=your_client_secret
ZOHO_ORG_ID=your_org_id

# Warehouses (Required for location mapping)
WAREHOUSE_REQUIRED=Surulere Store,Lekki Store
LOCATION_NAME_REQUIRED=Surul/Stock,Lekki/Stock

# Warehouse IDs (from Zoho)
ZOHO_WAREHOUSE_SURULERE_ID=123456789012345
ZOHO_WAREHOUSE_LEKKI_ID=987654321098765
```

---

## 🧠 Key Functions

### From `helper.py`

* `is_valid_webhook_payload(...)` – Validates required fields from the payload
* `get_adjusted_quantity(...)` – Determines inventory adjustment quantity
* `fetch_zoho_item_id(...)` – Retrieves Zoho item ID and warehouse ID
* `update_zoho_inventory(...)` – Adjusts inventory in Zoho
* `create_zoho_item(...)` – Creates new items in Zoho based on Odoo payload
* `refresh_token()` – Refreshes the Zoho OAuth access token when expired

---

## ▶️ Running the Middleware

```bash
python app.py
```

Ensure your webhook server is running or Odoo is configured to send payloads to this application.

---

## ✅ Best Practices

* Always secure your `.env` file and **never** commit it to version control
* Use proper exception handling in your `app.py` to handle invalid payloads
* Enable HTTPS for production webhook endpoints
* Set up logging to a file for better traceability

---

## 🛠️ TODO

* Add unit tests
* Add database logging of payloads
* Enable item update support
* Improve warehouse ID mapping flexibility

---

## 📄 License

This project is licensed under the MIT License.

---

## 🙌 Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss what you would like to change.

```

---

