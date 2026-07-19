#!/bin/bash

# --- COLOR PIPELINES FOR TEXT ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}===========================================${NC}"
echo -e "${YELLOW}   Fish Feeder Systemd Service Installer   ${NC}"
echo -e "${YELLOW}===========================================${NC}"

# 1. Detect environment variables dynamically
CURRENT_USER=$(whoami)
CURRENT_DIR=$(pwd)
SERVICE_FILE="/etc/systemd/system/fishfeeder.service"

echo -e "Detecting Environment..."
echo -e "Current User: ${GREEN}$CURRENT_USER${NC}"
echo -e "Working Directory: ${GREEN}$CURRENT_DIR${NC}"

# Check if app.py exists in this directory before proceeding
if [ ! -f "$CURRENT_DIR/app.py" ]; then
    echo -e "${RED}Error: app.py not found in $CURRENT_DIR!${NC}"
    echo -e "Please run this script from inside your project folder containing app.py."
    exit 1
fi

# 2. Install Python Core Dependencies Automatically
echo -e "\n${YELLOW}Checking and installing required Python system packages...${NC}"
echo -e "This might take a minute on a Pi Zero..."
sudo apt update -y
# ffmpeg is required to turn the recorded feed clip into an animated GIF.
sudo apt install python3-pip python3-flask python3-gpiozero python3-pil ffmpeg -y

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✔ System dependencies installed perfectly!${NC}"
else
    echo -e "${RED}❌ Failed to install dependencies. Check your internet connection.${NC}"
    exit 1
fi

# 2.5 Initialize persistent data resources (no database needed — plain files)
echo -e "\n${YELLOW}Initializing data resources...${NC}"

# Photos directory for feed confirmation snapshots
mkdir -p "$CURRENT_DIR/photos"

# Feeding log (timestamp,filename per line)
touch "$CURRENT_DIR/database.txt"

# Feeding schedule stored as JSON (created empty only if it doesn't exist yet)
if [ ! -f "$CURRENT_DIR/schedule.json" ]; then
    echo '{"entries": []}' > "$CURRENT_DIR/schedule.json"
    echo -e "${GREEN}✔ Created empty schedule.json${NC}"
else
    echo -e "${GREEN}✔ Existing schedule.json preserved${NC}"
fi

# Make sure the service user owns these files (script may be run with sudo)
sudo chown -R "$CURRENT_USER":"$CURRENT_USER" "$CURRENT_DIR/photos" "$CURRENT_DIR/database.txt" "$CURRENT_DIR/schedule.json"

echo -e "${GREEN}✔ Data resources ready!${NC}"

# 3. Construct the systemd service file dynamically
echo -e "\nWriting systemd configuration to ${SERVICE_FILE}..."
sudo bash -c "cat << EOF > $SERVICE_FILE
[Unit]
Description=Automated Fish Feeder Web Server
After=network.target

[Service]
ExecStart=/usr/bin/python3 $CURRENT_DIR/app.py
WorkingDirectory=$CURRENT_DIR
StandardOutput=inherit
StandardError=inherit
Restart=always
RestartSec=5
User=$CURRENT_USER

[Install]
WantedBy=multi-user.target
EOF"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✔ Service file written successfully!${NC}"
else
    echo -e "${RED}❌ Failed to write service file.${NC}"
    exit 1
fi

# 4. Register and start the background engine
echo -e "\nRegistering and enabling the service..."
sudo systemctl daemon-reload
sudo systemctl enable fishfeeder.service
sudo systemctl restart fishfeeder.service

# 5. Verification Check Routine
echo -e "\n${YELLOW}Verifying initialization status...${NC}"
sleep 3 # Give Python a few seconds to parse dependencies and mount the network port

SERVICE_STATUS=$(sudo systemctl is-active fishfeeder.service)

if [ "$SERVICE_STATUS" = "active" ]; then
    echo -e "${GREEN}===========================================${NC}"
    echo -e "${GREEN}SUCCESS: The Fish Feeder Service is RUNNING!${NC}"
    echo -e "${GREEN}===========================================${NC}"
    echo -e "Your web application will now launch automatically every time the Pi boots up."
    echo -e "Check your browser at: ${YELLOW}http://$(hostname -I | awk '{print $1}'):5000${NC}"
else
    echo -e "${RED}===========================================${NC}"
    echo -e "${RED}WARNING: Service failed to enter an active state.${NC}"
    echo -e "${RED}===========================================${NC}"
    echo -e "Current Status Reported: ${RED}$SERVICE_STATUS${NC}"
    echo -e "To view error diagnostics, execute: ${YELLOW}sudo journalctl -u fishfeeder.service -n 20${NC}"
fi
