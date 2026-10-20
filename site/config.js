// Site settings. Everything here is public by design: security rests on the access rules in
// Supabase (supabase/schema-v2.sql), not on keeping these values secret.
export const CONFIG = {
  SITE_NAME: 'H&F Tracks',
  SUPABASE_URL: 'https://fjwsmdglbnmmelfamyol.supabase.co',
  SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_lQGLe10NlBKFSLz6sapaKg_cgzjH_Hv',
  // Cloudflare Turnstile (anti-robot on sign-in). Also switch it on in Supabase:
  // Authentication > Attack Protection > CAPTCHA, provider Turnstile, with the secret key.
  TURNSTILE_SITE_KEY: '0x4AAAAAAFbn5gcuFqJjtp_L',
  // Show "Continue with Google" once Google is set up in Supabase (Authentication > Providers).
  GOOGLE_LOGIN: false,
  // Map background. If you change the provider, also change img-src in index.html.
  TILES_URL: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
  TILES_SUBDOMAINS: 'abc',
  TILES_ATTRIBUTION: 'Map &copy; OpenStreetMap contributors, SRTM | Style &copy; OpenTopoMap (CC-BY-SA)',
  TILES_MAX_ZOOM: 17,
  OVERPASS_URL: 'https://overpass-api.de/api/interpreter',
  // Ground altitude under the flight (tells a flight from a ski or bike descent). Also change connect-src in index.html.
  ELEVATION_URL: 'https://api.open-meteo.com/v1/elevation',
  // Address for removal requests, shown in the page footer. Leave empty until it is chosen.
  CONTACT_EMAIL: '',
  MAX_FILE_MB: 10,
  PAGE_SIZE: 50,
};
