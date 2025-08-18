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

// Remove tool-call JSON blocks from assistant text to keep the UI clean.
// Strips:
// - Fenced blocks like ```json {"name":"...","arguments":{...}} ```
// - Raw JSON objects containing both "name" and "arguments" (balanced braces only)
export function stripToolJsonBlocks(input: string): string {
  if (!input) return input;
  let out = input;
  // Remove fenced JSON blocks first
  out = out.replace(/```(?:json)?\s*\{[\s\S]*?\}\s*```/g, (block)=>{
    try {
      const m = block.match(/\{[\s\S]*\}/);
      if (!m) return block;
      const obj = JSON.parse(m[0]);
      if (obj && typeof obj === 'object' && 'name' in obj && 'arguments' in obj) return '';
    } catch {}
    return block;
  });
  // Remove raw tool JSON objects by scanning for balanced braces around "name"
  const nameIdx = () => out.indexOf('"name"');
  let idx = nameIdx();
  while (idx !== -1) {
    // find preceding opening brace
    let start = -1;
    for (let i = idx; i >= 0; i--) {
      if (out[i] === '{') { start = i; break; }
      if (out[i] === '}' || out[i] === '`') break;
    }
    if (start === -1) break;
    // find matching closing brace
    let depth = 0, end = -1;
    for (let j = start; j < out.length; j++) {
      const ch = out[j];
      if (ch === '{') depth++;
      else if (ch === '}') { depth--; if (depth === 0) { end = j; break; } }
    }
    if (end !== -1) {
      const candidate = out.slice(start, end+1);
      try {
        const obj = JSON.parse(candidate);
        if (obj && typeof obj === 'object' && 'name' in obj && 'arguments' in obj) {
          out = out.slice(0, start) + out.slice(end+1);
          idx = nameIdx();
          continue;
        }
      } catch {}
    }
    idx = out.indexOf('"name"', idx + 6);
  }
  return out;
}

// Split out model control/preamble tokens (e.g., "<|start|>assistant|channel|...", "<constrain>|json|message>")
// from the beginning of the string. Returns { preamble, rest } where preamble is the
// joined lines of control tokens (may be empty) and rest is the remaining content.
export function splitControlPreamble(input: string): { preamble: string; rest: string } {
  if (!input) return { preamble: '', rest: '' };
  const lines = input.split(/\r?\n/);
  const out: string[] = [];
  let i = 0;
  const isControl = (line: string) => {
    const l = line.trim();
    if (!l) return false;
    if (/^<\|[^>]+\|>/.test(l)) return true; // <|...|>
    if (/<constrain>/i.test(l)) return true;
    if (/\bassistant\|channel\b/.test(l)) return true;
    if (/commentary to=functions\./.test(l)) return true;
    if (/\|json\|message>?$/i.test(l)) return true;
    // Lines dominated by pipes/angle tokens
    const pipes = (l.match(/[|<>]/g) || []).length;
    return pipes >= Math.max(6, Math.floor(l.length * 0.2));
  };
  while (i < lines.length && isControl(lines[i])) {
    out.push(lines[i]);
    i++;
  }
  const preamble = out.join('\n');
  const rest = lines.slice(i).join('\n').replace(/^\n+/, '');
  return { preamble, rest };
}
