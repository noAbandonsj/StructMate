type Kind = 'chat' | 'practice' | 'reports'
const prefix = (kind: Kind) => 'capstone.' + kind + '.'
export function draftKey(user: string, conversation: string, kind: Kind = 'chat') { return prefix(kind) + user + '.' + conversation }
export function readDraft(user: string, conversation: string, kind: Kind = 'chat'): string {
  try { return sessionStorage.getItem(draftKey(user, conversation, kind)) ?? '' } catch { return '' }
}
export function saveDraft(user: string, conversation: string, text: string, kind: Kind = 'chat') {
  try {
    if (text) sessionStorage.setItem(draftKey(user, conversation, kind), text)
    else sessionStorage.removeItem(draftKey(user, conversation, kind))
  } catch { /* Storage disabled: the in-memory draft still works. */ }
}
export function clearDrafts(user: string) {
  try {
    for (let index = sessionStorage.length - 1; index >= 0; index--) {
      const key = sessionStorage.key(index)
      if (key && (['chat', 'practice', 'reports'] as Kind[]).some(kind => key.startsWith(prefix(kind) + user + '.'))) sessionStorage.removeItem(key)
    }
  } catch { /* No browser storage in Node tests. */ }
}
