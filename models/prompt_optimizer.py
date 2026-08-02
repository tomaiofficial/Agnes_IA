"""
Agnes IA - Optimiseur de Prompts
Améliore les prompts pour une meilleure génération IA
"""

import re
import random
from typing import Dict, Any, List, Optional

try:
    from transformers import pipeline as hf_pipeline
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False


class PromptOptimizer:
    """
    Optimiseur de prompts pour le pipeline IA.
    
    Fonctionnalités:
    - Nettoyage des prompts
    - Correction grammaticale
    - Ajout de mots-clés de qualité
    - Génération de variations
    """
    
    def __init__(self):
        self.grammar_checker = None
        self.text_classifier = None
        
        if HAS_TRANSFORMERS:
            try:
                self.grammar_checker = hf_pipeline(
                    "text2text-generation",
                    model="vennify/t5-base-grammar-correction"
                )
            except Exception as e:
                print(f"Warning: Could not load grammar checker: {e}")
            
            try:
                self.text_classifier = hf_pipeline(
                    "text-classification",
                    model="facebook/bart-large-mnli"
                )
            except Exception as e:
                print(f"Warning: Could not load text classifier: {e}")
        
        # Mots-clés pour l'amélioration
        self.style_keywords = {
            "realistic": ["photorealistic", "8k", "ultra detailed", "cinematic lighting", "high resolution"],
            "anime": ["anime style", "studio ghibli", "vibrant colors", "anime background", "japanese animation"],
            "cartoon": ["cartoon", "toon", "2d", "colorful", "animated"],
            "fantasy": ["fantasy", "magical", "ethereal", "mystical", "enchanting"],
            "cyberpunk": ["cyberpunk", "neon lights", "futuristic", "dystopian", "sci-fi"],
            "3d": ["3d render", "cgi", "three dimensional", "volumetric lighting"],
            "watercolor": ["watercolor", "painting", "artistic", "brush strokes", "textured"]
        }
        
        self.quality_keywords = [
            "high quality", "ultra high resolution", "sharp focus",
            "detailed textures", "professional", "masterpiece",
            "incredible detail", "perfect", "stunning"
        ]
        
        self.cinematic_keywords = [
            "cinematic composition", "rule of thirds", "dynamic angle",
            "dutch angle", "close up", "wide shot", "depth of field",
            "golden hour", "dramatic lighting", "atmospheric"
        ]
        
        self.artists = [
            "by Albrech Durer", "by Leonardo da Vinci", "by Vincent van Gogh",
            "by Pablo Picasso", "by Salvador Dali", "by Michelangelo",
            "by Rembrandt", "by Claude Monet", "trending on artstation",
            "unreal engine", "octane render"
        ]
    
    def clean(self, prompt: str) -> str:
        """Nettoyer le prompt"""
        if not prompt or not prompt.strip():
            return ""
        
        # Supprimer les espaces multiples
        prompt = re.sub(r'\s+', ' ', prompt)
        
        # Supprimer les caractères spéciaux non valides
        prompt = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', prompt)
        
        # Supprimer les balises HTML
        prompt = re.sub(r'<[^>]+>', '', prompt)
        
        return prompt.strip()
    
    def analyse(self, prompt: str) -> Dict[str, Any]:
        """Analyser le prompt pour en extraire des informations"""
        cleaned = self.clean(prompt)
        
        # Détecter le style
        style = self.detect_style(cleaned)
        
        # Calculer la complexité
        word_count = len(cleaned.split())
        if word_count < 5:
            complexity = "simple"
        elif word_count < 15:
            complexity = "medium"
        else:
            complexity = "complex"
        
        return {
            "length": len(cleaned),
            "word_count": word_count,
            "style": style,
            "complexity": complexity,
            "characters": [],
            "scenes": []
        }
    
    def detect_style(self, prompt: str) -> str:
        """Détecter le style du prompt"""
        if not self.text_classifier:
            # Détection simple par mots-clés
            for style, keywords in self.style_keywords.items():
                for keyword in keywords:
                    if keyword in prompt.lower():
                        return style
            return "realistic"
        
        try:
            result = self.text_classifier(
                prompt,
                candidate_labels=list(self.style_keywords.keys())
            )
            # Retourner le style avec la plus haute probabilité
            return max(result, key=lambda x: x['score'])['label']
        except:
            return "realistic"
    
    def optimize(self, prompt: str, analysis: Optional[Dict[str, Any]] = None) -> str:
        """Optimiser un prompt pour la génération IA"""
        if not prompt or not prompt.strip():
            return prompt
        
        # Nettoyer
        cleaned = self.clean(prompt)
        
        # Correction grammaticale
        corrected = self._correct_grammar(cleaned)
        
        # Détecter le style
        style = analysis.get("style", "realistic") if analysis else self.detect_style(cleaned)
        
        # Ajouter des mots-clés de qualité
        enhanced = self._add_quality_keywords(corrected, style)
        
        # Ajouter des mots-clés cinématiques
        enhanced = self._add_cinematic_keywords(enhanced)
        
        # Ajouter un style d'artiste
        enhanced = self._add_artist_style(enhanced)
        
        return enhanced
    
    def _correct_grammar(self, prompt: str) -> str:
        """Corriger la grammaire du prompt"""
        if not self.grammar_checker:
            return prompt
        
        try:
            result = self.grammar_checker(prompt, max_length=512)
            return result[0]['generated_text']
        except:
            return prompt
    
    def _add_quality_keywords(self, prompt: str, style: str) -> str:
        """Ajouter des mots-clés de qualité"""
        style_kws = self.style_keywords.get(style, [])
        quality_kws = random.sample(self.quality_keywords, min(3, len(self.quality_keywords)))
        
        keywords = style_kws + quality_kws
        random.shuffle(keywords)
        
        if keywords:
            return f"{', '.join(keywords)}, {prompt}"
        return prompt
    
    def _add_cinematic_keywords(self, prompt: str) -> str:
        """Ajouter des mots-clés cinématiques"""
        if random.random() < 0.7:
            keyword = random.choice(self.cinematic_keywords)
            return f"{keyword}, {prompt}"
        return prompt
    
    def _add_artist_style(self, prompt: str) -> str:
        """Ajouter un style d'artiste"""
        if random.random() < 0.5:
            artist = random.choice(self.artists)
            return f"{prompt}, {artist}"
        return prompt
    
    def generate_variations(self, prompt: str, count: int = 3) -> List[str]:
        """Générer des variations d'un prompt"""
        variations = []
        for _ in range(count):
            variation = prompt
            
            # Changer le style aléatoirement
            if random.random() < 0.5:
                new_style = random.choice(list(self.style_keywords.keys()))
                variation = self._add_quality_keywords(variation, new_style)
            
            # Ajouter/supprimer des mots-clés
            if random.random() < 0.5:
                if random.random() < 0.5:
                    keyword = random.choice(self.quality_keywords + self.cinematic_keywords + self.artists)
                    variation = f"{keyword}, {variation}"
                else:
                    words = variation.split(', ')
                    if len(words) > 3:
                        words.pop(random.randint(0, len(words)-1))
                        variation = ', '.join(words)
            
            variations.append(variation)
        
        return variations
