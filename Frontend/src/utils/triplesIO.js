const TRIPLET_ARRAY_KEYS = ['triplets', 'data']

const DEFAULT_IMPORT_MESSAGES = {
  invalidJson: 'Geçersiz JSON dosyası.',
  invalidShape: 'JSON içeriği bir dizi ya da triplets/data alanı içeren bir nesne olmalı.',
  noTriplesArray: 'JSON içinde okunabilir triplet dizisi bulunamadı.',
  noValidTriples: 'Geçerli triplet bulunamadı. Her satırda en az baş/subject ve uç/object alanları olmalı.',
}

const FIELD_ALIASES = {
  baş: ['baş', 'bas', 'subject', 'head', 'source'],
  baş_tipi: ['baş_tipi', 'bas_tipi', 'subject_type', 'head_type', 'source_type'],
  ilişki: ['ilişki', 'iliski', 'relation', 'predicate'],
  uç: ['uç', 'uc', 'object', 'tail', 'target'],
  uç_tipi: ['uç_tipi', 'uc_tipi', 'object_type', 'tail_type', 'target_type'],
  qualifiers: ['qualifiers'],
  kaynak_cumle: ['kaynak_cumle', 'kaynak_cümle', 'source_sentence'],
}

function getImportMessage(messages, key) {
  return messages?.[key] || DEFAULT_IMPORT_MESSAGES[key]
}

function parseJson(rawJson, messages) {
  if (typeof rawJson !== 'string') return rawJson

  try {
    return JSON.parse(rawJson)
  } catch {
    throw new Error(getImportMessage(messages, 'invalidJson'))
  }
}

function getImportPayload(parsedJson, messages) {
  if (Array.isArray(parsedJson)) {
    return {
      rows: parsedJson,
      highlight: [],
    }
  }

  if (!parsedJson || typeof parsedJson !== 'object') {
    throw new Error(getImportMessage(messages, 'invalidShape'))
  }

  const arrayKey = TRIPLET_ARRAY_KEYS.find(key => Array.isArray(parsedJson[key]))
  if (!arrayKey) {
    throw new Error(getImportMessage(messages, 'noTriplesArray'))
  }

  return {
    rows: parsedJson[arrayKey],
    highlight: Array.isArray(parsedJson.highlight) ? parsedJson.highlight.filter(Boolean) : [],
  }
}

function readAliasedValue(row, aliases) {
  const key = aliases.find(alias => Object.prototype.hasOwnProperty.call(row, alias))
  return key ? row[key] : ''
}

function normalizeText(value) {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

function normalizeQualifiers(value) {
  if (!Array.isArray(value)) return []
  return value
    .filter(item => item && typeof item === 'object' && !Array.isArray(item))
    .map(item => ({
      relation: normalizeText(item.relation ?? item.ilişki ?? ''),
      object: normalizeText(item.object ?? item.uç ?? ''),
    }))
}

function normalizeTriplet(row) {
  if (!row || typeof row !== 'object' || Array.isArray(row)) return null

  const triplet = {
    baş: normalizeText(readAliasedValue(row, FIELD_ALIASES.baş)),
    baş_tipi: normalizeText(readAliasedValue(row, FIELD_ALIASES.baş_tipi)),
    ilişki: normalizeText(readAliasedValue(row, FIELD_ALIASES.ilişki)),
    uç: normalizeText(readAliasedValue(row, FIELD_ALIASES.uç)),
    uç_tipi: normalizeText(readAliasedValue(row, FIELD_ALIASES.uç_tipi)),
    qualifiers: normalizeQualifiers(readAliasedValue(row, FIELD_ALIASES.qualifiers)),
    kaynak_cumle: normalizeText(readAliasedValue(row, FIELD_ALIASES.kaynak_cumle)),
  }

  if (!triplet.baş || !triplet.uç) return null
  return triplet
}

export function parseImportedTriples(rawJson, messages = DEFAULT_IMPORT_MESSAGES) {
  const parsedJson = parseJson(rawJson, messages)
  const { rows, highlight } = getImportPayload(parsedJson, messages)
  const triplets = []
  let skipped = 0

  rows.forEach(row => {
    const triplet = normalizeTriplet(row)
    if (triplet) {
      triplets.push(triplet)
    } else {
      skipped += 1
    }
  })

  if (rows.length > 0 && triplets.length === 0) {
    throw new Error(getImportMessage(messages, 'noValidTriples'))
  }

  return {
    triplets,
    highlight,
    skipped,
    total: rows.length,
  }
}

export function downloadJson(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')

  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export function downloadText(text, filename, type = 'text/plain;charset=utf-8') {
  const blob = new Blob([text], { type })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')

  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}
