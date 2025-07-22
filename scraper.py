"""
RTanks Online Website Scraper
Handles scraping player data from the RTanks ratings website.
"""

import aiohttp
import asyncio
from bs4 import BeautifulSoup
import random
import re
import logging
from urllib.parse import quote
import json

logger = logging.getLogger(__name__)

class RTanksScraper:
    def __init__(self):
        self.base_url = "https://ratings.ranked-rtanks.online"
        self.session = None
        
        # Headers to avoid bot detection
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
        }
        
    async def _get_session(self):
        """Get or create an aiohttp session."""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                headers=self.headers
            )
        return self.session
    
    async def get_player_data(self, username):
        """
        Scrape player data from the RTanks ratings website.
        Returns a dictionary with player information or None if not found.
        """
        try:
            session = await self._get_session()
            
            # Add random delay to avoid rate limiting
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
            # Try the correct URL pattern for RTanks
            possible_urls = [
                f"{self.base_url}/user/{quote(username)}"
            ]
            
            player_data = None
            for url in possible_urls:
                try:
                    async with session.get(url) as response:
                        if response.status == 200:
                            html = await response.text()
                            player_data = await self._parse_player_data(html, username)
                            if player_data:
                                break
                        elif response.status == 404:
                            continue
                        else:
                            logger.warning(f"Unexpected status code {response.status} for {url}")
                            continue
                            
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout while fetching {url}")
                    continue
                except Exception as e:
                    logger.error(f"Error fetching {url}: {e}")
                    continue
            
            if not player_data:
                # Try searching the main page for the player
                player_data = await self._search_player_on_main_page(username)
            
            return player_data
            
        except Exception as e:
            logger.error(f"Error in get_player_data: {e}")
            return None
    
    async def _parse_player_data(self, html, username):
        """Parse player data from HTML response."""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            logger.info(f"Parsing data for {username}")
            
            # CRITICAL FIX: Check if this is actually a valid player page
            # First check for error indicators that show player doesn't exist
            error_indicators = [
                'player not found' in html.lower(),
                'user not found' in html.lower(),  
                'not found' in html.lower() and len(html) < 5000,  # Short error page
                '404' in html and 'error' in html.lower(),
                'пользователь не найден' in html.lower(),  # Russian "user not found"
                soup.find(text=re.compile(r'404|not found|error', re.IGNORECASE)) and len(html) < 3000,
                # Check if page redirects back to main site (common for non-existent players)
                f'{self.base_url}/' == f'{self.base_url}/user/{quote(username)}',  # redirect check
            ]
            
            # If we find error indicators, return None immediately
            if any(error_indicators):
                logger.info(f"Player {username} not found - error page detected")
                return None
            
            # ENHANCED CHECK: Look for actual player profile structure
            # Check for specific profile elements that indicate a real player
            profile_structure_indicators = [
                # Look for profile container or user profile elements
                soup.find(class_=re.compile(r'profile|user-info|player-card', re.IGNORECASE)),
                soup.find(id=re.compile(r'profile|user|player', re.IGNORECASE)),
                # Look for elements that would contain player stats
                soup.find(text=re.compile(r'Activity|Активность', re.IGNORECASE)),
                soup.find(text=re.compile(r'Combat Stats|Статистика боя', re.IGNORECASE)),
            ]
            
            # STRICT CHECK: Look for default/template data that indicates fake profile
            default_data_indicators = [
                # Check for exact default values that appear for non-existent users
                re.search(r'14/400', html),  # Default experience pattern
                re.search(r'Kills:\s*0.*Deaths:\s*0.*K/D:\s*0\.00', html, re.DOTALL),  # Default combat stats
                re.search(r'Group:\s*Unknown', html),  # Default group
                # Check if rank is exactly "Recruit" with 14/400 experience (template data)
                re.search(r'Recruit.*14/400', html, re.DOTALL),
            ]
            
            # If we find default/template data patterns, it's likely a fake profile
            if any(default_data_indicators):
                logger.info(f"Player {username} not found - template/default data detected")
                return None
            
            # Look for meaningful player data that goes beyond defaults
            meaningful_data_patterns = [
                # Look for non-zero, non-default stats
                r'[Kk]ills?[:\s]*([1-9]\d*)',  # Non-zero kills
                r'[Dd]eaths?[:\s]*([1-9]\d*)',  # Non-zero deaths  
                r'(\d{1,3}(?:\s?\d{3})*)\s*/\s*(\d{1,3}(?:\s?\d{3})*)',  # Experience format
                # Look for ranks other than default Recruit
                r'(Private|Gefreiter|Corporal|Sergeant|Lieutenant|Captain|Major|Colonel|General|Marshal|Commander|Legend)',
            ]
            
            has_meaningful_data = False
            for pattern in meaningful_data_patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    # Additional check: if it's experience format, ensure it's not the default 14/400
                    if '/' in pattern and match:
                        current_exp = match.group(1).replace(',', '').replace(' ', '')
                        if current_exp != '14':  # Not default experience
                            has_meaningful_data = True
                            break
                    else:
                        has_meaningful_data = True
                        break
            
            if not has_meaningful_data:
                logger.info(f"Player {username} not found - no meaningful data beyond defaults")
                return None
            
            # If we reach here, we have a valid player page - initialize data
            player_data = {
                'username': username,
                'rank': 'Unknown',
                'experience': 0,
                'kills': 0,
                'deaths': 0,
                'kd_ratio': '0.00',
                'gold_boxes': 0,
                'premium': False,
                'group': 'Unknown',
                'is_online': False,
                'status_indicator': '🔴',
                'equipment': {'turrets': [], 'hulls': []}
            }
            
            # Parse activity status from non-displayable span with yes/no text
            # According to website owner: activity is in a non-displayable span with text "yes/no"
            activity_spans = soup.find_all('span', style=re.compile(r'display:\s*none', re.IGNORECASE))
            is_online = False
            
            # Look for spans with "yes" or "no" text content
            for span in activity_spans:
                if span.get_text(strip=True).lower() == 'yes':
                    is_online = True
                    logger.info(f"Found activity span with 'yes' - {username} is ONLINE")
                    break
                elif span.get_text(strip=True).lower() == 'no':
                    is_online = False
                    logger.info(f"Found activity span with 'no' - {username} is OFFLINE")
                    break
            
            # Fallback: also check for hidden spans without explicit display:none style
            if not any(span.get_text(strip=True).lower() in ['yes', 'no'] for span in activity_spans):
                all_spans = soup.find_all('span')
                for span in all_spans:
                    span_text = span.get_text(strip=True).lower()
                    if span_text == 'yes':
                        is_online = True
                        logger.info(f"Found span with 'yes' text - {username} is ONLINE")
                        break
                    elif span_text == 'no':
                        is_online = False
                        logger.info(f"Found span with 'no' text - {username} is OFFLINE")
                        break
            
            player_data['is_online'] = is_online
            player_data['status_indicator'] = '🟢' if is_online else '🔴'
            logger.info(f"{username} activity status: {'ONLINE' if is_online else 'OFFLINE'}")
            
            # Parse experience FIRST - Look for current/max format like "105613/125000"
            exp_patterns = [
                r'(\d{1,3}(?:\s?\d{3})*)\s*/\s*(\d{1,3}(?:\s?\d{3})*)',  # Current/max format with spaces
                r'(\d{1,3}(?:,\d{3})*)\s*/\s*(\d{1,3}(?:,\d{3})*)',     # Current/max format with commas
                r'(\d+)\s*/\s*(\d+)',                                     # Simple current/max format
            ]
            
            # First try to find current/max experience format
            exp_found = False
            for pattern in exp_patterns:
                exp_match = re.search(pattern, html)
                if exp_match:
                    current_exp_str = exp_match.group(1).replace(',', '').replace(' ', '')
                    max_exp_str = exp_match.group(2).replace(',', '').replace(' ', '')
                    try:
                        player_data['experience'] = int(current_exp_str)
                        player_data['max_experience'] = int(max_exp_str)
                        exp_found = True
                        logger.info(f"Found experience: {player_data['experience']}/{player_data['max_experience']}")
                        break
                    except ValueError:
                        continue
            
            # If current/max format not found, try single experience value
            if not exp_found:
                single_exp_patterns = [
                    r'Experience[^0-9]*(\d{1,3}(?:,?\d{3})*)',
                    r'Опыт[^0-9]*(\d{1,3}(?:,?\d{3})*)',
                    r'"experience"[^0-9]*(\d{1,3}(?:,?\d{3})*)'
                ]
                
                for pattern in single_exp_patterns:
                    exp_match = re.search(pattern, html, re.IGNORECASE)
                    if exp_match:
                        exp_str = exp_match.group(1).replace(',', '').replace(' ', '')
                        player_data['experience'] = int(exp_str)
                        logger.info(f"Found single experience: {player_data['experience']}")
                        break
            
            # Parse rank - Enhanced detection with experience-based fallback
            rank_patterns = [
                r'(Легенда|Legend)\s*(\d*)',
                r'(Генералиссимус|Generalissimo)',
                r'(Командир бригады|Brigadier Commander)',
                r'(Командир полковник|Colonel Commander)',
                r'(Командир подполковник|Lieutenant Colonel Commander)',
                r'(Командир майор|Major Commander)',
                r'(Командир капитан|Captain Commander)',
                r'(Командир лейтенант|Lieutenant Commander)',
                r'(Командир|Commander)',
                r'(Фельдмаршал|Field Marshal)',
                r'(Маршал|Marshal)',
                r'(Генерал|General)',
                r'(Генерал-лейтенант|Lieutenant General)',
                r'(Генерал-майор|Major General)',
                r'(Бригадир|Brigadier)',
                r'(Полковник|Colonel)',
                r'(Подполковник|Lieutenant Colonel)',
                r'(Майор|Major)',
                r'(Капитан|Captain)',
                r'(Старший лейтенант|First Lieutenant)',
                r'(Лейтенант|Second Lieutenant)',
                r'(Старший прапорщик|Master Warrant Officer)',
                r'(Прапорщик|Warrant Officer)',
                r'(Старшина|Sergeant Major)',
                r'(Старший сержант|First Sergeant)',
                r'(Сержант|Master Sergeant)',
                r'(Младший сержант|Staff Sergeant)',
                r'(Ефрейтор|Sergeant)',
                r'(Старший ефрейтор|Master Corporal)',
                r'(Капрал|Corporal)',
                r'(Гефрейтор|Gefreiter)',
                r'(Рядовой|Private)',
                r'(Новобранец|Recruit)'
            ]
            
            rank_found = False
            for pattern in rank_patterns:
                rank_match = re.search(pattern, html, re.IGNORECASE)
                if rank_match:
                    rank_text = rank_match.group(1)
                    # Map Russian ranks to English
                    rank_mapping = {
                        'Легенда': 'Legend',
                        'Генералиссимус': 'Generalissimo',
                        'Командир бригады': 'Brigadier Commander',
                        'Командир полковник': 'Colonel Commander',
                        'Командир подполковник': 'Lieutenant Colonel Commander',
                        'Командир майор': 'Major Commander',
                        'Командир капитан': 'Captain Commander',
                        'Командир лейтенант': 'Lieutenant Commander',
                        'Командир': 'Commander',
                        'Фельдмаршал': 'Field Marshal',
                        'Маршал': 'Marshal',
                        'Генерал': 'General',
                        'Генерал-лейтенант': 'Lieutenant General',
                        'Генерал-майор': 'Major General',
                        'Бригадир': 'Brigadier',
                        'Полковник': 'Colonel',
                        'Подполковник': 'Lieutenant Colonel',
                        'Майор': 'Major',
                        'Капитан': 'Captain',
                        'Старший лейтенант': 'First Lieutenant',
                        'Лейтенант': 'Second Lieutenant',
                        'Старший прапорщик': 'Master Warrant Officer',
                        'Прапорщик': 'Warrant Officer',
                        'Старшина': 'Sergeant Major',
                        'Старший сержант': 'First Sergeant',
                        'Сержант': 'Master Sergeant',
                        'Младший сержант': 'Staff Sergeant',
                        'Ефрейтор': 'Sergeant',
                        'Старший ефрейтор': 'Master Corporal',
                        'Капрал': 'Corporal',
                        'Гефрейтор': 'Gefreiter',
                        'Рядовой': 'Private',
                        'Новобранец': 'Recruit'
                    }
                    
                    player_data['rank'] = rank_mapping.get(rank_text, rank_text)
                    
                    # Handle Legend with number
                    if len(rank_match.groups()) > 1 and rank_match.group(2):
                        legend_level = rank_match.group(2)
                        if legend_level:
                            player_data['rank'] = f"Legend {legend_level}"
                    
                    rank_found = True
                    logger.info(f"Found rank: {player_data['rank']}")
                    break
            
            # If rank not found by pattern, try experience-based rank detection
            if not rank_found and player_data['experience'] > 0:
                from utils import get_max_experience_for_rank
                
                experience = player_data['experience']
                
                if experience >= 1800000:
                    # Calculate Legend level
                    legend_level = max(1, (experience - 1600000) // 200000)
                    player_data['rank'] = f"Legend {legend_level}"
                elif experience >= 1600000:
                    player_data['rank'] = "Generalissimo"
                elif experience >= 1400000:
                    player_data['rank'] = "Commander"
                elif experience >= 1255000:
                    player_data['rank'] = "Field Marshal"
                elif experience >= 1122000:
                    player_data['rank'] = "Marshal"
                elif experience >= 1000000:
                    player_data['rank'] = "General"
                elif experience >= 889000:
                    player_data['rank'] = "Lieutenant General"
                elif experience >= 787000:
                    player_data['rank'] = "Major General"
                elif experience >= 695000:
                    player_data['rank'] = "Brigadier"
                elif experience >= 606000:
                    player_data['rank'] = "Colonel"
                elif experience >= 527000:
                    player_data['rank'] = "Lieutenant Colonel"
                elif experience >= 455000:
                    player_data['rank'] = "Major"
                elif experience >= 390000:
                    player_data['rank'] = "Captain"
                elif experience >= 332000:
                    player_data['rank'] = "First Lieutenant"
                elif experience >= 280000:
                    player_data['rank'] = "Second Lieutenant"
                elif experience >= 233000:
                    player_data['rank'] = "Third Lieutenant"
                elif experience >= 192000:
                    player_data['rank'] = "Warrant Officer 5"
                elif experience >= 156000:
                    player_data['rank'] = "Warrant Officer 4"
                elif experience >= 125000:
                    player_data['rank'] = "Warrant Officer 3"
                elif experience >= 98000:
                    player_data['rank'] = "Warrant Officer 2"
                elif experience >= 76000:
                    player_data['rank'] = "Warrant Officer 1"
                elif experience >= 57000:
                    player_data['rank'] = "Sergeant Major"
                elif experience >= 41000:
                    player_data['rank'] = "First Sergeant"
                elif experience >= 29000:
                    player_data['rank'] = "Master Sergeant"
                elif experience >= 20000:
                    player_data['rank'] = "Staff Sergeant"
                elif experience >= 12300:
                    player_data['rank'] = "Sergeant"
                elif experience >= 7700:
                    player_data['rank'] = "Master Corporal"
                elif experience >= 4400:
                    player_data['rank'] = "Corporal"
                elif experience >= 2200:
                    player_data['rank'] = "Gefreiter"
                elif experience >= 1000:
                    player_data['rank'] = "Private"
                else:
                    player_data['rank'] = "Recruit"
                
                logger.info(f"Rank determined by experience: {player_data['rank']}")
            
            # Parse kills and deaths
            kill_patterns = [
                r'[Kk]ills?[:\s]*(\d{1,3}(?:[,\s]\d{3})*)',
                r'Убийства[:\s]*(\d{1,3}(?:[,\s]\d{3})*)',
                r'"kills"[:\s]*(\d{1,3}(?:[,\s]\d{3})*)'
            ]
            
            for pattern in kill_patterns:
                kill_match = re.search(pattern, html, re.IGNORECASE)
                if kill_match:
                    kills_str = kill_match.group(1).replace(',', '').replace(' ', '')
                    player_data['kills'] = int(kills_str)
                    logger.info(f"Found kills: {player_data['kills']}")
                    break
            
            death_patterns = [
                r'[Dd]eaths?[:\s]*(\d{1,3}(?:[,\s]\d{3})*)',
                r'Смерти[:\s]*(\d{1,3}(?:[,\s]\d{3})*)',
                r'"deaths"[:\s]*(\d{1,3}(?:[,\s]\d{3})*)'
            ]
            
            for pattern in death_patterns:
                death_match = re.search(pattern, html, re.IGNORECASE)
                if death_match:
                    deaths_str = death_match.group(1).replace(',', '').replace(' ', '')
                    player_data['deaths'] = int(deaths_str)
                    logger.info(f"Found deaths: {player_data['deaths']}")
                    break
            
            # Calculate K/D ratio
            if player_data['deaths'] == 0:
                player_data['kd_ratio'] = str(player_data['kills']) if player_data['kills'] > 0 else "0.00"
            else:
                player_data['kd_ratio'] = f"{player_data['kills']/player_data['deaths']:.2f}"
            
            # Parse gold boxes
            gold_patterns = [
                r'[Gg]old[^0-9]*[Bb]oxes?[:\s]*(\d+)',
                r'Золотые[^0-9]*коробки[:\s]*(\d+)',
                r'"gold_boxes"[:\s]*(\d+)'
            ]
            
            for pattern in gold_patterns:
                gold_match = re.search(pattern, html, re.IGNORECASE)
                if gold_match:
                    player_data['gold_boxes'] = int(gold_match.group(1))
                    logger.info(f"Found gold boxes: {player_data['gold_boxes']}")
                    break
            
            # Parse premium status
            premium_indicators = [
                'premium' in html.lower(),
                'премиум' in html.lower(),
                '"premium": true' in html.lower()
            ]
            
            player_data['premium'] = any(premium_indicators)
            
            # Parse group/clan
            group_patterns = [
                r'[Gg]roup[:\s]*([^<\n\r]+)',
                r'[Cc]lan[:\s]*([^<\n\r]+)',
                r'Группа[:\s]*([^<\n\r]+)',
                r'"group"[:\s]*"([^"]+)"'
            ]
            
            for pattern in group_patterns:
                group_match = re.search(pattern, html, re.IGNORECASE)
                if group_match:
                    group_name = group_match.group(1).strip()
                    if group_name and group_name.lower() not in ['unknown', 'none', 'null', '']:
                        player_data['group'] = group_name
                        logger.info(f"Found group: {player_data['group']}")
                        break
            
            # Parse equipment (turrets and hulls)
            from config import TURRET_NAMES, HULL_NAMES
            
            # Find turrets
            turrets_found = []
            for turret in TURRET_NAMES:
                # Look for turret with modification levels
                turret_patterns = [
                    rf'{turret}[^a-zA-Z0-9]*M(\d+)',  # Turret M3 format
                    rf'{turret}[^a-zA-Z0-9]*(\d+)',   # Turret 3 format
                    rf'{turret}'                       # Just turret name
                ]
                
                for pattern in turret_patterns:
                    turret_matches = re.findall(pattern, html, re.IGNORECASE)
                    for match in turret_matches:
                        if isinstance(match, str) and match.isdigit():
                            turrets_found.append(f"{turret} M{match}")
                        elif isinstance(match, str) and not match:
                            turrets_found.append(turret)
                        elif match:
                            turrets_found.append(f"{turret} M{match}")
                    if turret_matches:
                        break
            
            # Find hulls
            hulls_found = []
            for hull in HULL_NAMES:
                # Look for hull with modification levels
                hull_patterns = [
                    rf'{hull}[^a-zA-Z0-9]*M(\d+)',  # Hull M3 format
                    rf'{hull}[^a-zA-Z0-9]*(\d+)',   # Hull 3 format
                    rf'{hull}'                       # Just hull name
                ]
                
                for pattern in hull_patterns:
                    hull_matches = re.findall(pattern, html, re.IGNORECASE)
                    for match in hull_matches:
                        if isinstance(match, str) and match.isdigit():
                            hulls_found.append(f"{hull} M{match}")
                        elif isinstance(match, str) and not match:
                            hulls_found.append(hull)
                        elif match:
                            hulls_found.append(f"{hull} M{match}")
                    if hull_matches:
                        break
            
            # Remove duplicates while preserving order
            player_data['equipment']['turrets'] = list(dict.fromkeys(turrets_found))
            player_data['equipment']['hulls'] = list(dict.fromkeys(hulls_found))
            
            logger.info(f"Successfully parsed data for {username}")
            return player_data
            
        except Exception as e:
            logger.error(f"Error parsing player data for {username}: {e}")
            return None
    
    async def _search_player_on_main_page(self, username):
        """Search for player on the main rankings page."""
        try:
            session = await self._get_session()
            
            # Try searching on different ranking pages
            search_urls = [
                f"{self.base_url}",
                f"{self.base_url}/rankings",
                f"{self.base_url}/search?q={quote(username)}"
            ]
            
            for url in search_urls:
                try:
                    async with session.get(url) as response:
                        if response.status == 200:
                            html = await response.text()
                            
                            # Look for the username in the rankings
                            if username.lower() in html.lower():
                                # Try to extract basic player info from the rankings
                                return await self._extract_from_rankings(html, username)
                            
                except Exception as e:
                    logger.warning(f"Error searching on {url}: {e}")
                    continue
            
            return None
            
        except Exception as e:
            logger.error(f"Error in _search_player_on_main_page: {e}")
            return None
    
    async def _extract_from_rankings(self, html, username):
        """Extract basic player data from rankings page."""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Look for the username in table rows or list items
            username_pattern = re.compile(re.escape(username), re.IGNORECASE)
            
            # Find elements containing the username
            elements = soup.find_all(text=username_pattern)
            
            if not elements:
                return None
            
            # Try to find the parent row/container with player data
            for element in elements:
                parent = element.parent
                while parent and parent.name not in ['tr', 'li', 'div']:
                    parent = parent.parent
                
                if parent:
                    # Extract what we can from this row
                    row_text = parent.get_text()
                    
                    # Try to extract experience and rank from the row
                    exp_match = re.search(r'(\d{1,3}(?:[,\s]\d{3})*)', row_text)
                    
                    if exp_match:
                        # We found some data, create minimal player object
                        player_data = {
                            'username': username,
                            'rank': 'Unknown',
                            'experience': 0,
                            'kills': 0,
                            'deaths': 0,
                            'kd_ratio': '0.00',
                            'gold_boxes': 0,
                            'premium': False,
                            'group': 'Unknown',
                            'is_online': False,
                            'status_indicator': '🔴',
                            'equipment': {'turrets': [], 'hulls': []}
                        }
                        
                        # Extract experience
                        try:
                            exp_str = exp_match.group(1).replace(',', '').replace(' ', '')
                            player_data['experience'] = int(exp_str)
                        except ValueError:
                            pass
                        
                        return player_data
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting from rankings: {e}")
            return None
    
    async def close(self):
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()
