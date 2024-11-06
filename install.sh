#!/bin/bash

# Function to print colored output
print_status() {
    echo -e "\e[1;34m[*]\e[0m $1"
}

print_error() {
    echo -e "\e[1;31m[!]\e[0m $1"
}

print_success() {
    echo -e "\e[1;32m[+]\e[0m $1"
}

# Check if script is run as root
if [ "$EUID" -ne 0 ]; then 
    print_error "Please run as root"
    exit 1
fi

# Update package list
print_status "Updating package list..."
apt update

# Install required packages
print_status "Installing required packages..."
apt install -y python3-pip python3-venv curl

# Create ircbot user if it doesn't exist
print_status "Creating ircbot user..."
if id "ircbot" &>/dev/null; then
    print_status "User ircbot already exists"
else
    useradd -r -s /bin/false ircbot
    print_success "Created ircbot user"
fi

# Create and configure directory structure
print_status "Creating directory structure..."
mkdir -p /srv/ircbot
chmod 755 /srv/ircbot

# Download bot files
print_status "Downloading bot files..."
curl -o /srv/ircbot/bot.py https://raw.githubusercontent.com/Longhoern/tl-irc-bot/refs/heads/main/bot.py
curl -o /srv/ircbot/config.yaml https://raw.githubusercontent.com/Longhoern/tl-irc-bot/refs/heads/main/config.yaml

# Set proper permissions
print_status "Setting permissions..."
chown -R ircbot:ircbot /srv/ircbot
chmod 644 /srv/ircbot/bot.py
chmod 644 /srv/ircbot/config.yaml

# Create virtual environment and install dependencies
print_status "Setting up Python virtual environment..."
sudo -u ircbot python3 -m venv /srv/ircbot/venv
/srv/ircbot/venv/bin/pip install irc requests qbittorrent-api discord-webhook pyyaml

# Create systemd service
print_status "Creating systemd service..."
cat > /etc/systemd/system/ircbot.service << 'EOL'
[Unit]
Description=IRC Torrent Monitor Bot
After=network.target

[Service]
Type=simple
User=ircbot
Group=ircbot
WorkingDirectory=/srv/ircbot
ExecStart=/srv/ircbot/venv/bin/python bot.py
Restart=always

[Install]
WantedBy=multi-user.target
EOL

# Reload systemd and enable service
print_status "Configuring systemd service..."
systemctl daemon-reload
systemctl enable ircbot

print_success "Installation complete!"
print_status "Please edit /srv/ircbot/config.yaml with your settings before starting the service"
print_status "You need to configure:"
echo "  - TorrentLeech cookies (tluid and tlpass)"
echo "  - qBittorrent connection details"
echo "  - Discord webhook URL"
echo ""
print_status "To edit the config:"
echo "  sudo vim /srv/ircbot/config.yaml"
echo ""
print_status "Once configured, start the service with:"
echo "  sudo systemctl start ircbot"
echo ""
print_status "To check the status:"
echo "  sudo systemctl status ircbot"
echo "  sudo tail -f /srv/ircbot/bot.log"
