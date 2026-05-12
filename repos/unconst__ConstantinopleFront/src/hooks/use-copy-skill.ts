import { useState, useCallback } from 'react';

let cachedContent: string | null = null;

export function useCopySkill() {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(async () => {
    try {
      if (!cachedContent) {
        const res = await fetch('/SKILL.md');
        cachedContent = await res.text();
      }
      await navigator.clipboard.writeText(cachedContent);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.open('/SKILL.md', '_blank');
    }
  }, []);

  return { copy, copied };
}
