// ═══════════════════════════════════════════════════════════
// Agnes — Configuration API (frontend)
// ═══════════════════════════════════════════════════════════
// ⚠️ ATTENTION : ce fichier est PUBLIC (sur GitHub Pages).
// Les clés sont visibles par n'importe qui. Utilisées uniquement
// pour les appels directs depuis le navigateur quand le backend
// Render est indisponible.
// ═══════════════════════════════════════════════════════════

window.AGNES_CONFIG = {
  // Clé API Agnes (génération vidéo/image/chat)
  agnesApiKey: 'sk-bq0vx0f9uEJ4xU6J6f2CBKTufuHrYIwIyMuVaBufyfW9g5Bq',

  // Clé API Google Gemini (Veo 3.1)
  // ⚠️ Retirée : GitHub a bloqué sa publication (secret détecté).
  // Elle reste disponible dans le .env local. À configurer via le backend
  // ou le champ "Clé API Gemini" de l'interface.
  geminiApiKey: '',

  // Supabase (communauté Vibes)
  supabaseUrl: 'https://qrxsivfsyraqbqdpsxiv.supabase.co',
  supabaseServiceRoleKey: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFyeHNpdmZzeXJhcWJxZHBzeGl2Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NzU0NDMxNiwiZXhwIjoyMTAzMTIwMzE2fQ.qtfzaaEvbGvq7OusJHUQXTFeSa2Wqp3D_NXkNiJaGQo',
  supabaseAnonKey: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFyeHNpdmZzeXJhcWJxZHBzeGl2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1NDQzMTYsImV4cCI6MjEwMzEyMDMxNn0.n92mbIk7IZUwW8bmWhpWq7hnqX4rqr0bOm4sSlWVMGk',

  // Backend Render (quand il est disponible)
  backendUrl: 'https://agnes-ia2.onrender.com'
};
