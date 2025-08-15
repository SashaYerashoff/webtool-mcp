// Heuristic fixer for UTF-8 text that was mis-decoded as ISO-8859-1/Windows-1252 (mojibake like 
// "ÐÑÐ¸Ð²ÐµÑ", "â", "Ã©").
// Only applies when the string appears to be 8-bit and contains common mojibake markers.
export function maybeFixUtf8Mojibake(input: string): string {
  if (!input) return input;
  // If it already contains non-Latin1 code points (e.g., Cyrillic), assume it's fine.
  for (let i = 0; i < input.length; i++) {
    if (input.charCodeAt(i) > 255) return input;
  }
  // Detect common mojibake markers
  const suspicious = /[ÃÂÐÑâ€ž•™œžŸ¢£¥¦§¨©ª«¬®¯°±²³´µ¶·¸¹º»¼½¾¿]/;
  if (!suspicious.test(input)) return input;
  try {
    // Interpret current 8-bit code units as bytes and decode as UTF-8
    const bytes = new Uint8Array(input.length);
    for (let i = 0; i < input.length; i++) bytes[i] = input.charCodeAt(i) & 0xff;
    const dec = new TextDecoder('utf-8');
    const fixed = dec.decode(bytes);
    // Only keep if it reduced mojibake markers
    const beforeCount = (input.match(/[ÃÂÐÑâ]/g) || []).length;
    const afterCount = (fixed.match(/[ÃÂÐÑâ]/g) || []).length;
    return afterCount < beforeCount ? fixed : input;
  } catch {
    return input;
  }
}
