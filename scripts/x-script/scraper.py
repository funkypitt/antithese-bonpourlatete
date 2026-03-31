"""
X (Twitter) Scraper - Module de récupération des posts
Utilise Playwright pour simuler une session authentifiée
"""

import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

from playwright.async_api import async_playwright, Browser, Page, BrowserContext


@dataclass
class XPost:
    """Représente un post X"""
    id: str
    author_handle: str
    author_name: str
    author_verified: bool
    content: str
    timestamp: datetime
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    views: int = 0
    is_retweet: bool = False
    retweeted_by: Optional[str] = None
    has_media: bool = False
    media_type: Optional[str] = None  # "image", "video", "gif"
    url: str = ""
    source: str = ""  # "for_you" ou nom de la liste
    
    @property
    def engagement_score(self) -> int:
        """Score d'engagement total"""
        return self.likes + (self.retweets * 2) + self.replies
    
    def to_dict(self) -> dict:
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        d['engagement_score'] = self.engagement_score
        return d


class XScraper:
    """Scraper X utilisant Playwright"""
    
    def __init__(self, config: dict, headless: bool = True):
        self.config = config
        self.headless = headless
        self.session_file = Path(config['x_auth']['session_file']).expanduser()
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        
    async def __aenter__(self):
        await self.start()
        return self
        
    async def __aexit__(self, *args):
        await self.close()
        
    async def start(self):
        """Démarre le navigateur"""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(
            headless=self.headless,
            args=['--disable-blink-features=AutomationControlled']
        )
        
        # Charger la session existante ou en créer une nouvelle
        if self.session_file.exists():
            print(f"📂 Chargement de la session depuis {self.session_file}")
            storage_state = json.loads(self.session_file.read_text())
            self.context = await self.browser.new_context(
                storage_state=storage_state,
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
        else:
            print("🔐 Nouvelle session - connexion requise")
            self.context = await self.browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            
        self.page = await self.context.new_page()
        
    async def close(self):
        """Ferme le navigateur"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
            
    async def login_interactive(self):
        """
        Connexion interactive - ouvre le navigateur pour que l'utilisateur
        se connecte manuellement, puis sauvegarde la session
        """
        # Relancer en mode visible
        await self.close()
        
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(
            headless=False,  # Visible pour login manuel
            args=['--disable-blink-features=AutomationControlled']
        )
        self.context = await self.browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        )
        self.page = await self.context.new_page()
        
        print("\n" + "="*60)
        print("🔐 CONNEXION MANUELLE REQUISE")
        print("="*60)
        print("1. Une fenêtre de navigateur va s'ouvrir")
        print("2. Connecte-toi à X avec tes identifiants")
        print("3. Une fois sur ton feed, appuie sur ENTRÉE ici")
        print("="*60 + "\n")
        
        await self.page.goto('https://x.com/login')
        
        input("Appuie sur ENTRÉE une fois connecté...")
        
        # Sauvegarder la session
        storage_state = await self.context.storage_state()
        self.session_file.write_text(json.dumps(storage_state, indent=2))
        print(f"✅ Session sauvegardée dans {self.session_file}")
        
        # Revenir en mode headless
        await self.close()
        await self.start()
        
    async def is_logged_in(self) -> bool:
        """Vérifie si la session est valide"""
        try:
            # Utiliser domcontentloaded car X charge en continu (networkidle ne termine jamais)
            await self.page.goto('https://x.com/home', wait_until='domcontentloaded', timeout=30000)
            
            # Attendre que le contenu principal charge
            try:
                await self.page.wait_for_selector('[data-testid="primaryColumn"]', timeout=10000)
            except:
                pass
                
            await asyncio.sleep(3)
            
            # Vérifier si on est redirigé vers login
            if 'login' in self.page.url.lower():
                return False
                
            # Vérifier la présence d'éléments authentifiés
            logged_in = await self.page.query_selector('[data-testid="SideNav_AccountSwitcher_Button"]')
            return logged_in is not None
            
        except Exception as e:
            print(f"⚠️ Erreur vérification login: {e}")
            return False
            
    async def ensure_logged_in(self):
        """S'assure que l'utilisateur est connecté"""
        if not await self.is_logged_in():
            print("❌ Session expirée ou invalide")
            await self.login_interactive()
            
    async def scrape_for_you(self, max_posts: int = 50) -> list[XPost]:
        """Scrape le feed For You"""
        print(f"\n📱 Scraping For You (max {max_posts} posts)...")
        
        await self.page.goto('https://x.com/home', wait_until='domcontentloaded', timeout=60000)
        
        # Attendre que les tweets chargent
        try:
            await self.page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
        except:
            print("   ⚠️ Timeout en attendant les tweets, on continue...")
            
        await asyncio.sleep(3)
        
        # S'assurer qu'on est sur l'onglet "For you"
        for_you_tab = await self.page.query_selector('[role="tab"]:has-text("For you")')
        if for_you_tab:
            await for_you_tab.click()
            await asyncio.sleep(2)
            
        posts = await self._scrape_timeline(max_posts, source="for_you")
        print(f"   ✅ {len(posts)} posts récupérés du For You")
        return posts
        
    async def scrape_list(self, list_url: str, list_name: str, max_posts: int = 30) -> list[XPost]:
        """Scrape une liste X"""
        print(f"\n📋 Scraping liste '{list_name}' (max {max_posts} posts)...")
        
        await self.page.goto(list_url, wait_until='domcontentloaded', timeout=60000)
        
        # Attendre que les tweets chargent
        try:
            await self.page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
        except:
            print(f"   ⚠️ Timeout en attendant les tweets de '{list_name}', on continue...")
            
        await asyncio.sleep(3)
        
        posts = await self._scrape_timeline(max_posts, source=list_name)
        print(f"   ✅ {len(posts)} posts récupérés de '{list_name}'")
        return posts
        
    async def _scrape_timeline(self, max_posts: int, source: str) -> list[XPost]:
        """Scrape les posts d'une timeline"""
        posts = []
        seen_ids = set()
        scroll_attempts = 0
        max_scroll_attempts = 20
        no_new_posts_count = 0
        
        while len(posts) < max_posts and scroll_attempts < max_scroll_attempts:
            # Récupérer les articles visibles
            try:
                articles = await self.page.query_selector_all('article[data-testid="tweet"]')
            except Exception as e:
                print(f"   ⚠️ Erreur récupération articles: {e}")
                break
            
            initial_count = len(posts)
            
            for article in articles:
                try:
                    post = await self._parse_article(article, source)
                    if post and post.id not in seen_ids:
                        seen_ids.add(post.id)
                        posts.append(post)
                        
                        if len(posts) >= max_posts:
                            break
                except Exception as e:
                    continue  # Skip les posts problématiques
            
            # Vérifier si on a trouvé de nouveaux posts
            if len(posts) == initial_count:
                no_new_posts_count += 1
                if no_new_posts_count >= 3:
                    print(f"   ℹ️ Plus de nouveaux posts après {scroll_attempts} scrolls")
                    break
            else:
                no_new_posts_count = 0
                    
            # Scroll pour charger plus
            await self.page.evaluate('window.scrollBy(0, 800)')
            await asyncio.sleep(2)  # Augmenté pour laisser le temps de charger
            scroll_attempts += 1
            
        return posts
        
    async def _parse_article(self, article, source: str) -> Optional[XPost]:
        """Parse un article en XPost"""
        try:
            # ID du post (depuis le lien)
            link = await article.query_selector('a[href*="/status/"]')
            if not link:
                return None
            href = await link.get_attribute('href')
            post_id = href.split('/status/')[-1].split('?')[0].split('/')[0]
            
            # Auteur
            author_link = await article.query_selector('[data-testid="User-Name"] a')
            author_handle = ""
            author_name = ""
            if author_link:
                author_href = await author_link.get_attribute('href')
                author_handle = author_href.strip('/') if author_href else ""
                name_span = await article.query_selector('[data-testid="User-Name"] span')
                if name_span:
                    author_name = await name_span.inner_text()
                    
            # Vérifié
            verified = await article.query_selector('[data-testid="icon-verified"]') is not None
            
            # Contenu
            content_div = await article.query_selector('[data-testid="tweetText"]')
            content = ""
            if content_div:
                content = await content_div.inner_text()
                
            # Timestamp
            time_el = await article.query_selector('time')
            timestamp = datetime.now()
            if time_el:
                datetime_attr = await time_el.get_attribute('datetime')
                if datetime_attr:
                    timestamp = datetime.fromisoformat(datetime_attr.replace('Z', '+00:00'))
                    
            # Métriques
            likes = await self._parse_metric(article, 'like')
            retweets = await self._parse_metric(article, 'retweet')
            replies = await self._parse_metric(article, 'reply')
            
            # Retweet check
            social_context = await article.query_selector('[data-testid="socialContext"]')
            is_retweet = False
            retweeted_by = None
            if social_context:
                context_text = await social_context.inner_text()
                if 'reposted' in context_text.lower() or 'retweeted' in context_text.lower():
                    is_retweet = True
                    retweeted_by = context_text.split()[0]
                    
            # Media
            has_media = await article.query_selector('[data-testid="tweetPhoto"]') is not None
            has_video = await article.query_selector('[data-testid="videoPlayer"]') is not None
            media_type = None
            if has_video:
                media_type = "video"
            elif has_media:
                media_type = "image"
                
            return XPost(
                id=post_id,
                author_handle=author_handle,
                author_name=author_name,
                author_verified=verified,
                content=content,
                timestamp=timestamp,
                likes=likes,
                retweets=retweets,
                replies=replies,
                is_retweet=is_retweet,
                retweeted_by=retweeted_by,
                has_media=has_media,
                media_type=media_type,
                url=f"https://x.com{href}",
                source=source
            )
            
        except Exception as e:
            return None
            
    async def _parse_metric(self, article, metric_type: str) -> int:
        """Parse une métrique (likes, retweets, replies)"""
        try:
            button = await article.query_selector(f'[data-testid="{metric_type}"]')
            if button:
                text = await button.inner_text()
                # Parser "1.2K", "5M", etc.
                text = text.strip()
                if not text or text == '0':
                    return 0
                multiplier = 1
                if 'K' in text.upper():
                    multiplier = 1000
                    text = text.upper().replace('K', '')
                elif 'M' in text.upper():
                    multiplier = 1000000
                    text = text.upper().replace('M', '')
                return int(float(text) * multiplier)
        except:
            pass
        return 0


async def main():
    """Test du scraper"""
    import yaml
    
    config_path = Path(__file__).parent / 'config.yaml'
    config = yaml.safe_load(config_path.read_text())
    
    async with XScraper(config) as scraper:
        await scraper.ensure_logged_in()
        
        # Test For You
        posts = await scraper.scrape_for_you(max_posts=10)
        
        for post in posts[:5]:
            print(f"\n{'='*50}")
            print(f"@{post.author_handle}: {post.content[:100]}...")
            print(f"❤️ {post.likes} | 🔄 {post.retweets} | 💬 {post.replies}")
            

if __name__ == "__main__":
    asyncio.run(main())
