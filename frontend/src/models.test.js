import { describe, it, expect } from 'vitest'
import { prettyModel, effectiveModel } from './models.js'
import { buildState, normalizeState } from './api.js'

describe('which Claude', () => {
  it('shows a readable model name', () => {
    expect(prettyModel('claude-sonnet-5-5')).toBe('Sonnet 5.5')
    expect(prettyModel('claude-opus-5-5')).toBe('Opus 5.5')
    expect(prettyModel('claude-haiku-4-5-20251001')).toBe('Haiku 4.5')
    expect(prettyModel('opus')).toBe('Opus')
    expect(prettyModel(null)).toBe('not reported yet')
    expect(prettyModel('some-other-model')).toBe('some-other-model')
  })
  it('resolves what an agent really runs on', () => {
    const models = { session_model: 'claude-sonnet-5-5', roles: { chief: { setting: 'opus' }, head: { setting: 'inherit' } } }
    expect(effectiveModel(models, 'chief')).toBe('opus')
    expect(effectiveModel(models, 'head')).toBe('claude-sonnet-5-5')
    expect(effectiveModel(models, 'hired')).toBeNull()
    expect(effectiveModel(null, 'chief')).toBeNull()
  })
})

describe('v0.10 state', () => {
  const base = { overview: { counts: { agents: 2, messages: 0, departments: 0 } }, departments: [], requests: [], details: [], tasks: [], messages: [] }
  it('carries the File Checker, the models and the learned links', () => {
    const s = buildState({ ...base, org: { chief: { id: 'chief', name: 'C' }, checker: { id: 'checker', name: 'File Checker', kind: 'checker' }, departments: [] },
      models: { session_model: 'claude-sonnet-5-5' }, links: { links: [{ term: 'borescope', dept: 'engine', seen: 2 }] } })
    expect(s.checker.name).toBe('File Checker')
    expect(s.agents.map((a) => a.id)).toEqual(['chief', 'checker'])
    expect(s.models.session_model).toBe('claude-sonnet-5-5')
    expect(s.links).toHaveLength(1)
  })
  it('copes with an older server that has none of it', () => {
    const s = buildState({ ...base, org: { chief: { id: 'chief' }, departments: [] } })
    expect(s.checker).toBeNull()
    expect(s.models).toBeNull()
    expect(s.links).toEqual([])
    expect(normalizeState({ links: 'x' }).links).toEqual([])
  })
})
