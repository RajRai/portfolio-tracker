https://portfolios.rajrai.net

# How to use

>*Pre-requisite:* Export your Fidelity account history CSV's from the "Activity & Orders" section. The date ranges for the reports are allowed to overlap; duplicate transactions are filtered.

**1. Pull the container**

`docker pull docker.rajrai.net/portfolio-tracker`

**2. Set your API key**

Create a `.env` file (or export the variable directly):

```bash
echo "POLYGON_API_KEY=your_api_key_here" > .env
```

Alternatively, you can export it inline when running the container.

---

**3. Prepare your data directory**
> *Note*: There's a bash script below which automates this.

Create a local folder (or reuse an existing one) to hold your portfolios, reports, and CSV files:

The structure inside should look like this:

```
data/
├── accounts.json
├── <account_id_1>/
│   └── statements/
│       ├── statement_2024-01.csv
│       ├── statement_2024-02.csv
│       └── ...
├── <account_id_2>/
│   └── statements/
│       ├── statement_2024-03.csv
│       └── ...
└── ...
```

**Details:**
- `accounts.json` — defines the list of accounts and their display names:
  ```json
  [
    { "id": "ABCDEFG", "name": "Cloud, Semiconductors, Energy, Utilities" },
    { "id": "HIJKLMNOP", "name": "Optical Computing" },
    { "id": "QRSTUVWXYZ", "name": "All Trading History" }
  ]
  ```
- The UI also supports an optional `about` field on each portfolio entry in `accounts.json`. When provided, that text is shown in the "About this portfolio" modal and supports escaped newlines such as `\n`; portfolios without about text do not show the link.
- Each `<account_id>/statements/` folder contains one or more CSV statements exported from Fidelity.
    - File names don’t matter — they are auto-discovered.
    - Each account must have its own `statements/` subdirectory.

###### Script

```bash
#!/usr/bin/env bash
set -e

# ============================================================
# Configuration
# ============================================================

DATA_DIR="data"

# Define accounts (id → name)
declare -A ACCOUNTS=(
  ["ABCDEFG"]="Cloud, Semiconductors, Energy, Utilities"
  ["HIJKLMNOP"]="Optical Computing"
  ["QRSTUVWXYZ"]="All Trading History"
)

# ============================================================
# Create directory structure
# ============================================================

echo "📁 Creating data directory structure..."
mkdir -p "$DATA_DIR"

for ACCOUNT_ID in "${!ACCOUNTS[@]}"; do
  mkdir -p "$DATA_DIR/$ACCOUNT_ID/statements"
  echo "  - Created $DATA_DIR/$ACCOUNT_ID/statements"
done

# ============================================================
# Write accounts.json
# ============================================================

ACCOUNTS_JSON="$DATA_DIR/accounts.json"
echo "📝 Writing $ACCOUNTS_JSON..."

{
  echo "["
  i=0
  total=${#ACCOUNTS[@]}
  for ACCOUNT_ID in "${!ACCOUNTS[@]}"; do
    NAME=${ACCOUNTS[$ACCOUNT_ID]}
    ((i++))
    COMMA=$([ $i -lt $total ] && echo "," || echo "")
    echo "  { \"id\": \"$ACCOUNT_ID\", \"name\": \"$NAME\" }$COMMA"
  done
  echo "]"
} > "$ACCOUNTS_JSON"

echo "✅ Setup complete: $DATA_DIR/"
```

---

**4. Run the container**

Use Docker’s CLI to bind ports, mount the data path, and pass environment variables:

```bash
docker run \
  -p 5000:8000 \
  -v "$(pwd)/data:/app/data" \
  --env-file .env.template \
  fidelity-portfolio-tracker
```

Then open [http://localhost:5000](http://localhost:5000) to access the dashboard.
