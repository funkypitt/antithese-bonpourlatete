#!/usr/bin/env python3
"""
X Daily Digest - Script principal
Orchestre le scraping, le résumé et la génération PDF
"""

import asyncio
import argparse
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import yaml

from scraper import XScraper, XPost
from summarizer import create_summarizer, Summary
from pdf_generator import PDFGenerator


class XDigestPipeline:
    """Pipeline complet de génération du digest"""
    
    def __init__(self, config_path: str = "config.yaml", headless: bool = True):
        self.config_path = Path(config_path)
        self.config = yaml.safe_load(self.config_path.read_text())
        self.headless = headless
        
    async def run(self, skip_scrape: bool = False, test_mode: bool = False):
        """Exécute le pipeline complet"""
        print("\n" + "="*60)
        print("📱 X DAILY DIGEST")
        print(f"   {datetime.now().strftime('%A %d %B %Y - %H:%M')}")
        print("="*60)
        
        all_posts: dict[str, list[XPost]] = {}
        
        if test_mode:
            print("\n🧪 Mode test - utilisation de données simulées")
            all_posts = self._generate_test_data()
        elif skip_scrape:
            print("\n⚠️ Scraping désactivé - données depuis le cache")
            # TODO: implémenter le cache
            return
        else:
            # Scraping
            all_posts = await self._scrape_all()
            
        if not all_posts:
            print("\n❌ Aucun post récupéré. Arrêt.")
            return
            
        # Filtrage
        filtered_posts = self._filter_posts(all_posts)
        
        # Résumé
        summaries = await self._summarize_all(filtered_posts)
        
        # Génération PDF
        pdf_path = self._generate_pdf(summaries)
        
        # Sync vers kDrive
        kdrive_path = self._sync_to_kdrive(pdf_path)
        
        print("\n" + "="*60)
        print("✅ DIGEST GÉNÉRÉ AVEC SUCCÈS")
        print(f"   📄 {pdf_path}")
        if kdrive_path:
            print(f"   ☁️  {kdrive_path}")
        print("="*60 + "\n")
        
        return pdf_path
        
    async def _scrape_all(self) -> dict[str, list[XPost]]:
        """Scrape toutes les sources configurées"""
        all_posts = {}
        
        async with XScraper(self.config, headless=self.headless) as scraper:
            # Vérifier la connexion
            await scraper.ensure_logged_in()
            
            # For You
            if self.config['sources']['for_you']['enabled']:
                max_posts = self.config['sources']['for_you']['max_posts']
                posts = await scraper.scrape_for_you(max_posts)
                all_posts['for_you'] = posts
                
            # Listes
            for list_config in self.config['sources'].get('lists', []):
                url = list_config['url']
                # Extraire l'ID de la liste depuis l'URL comme nom par défaut
                list_id = url.rstrip('/').split('/')[-1]
                name = list_config.get('name', f"list_{list_id}")
                max_posts = list_config.get('max_posts', 25)
                
                posts = await scraper.scrape_list(url, name, max_posts)
                all_posts[name] = posts
                
        return all_posts
        
    def _filter_posts(self, all_posts: dict[str, list[XPost]]) -> dict[str, list[XPost]]:
        """Filtre les posts selon la configuration"""
        print("\n🔍 Filtrage des posts...")
        
        filter_config = self.config['filtering']
        min_engagement = filter_config.get('min_engagement', 0)
        priority_keywords = [kw.lower() for kw in filter_config.get('priority_keywords', [])]
        exclude_keywords = [kw.lower() for kw in filter_config.get('exclude_keywords', [])]
        exclude_retweets = filter_config.get('exclude_pure_retweets', False)
        allowed_languages = filter_config.get('languages')
        
        filtered = {}
        
        for source, posts in all_posts.items():
            source_filtered = []
            
            for post in posts:
                # Exclure les retweets purs
                if exclude_retweets and post.is_retweet:
                    continue
                    
                # Engagement minimum
                if post.engagement_score < min_engagement:
                    continue
                    
                # Mots-clés exclus
                content_lower = post.content.lower()
                if any(kw in content_lower for kw in exclude_keywords):
                    continue
                    
                # Boost pour mots-clés prioritaires
                priority_boost = sum(1 for kw in priority_keywords if kw in content_lower)
                
                # Ajouter avec score
                post._priority_boost = priority_boost
                source_filtered.append(post)
                
            # Trier par engagement + boost
            source_filtered.sort(
                key=lambda p: p.engagement_score + (getattr(p, '_priority_boost', 0) * 1000),
                reverse=True
            )
            
            filtered[source] = source_filtered
            print(f"   {source}: {len(posts)} → {len(source_filtered)} posts")
            
        return filtered
        
    async def _summarize_all(self, posts_by_source: dict[str, list[XPost]]) -> list[Summary]:
        """Génère les résumés pour chaque source"""
        print("\n🤖 Génération des résumés...")
        
        summarizer = create_summarizer(self.config)
        summaries = []
        
        for source, posts in posts_by_source.items():
            if not posts:
                continue
                
            print(f"   📝 Résumé de '{source}' ({len(posts)} posts)...")
            
            try:
                summary = await summarizer.summarize(posts, source)
                summaries.append(summary)
                print(f"      ✅ {summary.title}")
            except Exception as e:
                print(f"      ❌ Erreur: {e}")
                # Créer un résumé minimal en cas d'erreur
                summaries.append(Summary(
                    title=f"Résumé {source}",
                    highlights=[f"{len(posts)} posts analysés"],
                    full_summary="Erreur lors de la génération du résumé.",
                    source=source,
                    post_count=len(posts),
                    top_posts=[p.to_dict() for p in posts[:3]]
                ))
                
        return summaries
        
    def _generate_pdf(self, summaries: list[Summary]) -> Path:
        """Génère le PDF final"""
        print("\n📄 Génération du PDF...")
        
        generator = PDFGenerator(self.config)
        return generator.generate(summaries)
        
    def _sync_to_kdrive(self, pdf_path: Path) -> Optional[Path]:
        """Synchronise le PDF vers kDrive"""
        kdrive_config = self.config.get('kdrive', {})
        
        if not kdrive_config.get('enabled', False):
            return None
            
        sync_path = Path(kdrive_config['sync_path']).expanduser()
        keep_last = kdrive_config.get('keep_last', 0)
        
        print(f"\n☁️  Synchronisation vers kDrive...")
        
        try:
            # Créer le dossier si nécessaire
            sync_path.mkdir(parents=True, exist_ok=True)
            
            # Copier le PDF
            dest_path = sync_path / pdf_path.name
            shutil.copy2(pdf_path, dest_path)
            print(f"   ✅ Copié vers {dest_path}")
            
            # Nettoyer les anciens fichiers si keep_last > 0
            if keep_last > 0:
                pdf_files = sorted(
                    sync_path.glob("x-digest-*.pdf"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True
                )
                
                for old_file in pdf_files[keep_last:]:
                    old_file.unlink()
                    print(f"   🗑️  Supprimé ancien: {old_file.name}")
                    
            return dest_path
            
        except Exception as e:
            print(f"   ❌ Erreur sync kDrive: {e}")
            return None
        
    def _generate_test_data(self) -> dict[str, list[XPost]]:
        """Génère des données de test"""
        from datetime import datetime
        
        test_posts = {
            "for_you": [
                XPost(
                    id="1", author_handle="elonmusk", author_name="Elon Musk",
                    author_verified=True,
                    content="Just had an incredible breakthrough with AI. This changes everything. The future is here and it's more amazing than we could have imagined.",
                    timestamp=datetime.now(), likes=150000, retweets=30000, replies=8000,
                    source="for_you", url="https://x.com/elonmusk/status/1"
                ),
                XPost(
                    id="2", author_handle="sama", author_name="Sam Altman",
                    author_verified=True,
                    content="Thinking about the next generation of AI systems. Safety and capability can go hand in hand.",
                    timestamp=datetime.now(), likes=45000, retweets=8000, replies=2000,
                    source="for_you", url="https://x.com/sama/status/2"
                ),
                XPost(
                    id="3", author_handle="kaboreski", author_name="AI Researcher",
                    author_verified=False,
                    content="New paper just dropped on constitutional AI. Really interesting approach to alignment. Thread 🧵",
                    timestamp=datetime.now(), likes=2500, retweets=500, replies=150,
                    source="for_you", url="https://x.com/kaboreski/status/3"
                ),
                XPost(
                    id="4", author_handle="techcrunch", author_name="TechCrunch",
                    author_verified=True,
                    content="BREAKING: Apple announces new AI features for iPhone. Siri gets a major upgrade with on-device LLM.",
                    timestamp=datetime.now(), likes=8000, retweets=2000, replies=500,
                    source="for_you", url="https://x.com/techcrunch/status/4"
                ),
                XPost(
                    id="5", author_handle="lexfridman", author_name="Lex Fridman",
                    author_verified=True,
                    content="New podcast episode with a brilliant mind discussing consciousness and AI. Link in bio.",
                    timestamp=datetime.now(), likes=12000, retweets=2500, replies=400,
                    source="for_you", url="https://x.com/lexfridman/status/5"
                ),
            ],
            "Tech & IA": [
                XPost(
                    id="10", author_handle="AnthropicAI", author_name="Anthropic",
                    author_verified=True,
                    content="Introducing new safety research on AI interpretability. Understanding what models know and why they behave as they do.",
                    timestamp=datetime.now(), likes=5000, retweets=1200, replies=300,
                    source="Tech & IA", url="https://x.com/AnthropicAI/status/10"
                ),
                XPost(
                    id="11", author_handle="GoogleAI", author_name="Google AI",
                    author_verified=True,
                    content="Gemini 2.0 benchmarks are in. Significant improvements across reasoning and coding tasks.",
                    timestamp=datetime.now(), likes=8500, retweets=2000, replies=450,
                    source="Tech & IA", url="https://x.com/GoogleAI/status/11"
                ),
            ]
        }
        
        return test_posts


async def main():
    parser = argparse.ArgumentParser(description="X Daily Digest - Génération de résumé quotidien")
    parser.add_argument(
        '--config', '-c',
        default='config.yaml',
        help='Chemin vers le fichier de configuration'
    )
    parser.add_argument(
        '--test', '-t',
        action='store_true',
        help='Mode test avec données simulées'
    )
    parser.add_argument(
        '--login',
        action='store_true',
        help='Forcer une nouvelle connexion à X'
    )
    parser.add_argument(
        '--skip-scrape',
        action='store_true',
        help='Utiliser le cache au lieu de scraper'
    )
    parser.add_argument(
        '--visible',
        action='store_true',
        help='Afficher le navigateur pendant le scraping (debug)'
    )
    
    args = parser.parse_args()
    
    pipeline = XDigestPipeline(args.config, headless=not args.visible)
    
    if args.login:
        async with XScraper(pipeline.config, headless=False) as scraper:
            await scraper.login_interactive()
        return
        
    await pipeline.run(
        skip_scrape=args.skip_scrape,
        test_mode=args.test
    )


if __name__ == "__main__":
    asyncio.run(main())
