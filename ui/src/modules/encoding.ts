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

// Remove control tokens like <|start|>, <|channel|>, <|message|>, etc., and leading wrappers like "to=functions.*"
export function stripControlTokens(input: string): string {
  if (!input) return input;
  let out = input.replace(/<\|[^>]+\|>/g, '');
  out = out.replace(/\bto=functions\.[^\s`]+/g, '');
  // Tidy multiple spaces/newlines left behind
  out = out.replace(/[\t \f\v]+/g, ' ');
  out = out.replace(/\s*\n\s*\n\s*/g, '\n\n').trim();
  return out;
}

// Remove a JSON tool call object (optionally inside ``` or ```json fences) from text
export function removeToolJsonBlock(input: string): string {
  if (!input) return input;
  let out = input;
  // Remove fenced JSON block that looks like a tool call
  out = out.replace(/```(?:json)?\s*\{[\s\S]*?\}\s*```/g, (m)=>{
    try {
      const inner = m.replace(/```(?:json)?/,'').replace(/```/,'').trim();
      const obj = JSON.parse(inner);
      if (obj && typeof obj === 'object' && 'name' in obj && 'arguments' in obj) return '';
    } catch {}
    return m; // leave non-tool fenced blocks intact
  });
  // Remove bare JSON tool object if present
  out = out.replace(/\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{[\s\S]*?\}\s*\}/g, '');
  // Clean leftover whitespace
  out = out.replace(/\s*\n\s*\n\s*/g, '\n\n').trim();
  return out;
}

export function sanitizeAssistantToken(token: string): string {
  return stripControlTokens(token);
}

export function sanitizeAssistantFull(text: string): string {
  return removeToolJsonBlock(stripControlTokens(text));
}
