"""
Summarizer - Module de résumé IA
Supporte Claude API (Anthropic) et Ollama (local)
"""

import os
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import httpx

from scraper import XPost


@dataclass
class Summary:
    """Résumé généré"""
    title: str
    highlights: list[str]  # Points clés
    full_summary: str
    source: str  # "for_you" ou nom de liste
    post_count: int
    top_posts: list[dict]  # Les posts les plus importants


class BaseSummarizer(ABC):
    """Classe de base pour les summarizers"""
    
    @abstractmethod
    async def summarize(self, posts: list[XPost], source_name: str) -> Summary:
        pass
        
    def _prepare_posts_text(self, posts: list[XPost]) -> str:
        """Prépare le texte des posts pour le résumé"""
        lines = []
        for i, post in enumerate(posts, 1):
            engagement = f"[❤️{post.likes} 🔄{post.retweets}]"
            verified = "✓" if post.author_verified else ""
            lines.append(
                f"{i}. @{post.author_handle}{verified} {engagement}\n"
                f"   {post.content[:500]}\n"
            )
        return "\n".join(lines)
        
    def _get_system_prompt(self, source_name: str, style: str) -> str:
        # Si c'est une liste avec un ID numérique, demander de déduire le thème
        is_unnamed_list = source_name.startswith("list_") or source_name.isdigit()
        
        theme_instruction = ""
        if is_unnamed_list:
            theme_instruction = """
IMPORTANT : Cette liste n'a pas de nom. Analyse le contenu des posts pour déduire le THÈME principal 
(ex: "Tech & IA", "Politique suisse", "Crypto & Finance", "Médias & Journalistes", etc.)
Utilise ce thème déduit comme titre."""
        
        return f"""Tu es un assistant qui crée des résumés {style} de fils Twitter/X.

Ta tâche : résumer les posts des dernières 24h.
{theme_instruction}

Règles :
1. Identifie les 3-5 sujets/tendances majeurs
2. Mentionne les posts les plus engageants ou importants
3. Garde un ton neutre et informatif
4. Réponds en JSON avec cette structure exacte :
{{
    "title": "Titre accrocheur du résumé - si liste sans nom, déduis le thème (max 60 caractères)",
    "highlights": ["Point clé 1", "Point clé 2", "Point clé 3"],
    "full_summary": "Résumé complet en 2-3 paragraphes",
    "top_post_indices": [1, 5, 12]  // Indices des posts les plus importants
}}"""


class ClaudeSummarizer(BaseSummarizer):
    """Summarizer utilisant l'API Claude (Anthropic)"""
    
    def __init__(self, config: dict):
        self.config = config['summarizer']['claude']
        self.api_key = os.environ.get(self.config['api_key_env'])
        if not self.api_key:
            raise ValueError(f"Variable d'environnement {self.config['api_key_env']} non définie")
        self.model = self.config['model']
        self.style = config['summarizer']['summary']['style']
        self.max_tokens = config['summarizer']['summary']['max_tokens']
        
    async def summarize(self, posts: list[XPost], source_name: str) -> Summary:
        posts_text = self._prepare_posts_text(posts)
        system_prompt = self._get_system_prompt(source_name, self.style)
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "system": system_prompt,
                    "messages": [
                        {"role": "user", "content": f"Voici les posts à résumer :\n\n{posts_text}"}
                    ]
                },
                timeout=60.0
            )
            response.raise_for_status()
            result = response.json()
            
        # Parser la réponse JSON
        content = result['content'][0]['text']
        # Extraire le JSON de la réponse
        try:
            # Chercher le JSON dans la réponse
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            summary_data = json.loads(content[json_start:json_end])
        except json.JSONDecodeError:
            # Fallback si le JSON est malformé
            summary_data = {
                "title": f"Résumé {source_name}",
                "highlights": ["Erreur de parsing du résumé"],
                "full_summary": content,
                "top_post_indices": []
            }
            
        # Récupérer les top posts
        top_posts = []
        for idx in summary_data.get('top_post_indices', []):
            if 1 <= idx <= len(posts):
                top_posts.append(posts[idx-1].to_dict())
                
        return Summary(
            title=summary_data.get('title', f"Résumé {source_name}"),
            highlights=summary_data.get('highlights', []),
            full_summary=summary_data.get('full_summary', ''),
            source=source_name,
            post_count=len(posts),
            top_posts=top_posts[:5]
        )


class OllamaSummarizer(BaseSummarizer):
    """Summarizer utilisant Ollama (local)"""
    
    def __init__(self, config: dict):
        self.config = config['summarizer']['ollama']
        self.base_url = self.config['base_url']
        self.model = self.config['model']
        self.style = config['summarizer']['summary']['style']
        
    async def summarize(self, posts: list[XPost], source_name: str) -> Summary:
        posts_text = self._prepare_posts_text(posts)
        system_prompt = self._get_system_prompt(source_name, self.style)
        
        full_prompt = f"{system_prompt}\n\n---\n\nVoici les posts à résumer :\n\n{posts_text}"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": full_prompt,
                    "stream": False,
                    "format": "json"
                },
                timeout=120.0  # Ollama peut être plus lent
            )
            response.raise_for_status()
            result = response.json()
            
        # Parser la réponse
        content = result.get('response', '')
        try:
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                summary_data = json.loads(content[json_start:json_end])
            else:
                raise json.JSONDecodeError("No JSON found", content, 0)
        except json.JSONDecodeError:
            summary_data = {
                "title": f"Résumé {source_name}",
                "highlights": ["Résumé automatique"],
                "full_summary": content[:1000] if content else "Aucun contenu généré",
                "top_post_indices": []
            }
            
        top_posts = []
        for idx in summary_data.get('top_post_indices', []):
            if 1 <= idx <= len(posts):
                top_posts.append(posts[idx-1].to_dict())
                
        return Summary(
            title=summary_data.get('title', f"Résumé {source_name}"),
            highlights=summary_data.get('highlights', []),
            full_summary=summary_data.get('full_summary', ''),
            source=source_name,
            post_count=len(posts),
            top_posts=top_posts[:5]
        )


def create_summarizer(config: dict) -> BaseSummarizer:
    """Factory pour créer le bon summarizer selon la config"""
    provider = config['summarizer']['provider']
    
    if provider == 'claude':
        return ClaudeSummarizer(config)
    elif provider == 'ollama':
        return OllamaSummarizer(config)
    else:
        raise ValueError(f"Provider inconnu: {provider}")


# Test
async def main():
    import yaml
    from pathlib import Path
    
    config = yaml.safe_load(Path('config.yaml').read_text())
    
    # Créer des posts de test
    from datetime import datetime
    test_posts = [
        XPost(
            id="1", author_handle="elonmusk", author_name="Elon Musk",
            author_verified=True, content="Big announcement coming about AI...",
            timestamp=datetime.now(), likes=50000, retweets=10000, replies=5000,
            source="test"
        ),
        XPost(
            id="2", author_handle="kaboreski", author_name="Tech News",
            author_verified=False, content="New breakthrough in quantum computing",
            timestamp=datetime.now(), likes=1000, retweets=200, replies=50,
            source="test"
        ),
    ]
    
    summarizer = create_summarizer(config)
    summary = await summarizer.summarize(test_posts, "Test Feed")
    
    print(f"📰 {summary.title}")
    print(f"\n🔹 Points clés:")
    for h in summary.highlights:
        print(f"   • {h}")
    print(f"\n📝 Résumé:\n{summary.full_summary}")
    

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
