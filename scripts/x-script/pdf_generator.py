"""
PDF Generator - Génération du digest PDF
Optimisé pour lecture sur tablette 7 pouces
"""

from datetime import datetime
from pathlib import Path
from typing import Optional
from io import BytesIO

from reportlab.lib.pagesizes import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.units import mm as mm_unit
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, 
    Table, TableStyle, HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from summarizer import Summary


class PDFGenerator:
    """Génère le digest PDF optimisé tablette"""
    
    def __init__(self, config: dict):
        self.config = config['pdf']
        
        # Dimensions en mm converties en points
        self.page_width = self.config['page_width_mm'] * mm_unit
        self.page_height = self.config['page_height_mm'] * mm_unit
        self.margin = self.config['margin_mm'] * mm_unit
        
        # Couleurs
        colors = self.config['colors']
        self.color_primary = Color(*colors['primary'])
        self.color_secondary = Color(*colors['secondary'])
        self.color_accent = Color(*colors['accent'])
        self.color_bg = Color(*colors['background'])
        
        # Styles
        self._setup_styles()
        
        # Output
        self.output_dir = Path(self.config['output_dir']).expanduser()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def _setup_styles(self):
        """Configure les styles de paragraphe"""
        fonts = self.config['fonts']
        
        self.styles = getSampleStyleSheet()
        
        # Style titre principal
        self.styles.add(ParagraphStyle(
            name='DigestTitle',
            fontSize=fonts['title_size'],
            leading=fonts['title_size'] * 1.2,
            textColor=self.color_primary,
            alignment=TA_CENTER,
            spaceAfter=8 * mm_unit,
            fontName='Helvetica-Bold'
        ))
        
        # Style date
        self.styles.add(ParagraphStyle(
            name='DigestDate',
            fontSize=fonts['caption_size'],
            textColor=self.color_secondary,
            alignment=TA_CENTER,
            spaceAfter=4 * mm_unit,
            fontName='Helvetica'
        ))
        
        # Style section (For You, Listes)
        self.styles.add(ParagraphStyle(
            name='SectionTitle',
            fontSize=fonts['heading_size'],
            leading=fonts['heading_size'] * 1.3,
            textColor=self.color_accent,
            spaceBefore=4 * mm_unit,
            spaceAfter=2 * mm_unit,
            fontName='Helvetica-Bold'
        ))
        
        # Style highlights
        self.styles.add(ParagraphStyle(
            name='Highlight',
            fontSize=fonts['body_size'],
            leading=fonts['body_size'] * 1.4,
            textColor=self.color_primary,
            leftIndent=3 * mm_unit,
            spaceBefore=1 * mm_unit,
            spaceAfter=1 * mm_unit,
            fontName='Helvetica',
            bulletIndent=0,
            bulletFontSize=fonts['body_size']
        ))
        
        # Style body
        self.styles.add(ParagraphStyle(
            name='Body',
            fontSize=fonts['body_size'],
            leading=fonts['body_size'] * 1.5,
            textColor=self.color_primary,
            alignment=TA_JUSTIFY,
            spaceBefore=2 * mm_unit,
            spaceAfter=2 * mm_unit,
            fontName='Helvetica'
        ))
        
        # Style post
        self.styles.add(ParagraphStyle(
            name='PostAuthor',
            fontSize=fonts['caption_size'] + 1,
            textColor=self.color_accent,
            fontName='Helvetica-Bold',
            spaceBefore=2 * mm_unit
        ))
        
        self.styles.add(ParagraphStyle(
            name='PostContent',
            fontSize=fonts['body_size'],
            leading=fonts['body_size'] * 1.4,
            textColor=self.color_primary,
            leftIndent=2 * mm_unit,
            fontName='Helvetica'
        ))
        
        self.styles.add(ParagraphStyle(
            name='PostMeta',
            fontSize=fonts['caption_size'],
            textColor=self.color_secondary,
            leftIndent=2 * mm_unit,
            fontName='Helvetica'
        ))
        
    def generate(self, summaries: list[Summary], date: Optional[datetime] = None) -> Path:
        """Génère le PDF complet"""
        if date is None:
            date = datetime.now()
            
        # Nom du fichier
        filename = self.config['filename_pattern'].format(
            date=date.strftime('%Y-%m-%d')
        )
        output_path = self.output_dir / filename
        
        # Créer le document
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=(self.page_width, self.page_height),
            leftMargin=self.margin,
            rightMargin=self.margin,
            topMargin=self.margin,
            bottomMargin=self.margin
        )
        
        # Construire le contenu
        story = []
        
        # Page de titre
        story.extend(self._build_title_page(date, summaries))
        
        # Chaque résumé
        for i, summary in enumerate(summaries):
            if i > 0:
                story.append(PageBreak())
            story.extend(self._build_summary_section(summary))
            
        # Footer avec stats
        story.append(Spacer(1, 4 * mm_unit))
        story.append(HRFlowable(
            width="100%", 
            thickness=0.5, 
            color=self.color_secondary,
            spaceAfter=2 * mm_unit
        ))
        total_posts = sum(s.post_count for s in summaries)
        story.append(Paragraph(
            f"📊 {total_posts} posts analysés • Généré par X-Digest",
            self.styles['DigestDate']
        ))
        
        # Build
        doc.build(story)
        
        print(f"📄 PDF généré: {output_path}")
        return output_path
        
    def _build_title_page(self, date: datetime, summaries: list[Summary]) -> list:
        """Construit la page de titre"""
        elements = []
        
        # Espacement haut
        elements.append(Spacer(1, 10 * mm_unit))
        
        # Titre
        elements.append(Paragraph(
            "📱 X Daily Digest",
            self.styles['DigestTitle']
        ))
        
        # Date
        date_fr = date.strftime("%A %d %B %Y").capitalize()
        elements.append(Paragraph(
            date_fr,
            self.styles['DigestDate']
        ))
        
        elements.append(Spacer(1, 6 * mm_unit))
        
        # Sommaire
        elements.append(HRFlowable(
            width="60%", 
            thickness=1, 
            color=self.color_accent,
            spaceAfter=4 * mm_unit
        ))
        
        for summary in summaries:
            if summary.source == "for_you":
                icon = "🏠"
                display_name = summary.title
            elif summary.source.startswith("list_"):
                icon = "📋"
                display_name = summary.title  # Titre déduit par l'IA
            else:
                icon = "📋"
                display_name = summary.title
                
            elements.append(Paragraph(
                f"{icon} <b>{display_name}</b>",
                self.styles['Highlight']
            ))
            elements.append(Paragraph(
                f"   {summary.post_count} posts",
                self.styles['PostMeta']
            ))
            
        elements.append(Spacer(1, 6 * mm_unit))
        
        return elements
        
    def _build_summary_section(self, summary: Summary) -> list:
        """Construit une section de résumé"""
        elements = []
        
        # Titre de section - utiliser le titre déduit par l'IA si c'est une liste sans nom
        if summary.source == "for_you":
            section_title = "🏠 For You"
        elif summary.source.startswith("list_"):
            # Liste sans nom : utiliser le titre généré par l'IA
            section_title = f"📋 {summary.title}"
        else:
            section_title = f"📋 {summary.source}"
            
        elements.append(Paragraph(section_title, self.styles['SectionTitle']))
        
        # Ligne de séparation
        elements.append(HRFlowable(
            width="100%", 
            thickness=0.5, 
            color=self.color_accent,
            spaceAfter=3 * mm_unit
        ))
        
        # Highlights (points clés)
        if summary.highlights:
            elements.append(Paragraph(
                "<b>🔹 Points clés</b>",
                self.styles['Body']
            ))
            for highlight in summary.highlights:
                # Escape des caractères spéciaux pour ReportLab
                safe_highlight = self._escape_text(highlight)
                elements.append(Paragraph(
                    f"• {safe_highlight}",
                    self.styles['Highlight']
                ))
            elements.append(Spacer(1, 3 * mm_unit))
            
        # Résumé complet
        if summary.full_summary:
            elements.append(Paragraph(
                "<b>📝 Résumé</b>",
                self.styles['Body']
            ))
            # Diviser en paragraphes
            paragraphs = summary.full_summary.split('\n\n')
            for para in paragraphs:
                if para.strip():
                    safe_para = self._escape_text(para.strip())
                    elements.append(Paragraph(safe_para, self.styles['Body']))
                    
        # Top posts
        if summary.top_posts:
            elements.append(Spacer(1, 3 * mm_unit))
            elements.append(Paragraph(
                "<b>⭐ Posts remarquables</b>",
                self.styles['Body']
            ))
            
            for post in summary.top_posts[:3]:
                post_elements = self._build_post_block(post)
                elements.append(KeepTogether(post_elements))
                
        return elements
        
    def _build_post_block(self, post: dict) -> list:
        """Construit un bloc de post"""
        elements = []
        
        # Auteur
        verified = " ✓" if post.get('author_verified') else ""
        elements.append(Paragraph(
            f"@{post.get('author_handle', 'unknown')}{verified}",
            self.styles['PostAuthor']
        ))
        
        # Contenu (tronqué)
        content = post.get('content', '')[:200]
        if len(post.get('content', '')) > 200:
            content += "..."
        safe_content = self._escape_text(content)
        elements.append(Paragraph(safe_content, self.styles['PostContent']))
        
        # Métriques
        likes = post.get('likes', 0)
        retweets = post.get('retweets', 0)
        elements.append(Paragraph(
            f"❤️ {self._format_number(likes)} • 🔄 {self._format_number(retweets)}",
            self.styles['PostMeta']
        ))
        
        elements.append(Spacer(1, 2 * mm_unit))
        
        return elements
        
    def _escape_text(self, text: str) -> str:
        """Escape les caractères spéciaux pour ReportLab XML"""
        if not text:
            return ""
        # Remplacer les caractères problématiques
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        # Supprimer les caractères de contrôle
        text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\t')
        return text
        
    def _format_number(self, n: int) -> str:
        """Formate un nombre (1500 -> 1.5K)"""
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        elif n >= 1_000:
            return f"{n/1_000:.1f}K"
        return str(n)


# Test
def main():
    import yaml
    
    config = yaml.safe_load(Path('config.yaml').read_text())
    
    # Données de test
    test_summaries = [
        Summary(
            title="IA et Tech en ébullition",
            highlights=[
                "OpenAI annonce GPT-5 pour Q2 2025",
                "Anthropic lève 2B$ supplémentaires",
                "Apple intègre l'IA dans iOS 19"
            ],
            full_summary="La journée a été marquée par plusieurs annonces majeures dans le domaine de l'IA. OpenAI a confirmé le développement de GPT-5, promettant des capacités de raisonnement inédites.\n\nDu côté d'Anthropic, une nouvelle levée de fonds consolide leur position sur le marché. Les discussions portent principalement sur la sécurité et l'alignement des modèles.",
            source="for_you",
            post_count=47,
            top_posts=[
                {
                    "author_handle": "sama",
                    "author_verified": True,
                    "content": "Excited to share what we've been working on. GPT-5 is going to change everything.",
                    "likes": 125000,
                    "retweets": 28000
                },
                {
                    "author_handle": "daboreski",
                    "author_verified": True,
                    "content": "Safety remains our top priority. New paper on constitutional AI methods.",
                    "likes": 8500,
                    "retweets": 1200
                }
            ]
        ),
        Summary(
            title="Actualités Suisse romande",
            highlights=[
                "CFF: perturbations sur la ligne Lausanne-Genève",
                "Votation fédérale: résultats serrés attendus"
            ],
            full_summary="Les CFF ont annoncé des travaux qui perturberont le trafic pendant deux semaines. La votation sur l'initiative climatique mobilise les électeurs.",
            source="Actualités Suisse",
            post_count=23,
            top_posts=[]
        )
    ]
    
    generator = PDFGenerator(config)
    output_path = generator.generate(test_summaries)
    print(f"✅ Test PDF: {output_path}")


if __name__ == "__main__":
    main()
