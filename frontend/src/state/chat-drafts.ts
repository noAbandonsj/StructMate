const prefix = 'capstone.chat.'
export function draftKey(user: string, conversation: string) { return prefix + user + '.' + conversation }
export function readDraft(user: string, conversation: string): string {
  try { return sessionStorage.getItem(draftKey(user, conversation)) ?? '' } catch { return '' }
}
export function saveDraft(user: string, conversation: string, text: string) {
  try {
    if (text) sessionStorage.setItem(draftKey(user, conversation), text)
    else sessionStorage.removeItem(draftKey(user, conversation))
  } catch { /* Storage disabled: the in-memory draft still works. */ }
}
export function clearDrafts(user: string) {
  try {
    for (let index = sessionStorage.length - 1; index >= 0; index--) {
      const key = sessionStorage.key(index)
      if (key?.startsWith(prefix + user + '.')) sessionStorage.removeItem(key)
    }
  } catch { /* No browser storage in Node tests. */ }
}
