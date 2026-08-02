"""
Agnes IA - Améliorateur Audio
Nettoyage, normalisation, spatialisation, mixage
"""

import os
import tempfile
import numpy as np
import librosa
import soundfile as sf
from pydub import AudioSegment, effects
from typing import Optional
import logging

logger = logging.getLogger(__name__)

try:
    import rnnoise
    HAS_RNNOISE = True
except ImportError:
    HAS_RNNOISE = False


class AudioEnhancer:
    """
    Améliorateur audio avec plusieurs fonctionnalités:
    - Réduction de bruit (RNNoise)
    - Normalisation LUFS
    - Spatialisation (Binaural, 5.1)
    - Mixage (EQ, compression)
    - Suppression des silences
    """
    
    def __init__(self):
        self.denoiser = None
        if HAS_RNNOISE:
            try:
                self.denoiser = rnnoise.RNNoise()
                logger.info("RNNoise denoiser loaded")
            except Exception as e:
                logger.warning(f"Could not load RNNoise: {e}")
    
    def enhance(self, audio_path: str) -> str:
        """Améliorer un fichier audio (nettoyage + normalisation + spatialisation)"""
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
        # Étape 1: Nettoyage
        cleaned_path = self.denoise(audio_path)
        
        # Étape 2: Normalisation
        normalized_path = self.normalize(cleaned_path)
        
        # Étape 3: Spatialisation
        spatialized_path = self.spatialize(normalized_path)
        
        # Étape 4: Mixage
        final_path = self.mix(spatialized_path)
        
        # Nettoyer les fichiers temporaires
        for path in [cleaned_path, normalized_path, spatialized_path]:
            if path and os.path.exists(path) and path != final_path:
                try:
                    os.remove(path)
                except:
                    pass
        
        logger.info(f"Enhanced audio: {audio_path} -> {final_path}")
        return final_path
    
    def denoise(self, audio_path: str) -> str:
        """Nettoyer un fichier audio (réduction de bruit)"""
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            output_path = f.name
        
        try:
            y, sr = librosa.load(audio_path, sr=None, mono=True)
            
            if HAS_RNNOISE and self.denoiser:
                # Utiliser RNNoise
                denoised = self.denoiser.process(y.astype(np.float32), sr)
                sf.write(output_path, denoised, sr)
            else:
                # Méthode de fallback: spectral gating
                denoised = self._spectral_gating(y, sr)
                sf.write(output_path, denoised, sr)
            
            logger.info(f"Denoised audio: {audio_path} -> {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Denoising failed: {str(e)}")
            import shutil
            shutil.copy(audio_path, output_path)
            return output_path
    
    def _spectral_gating(self, y: np.ndarray, sr: int, threshold_db: float = -40.0) -> np.ndarray:
        """Réduction de bruit par spectral gating"""
        D = librosa.stft(y)
        S, phase = librosa.magphase(D)
        
        S_db = librosa.amplitude_to_db(S, ref=np.max)
        S_db_clean = np.copy(S_db)
        S_db_clean[S_db_clean < threshold_db] = threshold_db
        
        S_clean = librosa.db_to_amplitude(S_db_clean)
        D_clean = S_clean * phase
        
        return librosa.istft(D_clean)
    
    def normalize(self, audio_path: str, target_lufs: float = -23.0) -> str:
        """Normaliser un fichier audio à un niveau LUFS"""
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            output_path = f.name
        
        try:
            audio = AudioSegment.from_file(audio_path)
            
            # Calculer le LUFS actuel
            current_lufs = self._calculate_lufs(audio_path)
            
            # Calculer le gain nécessaire
            gain_db = target_lufs - current_lufs
            
            # Appliquer le gain
            normalized = audio + gain_db
            
            # Limiter pour éviter le clipping
            normalized = effects.normalize(normalized)
            
            normalized.export(output_path, format="wav")
            
            logger.info(f"Normalized audio: {audio_path} -> {output_path} (LUFS: {target_lufs})")
            return output_path
        except Exception as e:
            logger.error(f"Normalization failed: {str(e)}")
            import shutil
            shutil.copy(audio_path, output_path)
            return output_path
    
    def _calculate_lufs(self, audio_path: str) -> float:
        """Calculer approximativement le LUFS"""
        try:
            y, sr = librosa.load(audio_path, sr=None)
            rms = np.sqrt(np.mean(y**2))
            db = 20 * np.log10(rms) if rms > 0 else -np.inf
            return db + 3  # Estimation LUFS
        except:
            return -23.0
    
    def spatialize(self, audio_path: str, mode: str = "binaural") -> str:
        """Appliquer une spatialisation audio"""
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            output_path = f.name
        
        try:
            audio = AudioSegment.from_file(audio_path)
            
            if mode == "binaural":
                # Appliquer un effet binaural simple
                left = audio.pan(-15)
                right = audio.pan(15)
                spatialized = left.overlay(right)
            elif mode == "5.1":
                # Simuler un mixage 5.1
                center = audio
                left = audio.pan(-45)
                right = audio.pan(45)
                lfe = audio.low_pass(200) + 6
                rear_left = audio.pan(-90) - 10
                rear_right = audio.pan(90) - 10
                
                spatialized = center.overlay(left).overlay(right)
            else:
                spatialized = audio
            
            spatialized.export(output_path, format="wav")
            logger.info(f"Spatialized audio: {audio_path} -> {output_path} (mode: {mode})")
            return output_path
        except Exception as e:
            logger.error(f"Spatialization failed: {str(e)}")
            import shutil
            shutil.copy(audio_path, output_path)
            return output_path
    
    def mix(self, audio_path: str) -> str:
        """Appliquer un mixage audio (EQ + compression)"""
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            output_path = f.name
        
        try:
            audio = AudioSegment.from_file(audio_path)
            
            # Appliquer un EQ
            eq_audio = effects.equalize(
                audio,
                frequencies=[60, 170, 310, 600, 1000, 3000, 6000, 12000, 14000, 16000],
                gains=[3, 2, 1, 0, 0, 1, 2, 3, 4, 5]
            )
            
            # Appliquer une compression
            compressed = self._compress(eq_audio)
            
            compressed.export(output_path, format="wav")
            logger.info(f"Mixed audio: {audio_path} -> {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Mixing failed: {str(e)}")
            import shutil
            shutil.copy(audio_path, output_path)
            return output_path
    
    def _compress(self, audio: AudioSegment, threshold_db: float = -20.0, ratio: float = 4.0) -> AudioSegment:
        """Appliquer une compression dynamique"""
        audio = effects.normalize(audio)
        
        samples = np.array(audio.get_array_of_samples()).astype(np.float32) / (2**15)
        compressed = np.copy(samples)
        
        mask = np.abs(samples) > (10 ** (threshold_db / 20))
        compressed[mask] = np.sign(samples[mask]) * (np.abs(samples[mask]) ** (1 / ratio))
        
        return AudioSegment(
            (compressed * (2**15 - 1)).astype(np.int16).tobytes(),
            frame_rate=audio.frame_rate,
            sample_width=audio.sample_width,
            channels=audio.channels
        )
    
    def remove_silence(self, audio_path: str, threshold_db: float = -40.0, min_silence_len: int = 500) -> str:
        """Supprimer les silences"""
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            output_path = f.name
        
        try:
            audio = AudioSegment.from_file(audio_path)
            
            non_silent_chunks = effects.split_on_silence(
                audio,
                min_silence_len=min_silence_len,
                silence_thresh=threshold_db,
                keep_silence=200
            )
            
            result = AudioSegment.empty()
            for chunk in non_silent_chunks:
                result += chunk
            
            result.export(output_path, format="wav")
            logger.info(f"Removed silence: {audio_path} -> {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Silence removal failed: {str(e)}")
            import shutil
            shutil.copy(audio_path, output_path)
            return output_path
