export const meta = {
  name: 'm05-web-research',
  description: 'M0.5 external-web research engine (L2) — replaces the deprecated built-in L1 deep-research (ADR-010: chain converges to L2(primary)→L3(degrade)). Scope a question, fan out parallel WebSearch angles, fetch+extract falsifiable claims, adversarially N-vote verify (abstain-quorum), then synthesize a cited report. Cost-safe by default (tiered preset; opt into session-model inheritance via tier:\'inherit\'); optional cost controls = model tiers + fan-out knobs + a lite profile, with a hard Sonnet floor on Verify/Synthesize. Ported from the bughunter 5-phase pipeline, WebSearch/WebFetch swapped for git/grep.',
  phases: [
    { title: 'Scope', detail: 'decompose the question into independent search angles' },
    { title: 'Search', detail: 'one WebSearch agent per angle (pipeline, no barrier)' },
    { title: 'Fetch', detail: 'URL-normalized dedup + budget guard, fetch sources, extract falsifiable claims' },
    { title: 'Verify', detail: 'N-vote adversarial verification per claim (abstain-quorum)' },
    { title: 'Synthesize', detail: 'merge surviving claims into a cited report' },
  ],
}

// m05-web-research: Scope → pipeline(Search → URL-dedup+budget → Fetch+Extract) → N-vote Verify → Synthesize
// M0.5 L2 engine. ADR-010 deprecates the built-in L1; chain converges L2(primary)→L3(degrade). Ported from
// bughunter; WebSearch/WebFetch instead of git/grep. In a relay-gateway environment WebSearch depends on
// websearch-proxy (ADR-009) for non-empty recall; a direct Anthropic environment needs no proxy.

// ─── args (robust read: real object | bare question string | JSON-string [the prior-incident bug]) ───
// Prior incident: the caller passed args as a JSON *string* → typeof args === 'string' → every knob silently
// fell back to defaults. We parse a leading-'{' string as JSON, else treat the string as the bare question.
let a
if (typeof args === 'string') {
  const s = args.trim()
  if (s.startsWith('{')) { try { a = JSON.parse(s) } catch { a = { question: s } } }
  else a = { question: s }
} else {
  a = args || {}
}

const Q = a.question
if (!Q) {
  return { error: "No research question. Pass args as a bare string, or { question, angles?, votes?, urls?, claims?, profile?, tier? }." }
}

// ─── cost knobs (R3b/R3c): profile sets the base fan-out; explicit args override per-knob ───
const LITE = a.profile === 'lite'
const BASE = LITE ? { angles: 2, votes: 1, urls: 4, claims: 6 } : { angles: 3, votes: 3, urls: 8, claims: 12 }
const ANGLES       = a.angles ?? BASE.angles
const VOTES        = a.votes  ?? BASE.votes
const MAX_FETCH    = a.urls   ?? BASE.urls
const MAX_CLAIMS   = a.claims ?? BASE.claims
const QUORUM         = Math.max(1, Math.ceil(VOTES / 2))   // min valid (non-abstain) votes needed to adjudicate
const REFUTE_TO_KILL = Math.floor(VOTES / 2) + 1           // refuting votes needed to kill a claim (majority)

// ─── model tiers (R3a) — THE ONLY place vendor model ids live (overridable config-data) ───
// Stage keys map to tier-label values; agent() call-sites reference the RESOLVED map (see opt()), never a
// literal id, so the AC-4 neutrality grep stays clean. Default (no tier · non-lite) = cost-safe 'tiered' preset;
// only an explicit tier:'inherit' returns to an empty map = inherit session model.
const TIER_PRESETS = {
  haiku:  { Scope: 'haiku',  Search: 'haiku',  Fetch: 'haiku',  Verify: 'haiku',  Synthesize: 'haiku'  },
  sonnet: { Scope: 'sonnet', Search: 'sonnet', Fetch: 'sonnet', Verify: 'sonnet', Synthesize: 'sonnet' },
  opus:   { Scope: 'opus',   Search: 'opus',   Fetch: 'opus',   Verify: 'opus',   Synthesize: 'opus'   },
  tiered: { Scope: 'haiku',  Search: 'haiku',  Fetch: 'haiku',  Verify: 'sonnet', Synthesize: 'sonnet' },
}
function buildTierMap(tier, lite) {
  let raw
  if (tier === 'inherit') raw = {}                                             // escape hatch (AC-2): explicit opt-back to inheriting the session model (empty map ⇒ opt() omits model)
  else if (tier && typeof tier === 'object') raw = { ...tier }                  // fine-grained per-stage override
  else if (typeof tier === 'string' && TIER_PRESETS[tier]) raw = { ...TIER_PRESETS[tier] }
  else if (lite) raw = { ...TIER_PRESETS.tiered }                               // lite ⇒ tiered models by default
  else raw = { ...TIER_PRESETS.tiered }                                         // A1 default: no tier + non-lite ⇒ cost-safe tiered (Scope/Search/Fetch=haiku, Verify/Synthesize=sonnet), NOT raw session-model inherit
  // R-风1 hard floor: Verify/Synthesize must NEVER run on the cheapest tier — an under-powered adversarial
  // verifier loses falsification rigor and lets weak claims slip through; synthesis quality collapses too.
  // Enforced in code even if a caller explicitly asks for haiku there (bounced up + logged).
  for (const st of ['Verify', 'Synthesize']) {
    const FLOOR = 'sonnet'
    if (raw[st] && raw[st] === 'haiku') { log('R-风1 floor: ' + st + ' tier haiku→' + FLOOR + ' (verify/synth must not drop to the cheapest tier)'); raw[st] = FLOOR }
  }
  return raw
}
const MODELS = buildTierMap(a.tier, LITE)
// opt(): attach { model } ONLY when the tier map resolves one for the stage; otherwise omit ⇒ inherit session model.
const opt = (stage, extra) => (MODELS[stage] ? { ...extra, model: MODELS[stage] } : extra)

// ─── degraded return (R2/AC-4): explicit non-coverage, never a fabricated "covered" result ───
const degraded = (reason, extra = {}) => ({
  degraded: true,
  engine: 'm05-web-research',
  question: Q,
  reason,
  note: 'capability-degraded: explicit non-coverage — caller must map to explicit_na, never report "covered" or fabricate an engine tier.',
  ...extra,
})

// ─── B hard-gate (AC-3): refuse to fan out on an undecided (possibly flagship) session model ───
// Root cause of the cost blow-up: manual/direct calls that pass neither `tier` nor `profile` used to inherit
// whatever session model was active (e.g. a flagship tier) × the full non-lite fan-out (Scope+Search+Fetch +
// claims×votes Verify + Synthesize ≈ dozens of agents) → quota drain. Decision ②B-a: non-lite with NO cost
// decision at all = reject BEFORE any fan-out. `profile:'lite'` sets a.profile; an explicit `tier` (incl. the
// 'inherit' escape hatch, which sets a.tier) both count as "cost decision given" and pass through. We return a
// SELF-IDENTIFYING shape ({ needsCostDecision }) — NOT degraded()/error — so callers/entry-gate don't mis-map
// this to explicit_na/L3 (web-unavailable). No Scope/Search/Fetch/Verify agent is ever started.
if (a.tier === undefined && a.profile === undefined) {
  return {
    needsCostDecision: true,
    engine: 'm05-web-research',
    question: Q,
    reason: 'no cost decision provided (neither tier nor profile) for a non-lite fan-out — refusing to inherit an undecided session model × large fan-out',
    hint: "pass tier:'haiku'|'sonnet'|'opus'|'tiered'|'inherit', or profile:'lite', to set a cost tier before fan-out（避免继承任意会话模型 × 大扇出烧额度）",
  }
}

// ─── Schemas ───
const SCOPE_SCHEMA = {
  type: 'object', required: ['question', 'angles', 'summary'],
  properties: {
    question: { type: 'string' },
    summary: { type: 'string' },
    angles: { type: 'array', minItems: 1, items: {
      type: 'object', required: ['label', 'query'],
      properties: {
        label: { type: 'string' },
        query: { type: 'string' },
        rationale: { type: 'string' },
      },
    }},
  },
}
const SEARCH_SCHEMA = {
  type: 'object', required: ['results'],
  properties: {
    results: { type: 'array', maxItems: 6, items: {
      type: 'object', required: ['url', 'title', 'relevance'],
      properties: {
        url: { type: 'string' },
        title: { type: 'string' },
        snippet: { type: 'string' },
        relevance: { enum: ['high', 'medium', 'low'] },
      },
    }},
  },
}
const EXTRACT_SCHEMA = {
  type: 'object', required: ['claims', 'sourceQuality'],
  properties: {
    sourceQuality: { enum: ['primary', 'secondary', 'blog', 'forum', 'unreliable'] },
    publishDate: { type: 'string' },
    claims: { type: 'array', maxItems: 5, items: {
      type: 'object', required: ['claim', 'quote', 'importance'],
      properties: {
        claim: { type: 'string' },
        quote: { type: 'string' },
        importance: { enum: ['central', 'supporting', 'tangential'] },
      },
    }},
  },
}
const VERDICT_SCHEMA = {
  type: 'object', required: ['refuted', 'evidence', 'confidence'],
  properties: {
    refuted: { type: 'boolean' },
    evidence: { type: 'string' },
    confidence: { enum: ['high', 'medium', 'low'] },
    counterSource: { type: 'string' },
  },
}
const REPORT_SCHEMA = {
  type: 'object', required: ['summary', 'findings', 'caveats'],
  properties: {
    summary: { type: 'string' },
    findings: { type: 'array', items: {
      type: 'object', required: ['claim', 'confidence', 'sources', 'evidence'],
      properties: {
        claim: { type: 'string' },
        confidence: { enum: ['high', 'medium', 'low'] },
        sources: { type: 'array', items: { type: 'string' } },
        evidence: { type: 'string' },
        vote: { type: 'string' },
      },
    }},
    caveats: { type: 'string' },
    openQuestions: { type: 'array', items: { type: 'string' } },
  },
}

// ─── Phase 0: Scope — decompose question into search angles ───
phase('Scope')
const SCOPE_PROMPT =
  'Decompose this research question into complementary search angles.\n\n' +
  '## Question\n' + Q + '\n\n' +
  '## Task\n' +
  'Generate ' + ANGLES + ' distinct web search queries that together cover the question from different angles ' +
  '(e.g. broad/primary · academic/technical · recent developments · contrarian/limitations · practitioner/implementation). ' +
  'Pick angles that suit the question’s domain. Make queries specific enough to surface high-signal results; avoid redundancy.\n' +
  'Return: the question (verbatim or lightly normalized), a 1-2 sentence decomposition strategy, and the angles.\n\nStructured output only.'
let scope
try {
  scope = await agent(SCOPE_PROMPT, opt('Scope', { label: 'scope', phase: 'Scope', schema: SCOPE_SCHEMA }))
} catch (e) {
  // R2 capability probe: a throw here most likely = structured output (schema) unsupported, or model unavailable.
  return degraded('scope agent threw — structured output (schema) or the selected model may be unavailable: ' + (e && e.message || e), { stage: 'Scope' })
}
if (!scope || !Array.isArray(scope.angles) || scope.angles.length === 0) {
  return degraded('scope produced no angles — structured output (schema) may be unavailable, or the scoping agent returned nothing', { stage: 'Scope' })
}
const angles = scope.angles.slice(0, ANGLES)
log('Q: ' + String(Q).slice(0, 80) + (String(Q).length > 80 ? '…' : ''))
log('Decomposed into ' + angles.length + ' angles: ' + angles.map(a2 => a2.label).join(', '))

// ─── Dedup + budget state (accumulates across searchers as the pipeline completes) ───
const normURL = u => {
  try {
    const p = new URL(u)
    return (p.hostname.replace(/^www\./, '') + p.pathname.replace(/\/$/, '')).toLowerCase()
  } catch { return String(u).toLowerCase() }
}
const seen = new Map()
const dupes = []
const budgetDropped = []
const relRank = { high: 0, medium: 1, low: 2 }
let fetchSlots = MAX_FETCH

// ─── Prompts ───
const SEARCH_PROMPT = angle =>
  '## Web Searcher: ' + angle.label + '\n\n' +
  'Research question: "' + Q + '"\n\n' +
  'Your angle: **' + angle.label + '** — ' + (angle.rationale || '') + '\n' +
  'Search query: `' + angle.query + '`\n\n' +
  '## Task\nUse WebSearch with the query above (or a refined version). Return the top 4-6 most relevant results.\n' +
  'Rank by relevance to the ORIGINAL question, not just the search query. Skip obvious SEO spam/content farms.\n' +
  'Include a short snippet capturing why each result is relevant.\n\nStructured output only.'

const FETCH_PROMPT = (source, angle) =>
  '## Source Extractor\n\n' +
  'Research question: "' + Q + '"\n\n' +
  'Fetch and extract key claims from this source:\n' +
  '**URL:** ' + source.url + '\n**Title:** ' + source.title + '\n**Found via:** ' + angle + ' search\n\n' +
  '## Task\n1. Use WebFetch to retrieve the page content.\n' +
  '2. Assess source quality: primary research/institution? secondary reporting? blog/opinion? forum? unreliable?\n' +
  '3. Extract 2-5 FALSIFIABLE claims that bear on the research question. Each claim must:\n' +
  '   - be a concrete, checkable statement (not vague generalities)\n' +
  '   - include a direct quote from the source as support\n' +
  '   - be rated central/supporting/tangential to the research question\n' +
  '4. Note publish date if available.\n\n' +
  'If the fetch fails or the page is irrelevant/paywalled, return claims: [] and sourceQuality: "unreliable".\n\nStructured output only.'

const VERIFY_PROMPT = (claim, v) =>
  '## Adversarial Claim Verifier (voter ' + (v + 1) + '/' + VOTES + ')\n\n' +
  'Be SKEPTICAL. Try to REFUTE this claim. ≥' + REFUTE_TO_KILL + '/' + VOTES + ' refutations kill it.\n\n' +
  '## Research question\n' + Q + '\n\n' +
  '## Claim under review\n"' + claim.claim + '"\n\n' +
  '**Source:** ' + claim.sourceUrl + ' (' + claim.sourceQuality + ')\n' +
  '**Supporting quote:** "' + claim.quote + '"\n\n' +
  '## Checklist\n' +
  '1. Is the claim actually supported by the quote, or is it an overreach/misread?\n' +
  '2. WebSearch for contradicting evidence — does any credible source dispute or heavily qualify this?\n' +
  '3. Is the source quality sufficient for the claim’s strength? (extraordinary claims need primary sources)\n' +
  '4. Is the claim outdated? (check dates — old claims about fast-moving fields are suspect)\n' +
  '5. Is this a marketing claim / press release / cherry-picked benchmark / forum speculation?\n\n' +
  '**refuted=true** if: unsupported by quote / contradicted / low-quality source for strong claim / outdated / marketing fluff.\n' +
  '**refuted=false** ONLY if: claim is well-supported, current, and source quality matches claim strength.\n' +
  'Default to refuted=true if uncertain.\n\nStructured output only. Evidence MUST be specific.'

// ─── Pipeline: search → dedup+budget → fetch+extract (NO barrier — T1 item 5) ───
const searchResults = await pipeline(
  angles,

  angle => agent(SEARCH_PROMPT(angle), opt('Search', {
    label: 'search:' + angle.label, phase: 'Search', schema: SEARCH_SCHEMA,
  })).then(r => {
    if (!r) return null
    log(angle.label + ': ' + r.results.length + ' results')
    return { angle: angle.label, results: r.results }
  }),

  searchResult => {
    if (!searchResult) return []
    const sorted = [...searchResult.results].sort((x, y) => relRank[x.relevance] - relRank[y.relevance])
    const novel = sorted.filter(r => {
      const key = normURL(r.url)                                   // T1 item 1: URL-normalized dedup
      if (seen.has(key)) {
        dupes.push({ ...r, angle: searchResult.angle, dupOf: seen.get(key) })
        return false
      }
      if (fetchSlots <= 0 && relRank[r.relevance] >= 1) {          // T1 item 2: fetch budget guard
        budgetDropped.push({ ...r, angle: searchResult.angle })
        return false
      }
      seen.set(key, { angle: searchResult.angle, title: r.title })
      fetchSlots--
      return true
    })
    if (novel.length < searchResult.results.length) {
      log(searchResult.angle + ': ' + novel.length + ' novel (' + (searchResult.results.length - novel.length) + ' filtered: dedup/budget)')
    }
    return parallel(
      novel.map(source => () => {
        let host = 'unknown'
        try { host = new URL(source.url).hostname.replace(/^www\./, '') } catch {}
        return agent(FETCH_PROMPT(source, searchResult.angle), opt('Fetch', {
          label: 'fetch:' + host, phase: 'Fetch', schema: EXTRACT_SCHEMA,
        })).then(ext => {
          if (!ext) return null   // user-skip → drop (filtered out), don't mislabel "unreliable"
          return {
            url: source.url, title: source.title, angle: searchResult.angle,
            sourceQuality: ext.sourceQuality, publishDate: ext.publishDate,
            claims: ext.claims.map(c => ({ ...c, sourceUrl: source.url, sourceQuality: ext.sourceQuality })),
          }
        }).catch(e => {
          log('fetch failed: ' + source.url + ' — ' + (e && e.message || e))
          return { url: source.url, title: source.title, angle: searchResult.angle, sourceQuality: 'unreliable', claims: [] }
        })
      })
    )
  }
)

// R2 capability probe: zero URLs discovered across every angle ⇒ WebSearch path is down (or proxy not up).
if (seen.size === 0) {
  return degraded(
    'no URLs discovered from any search angle — WebSearch (or websearch-proxy in a relay-gateway environment, ADR-009) may be unavailable',
    { angles: angles.length, sources: 0, dupes: dupes.length }
  )
}

const allSources = searchResults.flat().filter(Boolean)
const allClaims = allSources.flatMap(s => s.claims)
const impRank = { central: 0, supporting: 1, tangential: 2 }
const qualRank = { primary: 0, secondary: 1, blog: 2, forum: 3, unreliable: 4 }

const rankedClaims = [...allClaims]
  .sort((x, y) => (impRank[x.importance] - impRank[y.importance]) || (qualRank[x.sourceQuality] - qualRank[y.sourceQuality]))
  .slice(0, MAX_CLAIMS)
if (allClaims.length > MAX_CLAIMS) log('claim budget: verifying top ' + MAX_CLAIMS + '/' + allClaims.length + ' (dropped ' + (allClaims.length - MAX_CLAIMS) + ')')

log('Fetched ' + allSources.length + ' sources → ' + allClaims.length + ' claims → verifying top ' + rankedClaims.length)

if (rankedClaims.length === 0) {
  // Distinguish capability failure (every fetch failed ⇒ WebFetch down) from a genuine empty result.
  const allFailed = allSources.length > 0 && allSources.every(s => s.claims.length === 0 && s.sourceQuality === 'unreliable')
  if (allFailed) {
    return degraded('every fetch failed across ' + allSources.length + ' sources — WebFetch may be unavailable', { sources: allSources.length })
  }
  return {
    question: Q, engine: 'm05-web-research',
    summary: 'No claims extracted. ' + allSources.length + ' sources fetched, all empty/irrelevant. ' + dupes.length + ' URL dupes, ' + budgetDropped.length + ' budget-dropped.',
    findings: [], refuted: [], sources: allSources.map(s => ({ url: s.url, quality: s.sourceQuality })),
    stats: { angles: angles.length, sources: allSources.length, claims: 0, dupes: dupes.length, budgetDropped: budgetDropped.length },
  }
}

// ─── Verify: N-vote adversarial with abstain-quorum (T1 item 3) ───
// Barrier here is intentional — the claim pool must be fully assembled before ranking/verification.
phase('Verify')
const voted = (await parallel(
  rankedClaims.map(claim => () =>
    parallel(
      Array.from({ length: VOTES }, (_, v) => () =>
        agent(VERIFY_PROMPT(claim, v), opt('Verify', {
          label: 'v' + v + ':' + claim.claim.slice(0, 40), phase: 'Verify', schema: VERDICT_SCHEMA,
        }))
      )
    ).then(verdicts => {
      // A null vote (user-skip / agent error) = ABSTAIN — counts as neither support nor refute.
      const valid = verdicts.filter(Boolean)
      const refuted = valid.filter(v => v.refuted).length
      const abstained = VOTES - valid.length
      // Survive ONLY if actually adjudicated: a QUORUM of valid votes AND fewer than REFUTE_TO_KILL refuting.
      // Too many abstentions = unverified ⇒ must NOT pass (else all-abstain → refuted=0 → false survive).
      const survives = valid.length >= QUORUM && refuted < REFUTE_TO_KILL
      log('"' + claim.claim.slice(0, 50) + '…": ' + (valid.length - refuted) + '-' + refuted + (abstained > 0 ? ' (' + abstained + ' abstain)' : '') + ' ' + (survives ? '✓' : '✗'))
      return { ...claim, verdicts: valid, refutedVotes: refuted, abstained, survives }
    })
  )
)).filter(Boolean)

const confirmed = voted.filter(c => c.survives)
const killed = voted.filter(c => !c.survives)
log('Verify done: ' + voted.length + ' claims → ' + confirmed.length + ' confirmed, ' + killed.length + ' killed')

const sourcesOut = () => allSources.map(s => ({ url: s.url, quality: s.sourceQuality, angle: s.angle, claimCount: s.claims.length }))
const refutedOut = () => killed.map(c => ({ claim: c.claim, vote: (c.verdicts.length - c.refutedVotes) + '-' + c.refutedVotes, source: c.sourceUrl }))
const baseStats = {
  angles: angles.length, sourcesFetched: allSources.length, claimsExtracted: allClaims.length,
  claimsVerified: voted.length, confirmed: confirmed.length, killed: killed.length,
  urlDupes: dupes.length, budgetDropped: budgetDropped.length,
}
const runMeta = { engine: 'm05-web-research', profile: LITE ? 'lite' : 'full', knobs: { angles: ANGLES, votes: VOTES, urls: MAX_FETCH, claims: MAX_CLAIMS }, models: MODELS }

if (confirmed.length === 0) {
  // Salvage (T1 item 4): all claims refuted — return transparently rather than throwing.
  return {
    question: Q, ...runMeta,
    summary: 'All ' + voted.length + ' claims refuted by adversarial verification. Research inconclusive — sources may be low-quality or claims overstated.',
    findings: [], refuted: refutedOut(), sources: sourcesOut(),
    stats: { ...baseStats, afterSynthesis: 0 },
  }
}

// ─── Synthesize ───
phase('Synthesize')
const confRank = { high: 0, medium: 1, low: 2 }
const block = confirmed.map((c, i) => {
  const best = c.verdicts.filter(v => !v.refuted).sort((x, y) => confRank[x.confidence] - confRank[y.confidence])[0] || { confidence: 'low', evidence: '(no non-refuting verdict recorded)' }
  return '### [' + i + '] ' + c.claim + '\n' +
    'Vote: ' + (c.verdicts.length - c.refutedVotes) + '-' + c.refutedVotes + ' · Source: ' + c.sourceUrl + ' (' + c.sourceQuality + ')\n' +
    'Quote: "' + c.quote + '"\nVerifier evidence (' + best.confidence + '): ' + best.evidence + '\n'
}).join('\n')

const killedBlock = killed.length > 0
  ? '\n## Refuted claims (for transparency)\n' +
    killed.map(c => '- "' + c.claim + '" (' + c.sourceUrl + ', vote ' + (c.verdicts.length - c.refutedVotes) + '-' + c.refutedVotes + ')').join('\n')
  : ''

let report
try {
  report = await agent(
    '## Synthesis: research report\n\n' +
    '**Question:** ' + Q + '\n\n' +
    confirmed.length + ' claims survived ' + VOTES + '-vote adversarial verification. Merge semantic duplicates and synthesize.\n\n' +
    '## Confirmed claims\n' + block + '\n' + killedBlock + '\n\n' +
    '## Instructions\n' +
    '1. Identify claims that say the same thing — merge them, combine their sources.\n' +
    '2. Group related claims into coherent findings. Each finding should directly address the research question.\n' +
    '3. Assign confidence per finding: high (multiple primary sources, unanimous votes), medium (secondary or split), low (single source or blog-quality).\n' +
    '4. Write a 3-5 sentence executive summary answering the research question.\n' +
    '5. Note caveats: what’s uncertain, what sources were weak, what time-sensitivity applies.\n' +
    '6. List 2-4 open questions that emerged but weren’t answered.\n\nStructured output only.',
    opt('Synthesize', { label: 'synthesize', phase: 'Synthesize', schema: REPORT_SCHEMA })
  )
} catch (e) {
  report = null
  log('synthesis threw — salvaging verified claims: ' + (e && e.message || e))
}

if (!report) {
  // Salvage (T1 item 4): synthesis skipped/errored — return verified claims raw rather than throwing away the run.
  return {
    question: Q, ...runMeta,
    summary: 'Synthesis step was skipped or failed — returning ' + confirmed.length + ' verified claims unmerged.',
    findings: [],
    confirmed: confirmed.map(c => ({ claim: c.claim, source: c.sourceUrl, quote: c.quote, vote: (c.verdicts.length - c.refutedVotes) + '-' + c.refutedVotes })),
    refuted: refutedOut(), sources: sourcesOut(),
    stats: { ...baseStats, afterSynthesis: 0 },
  }
}

return {
  question: Q, ...runMeta,
  ...report,
  refuted: refutedOut(),
  sources: sourcesOut(),
  stats: {
    ...baseStats,
    afterSynthesis: report.findings.length,
    agentCalls: 1 + angles.length + allSources.length + (voted.length * VOTES) + 1,
  },
}
