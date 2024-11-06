import ssl
import irc.bot
import irc.connection
import requests
from discord_webhook import DiscordWebhook
from qbittorrentapi import Client
import os
import re
import logging
from pathlib import Path
import yaml
from datetime import datetime, timedelta
import time

class TorrentBot(irc.bot.SingleServerIRCBot):
    def __init__(self, config):
        self.config = config
        ssl_factory = irc.connection.Factory(wrapper=ssl.wrap_socket)
        super().__init__(
            [(config['irc']['server'], config['irc']['port'])],
            config['irc']['nickname'],
            config['irc']['nickname'],
            connect_factory=ssl_factory
        )
        
        self.qbt_client = Client(
            host=config['qbittorrent']['host'],
            port=config['qbittorrent']['port'],
            username=config['qbittorrent']['username'],
            password=config['qbittorrent']['password']
        )
        
        # Define search criteria
        self.search_terms = [
            {'resolution': '1080p', 'category': 'HD-1080p'},
            {'resolution': '720p', 'category': 'HD-720p'}
        ]
        
        self.download_path = Path(config['paths']['download_dir'])
        self.download_path.mkdir(parents=True, exist_ok=True)
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(config['paths']['log_file']),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        # Initialize session
        self._session = requests.Session()
        
        # Validate cookies before starting
        if not self.validate_cookies():
            raise Exception("TorrentLeech cookies are invalid or expired")
        
        # Start cookie check thread
        self.should_run = True
        import threading
        self.cookie_check_thread = threading.Thread(target=self.periodic_cookie_check)
        self.cookie_check_thread.daemon = True
        self.cookie_check_thread.start()

    def validate_cookies(self):
        """Validate TorrentLeech cookies by making a test request"""
        try:
            self.logger.info("Testing TorrentLeech cookies...")
            self.logger.info(f"Using cookies - tluid: {self.config['torrentleech']['cookies']['tluid'][:4]}... " 
                           f"tlpass: {self.config['torrentleech']['cookies']['tlpass'][:4]}...")
            
            # Get initial PHPSESSID
            init_response = self._session.get('https://www.torrentleech.org', allow_redirects=False)
            
            cookies = {
                'tluid': self.config['torrentleech']['cookies']['tluid'],
                'tlpass': self.config['torrentleech']['cookies']['tlpass']
            }
            
            if 'PHPSESSID' in self._session.cookies:
                cookies['PHPSESSID'] = self._session.cookies['PHPSESSID']
                
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Connection': 'keep-alive',
            }
            
            # Try to access the main page
            response = self._session.get(
                'https://www.torrentleech.org/',
                cookies=cookies,
                headers=headers,
                allow_redirects=False
            )
            
            self.logger.info(f"TorrentLeech response status: {response.status_code}")
            
            if response.status_code == 302:
                location = response.headers.get('Location', '')
                if 'login' in location.lower():
                    self.logger.error("Cookie validation failed: Redirected to login page")
                    return False
                    
            if response.status_code != 200:
                self.logger.error(f"Cookie validation failed: Unexpected status code {response.status_code}")
                return False
            
            self.logger.info("Cookie validation successful!")
            return True
                
        except Exception as e:
            self.logger.error(f"Error validating cookies: {str(e)}")
            return False

    def periodic_cookie_check(self):
        """Periodically check cookie validity and send notifications"""
        while self.should_run:
            if not self.validate_cookies():
                # Send Discord notification about invalid cookies
                webhook = DiscordWebhook(
                    url=self.config['discord']['webhook_url'],
                    content="⚠️ TorrentLeech cookies have expired! Please update them to continue downloading torrents."
                )
                webhook.execute()
                
                # Wait longer between checks if cookies are invalid
                time.sleep(3600)  # Check once per hour when invalid
            else:
                # Check every 6 hours when valid
                time.sleep(21600)

    def on_welcome(self, connection, event):
        self.logger.info(f"Connected to {self.config['irc']['server']}")
        connection.join(self.config['irc']['channel'])
        self.logger.info(f"Joined channel {self.config['irc']['channel']}")

    def on_pubmsg(self, connection, event):
        if event.source.nick != self.config['irc']['announce_bot']:
            return

        message = event.arguments[0].lower()
        
        # Check for freeleech first as it's required for all
        if 'freeleech' not in message:
            return
            
        # Check for any matching resolution
        for search_term in self.search_terms:
            if search_term['resolution'] in message:
                self.logger.info(f"Found matching {search_term['resolution']} freeleech announcement")
                
                # Extract torrent ID using regex
                torrent_link_match = re.search(r'torrentleech\.org/torrent/(\d+)', message)
                if not torrent_link_match:
                    self.logger.warning("Could not extract torrent ID from message")
                    return
                
                torrent_id = torrent_link_match.group(1)
                self.process_torrent(torrent_id, search_term['category'])
                # Break after first match as a torrent won't be both 720p and 1080p
                break

    def process_torrent(self, torrent_id, category):
        # Validate cookies before attempting download
        if not self.validate_cookies():
            self.logger.error("Skipping torrent download - cookies are invalid")
            return
            
        # Construct download URL
        download_url = f"https://www.torrentleech.org/download/{torrent_id}/*.torrent"
        
        try:
            # Use the stored session for downloads
            response = self._session.get(
                download_url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                }
            )
            response.raise_for_status()
            
            # Save torrent file
            torrent_path = self.download_path / f"{torrent_id}.torrent"
            torrent_path.write_bytes(response.content)
            self.logger.info(f"Downloaded torrent file to {torrent_path}")
            
            # Add to qBittorrent with the appropriate category
            self.qbt_client.torrents_add(
                torrent_files=str(torrent_path),
                category=category
            )
            self.logger.info(f"Added torrent to qBittorrent with category: {category}")
            
            # Wait a moment for torrent to be added
            time.sleep(2)
            
            # Get the torrent hash from qBittorrent
            torrents = self.qbt_client.torrents_info(category=category)
            for torrent in torrents:
                if torrent.state in ['stalledDL', 'pausedDL', 'missingFiles']:
                    self.logger.info(f"Force rechecking torrent: {torrent.name}")
                    self.qbt_client.torrents_recheck(torrent.hash)
            
            # Construct torrent info URL
            torrent_url = f"https://www.torrentleech.org/torrent/{torrent_id}#torrentinfo"
            
            # Send Discord notification with torrent link
            webhook = DiscordWebhook(
                url=self.config['discord']['webhook_url'],
                content=f"New torrent added: {torrent_url}"
            )
            webhook.execute()
            self.logger.info("Sent Discord notification")
            
            # Clean up torrent file
            torrent_path.unlink()
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401 or e.response.status_code == 403:
                self.logger.error("Authentication failed - cookies may have expired")
                webhook = DiscordWebhook(
                    url=self.config['discord']['webhook_url'],
                    content="⚠️ TorrentLeech authentication failed! Please update cookies."
                )
                webhook.execute()
            else:
                self.logger.error(f"Error downloading torrent {torrent_id}: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error processing torrent {torrent_id}: {str(e)}")

    def stop(self):
        """Clean shutdown of the bot"""
        self.should_run = False
        super().die()

def load_config():
    config_path = Path(__file__).parent / 'config.yaml'
    with open(config_path) as f:
        return yaml.safe_load(f)

if __name__ == "__main__":
    config = load_config()
    bot = TorrentBot(config)
    try:
        bot.start()
    except KeyboardInterrupt:
        bot.stop()