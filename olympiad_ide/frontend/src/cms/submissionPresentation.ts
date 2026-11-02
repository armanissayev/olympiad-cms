import { CMSError } from './submissions'
import type { CMSContext, CMSTask } from './types'

export function sourceLanguage(task: CMSTask, filename: string, profiles: CMSContext['executionProfileMap']) {
  const matches = task.languages.filter(language => (language.extensions?.length ? language.extensions : [language.extension]).some(extension => filename.toLowerCase().endsWith(extension.startsWith('.') ? extension.toLowerCase() : '.' + extension.toLowerCase())))
  const preferred = Object.values(profiles ?? {}).find(profile => profile.enabled && matches.some(language => language.id === profile.cmsLanguage))
  return matches.find(language => language.id === preferred?.cmsLanguage)?.id ?? matches[0]?.id ?? ''
}
export function participantMessage(error: unknown) {
  if (error instanceof CMSError) {
    if ([401, 403].includes(error.status)) return 'Please sign in through CMS again. Your code is saved.'
    if (error.status === 429) return 'Please wait before submitting again.'
    if (error.status === 413) return 'The selected file is too large.'
    if ([400, 409, 415, 422].includes(error.status)) return 'CMS could not accept this submission. Check the problem, file and language.'
  }
  return 'We could not complete this request. Your code is preserved. Try again or use the CMS participant page.'
}
