import type { Item } from './api/practice'

export function isValidAnswer(item: Item, answer: string | undefined): boolean {
  return item.options.some(option => option.key === answer)
}

/** Shared by the page progress and the submission guard so they cannot disagree. */
export function practiceProgress(items: Item[], choices: Record<string, string>) {
  const effectiveItems = items.filter(item => item.is_valid)
  const pendingItems = effectiveItems.filter(item => !item.attempt)
  const missingItems = pendingItems.filter(item => !isValidAnswer(item, choices[item.id]))
  const answers = effectiveItems.map(item => ({
    practice_item_id: item.id,
    answer: item.attempt?.answer ?? choices[item.id] ?? '',
  })).sort((a, b) => a.practice_item_id.localeCompare(b.practice_item_id))

  return {
    effectiveItems,
    pendingItems,
    missingItems,
    answeredCount: effectiveItems.length - missingItems.length,
    answers,
    canSubmit: answers.length > 0 && effectiveItems.every(item =>
      isValidAnswer(item, item.attempt?.answer ?? choices[item.id])),
  }
}
