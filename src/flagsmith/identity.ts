const STORAGE_KEY = 'bos_visitor_id';

function createId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return `anon_${crypto.randomUUID()}`;
  }
  return `anon_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

/** Stable anonymous visitor id persisted in localStorage. */
export function getOrCreateVisitorId(): string {
  try {
    const existing = localStorage.getItem(STORAGE_KEY);
    if (existing && existing.length > 4) return existing;
    const id = createId();
    localStorage.setItem(STORAGE_KEY, id);
    return id;
  } catch {
    return createId();
  }
}
