'use strict';

const { parseJsonList } = require('./presenter');

function folded(value) { return String(value || '').toLocaleLowerCase(); }

function rowMatches(row, query) {
  if (query.tags.length && !query.tags.every((tag) => parseJsonList(row.tags_json).includes(tag))) return false;
  if (query.matchedTerms.length && !query.matchedTerms.every((term) => parseJsonList(row.matched_terms_json).includes(term))) return false;
  const fields = query.keywordFields.map((field) => {
    if (field === 'content') return row.content_text;
    return row[field];
  });
  const corpus = folded(fields.join('\n'));
  if (query.keywordMode === 'phrase') return corpus.includes(folded(query.phrase));
  if (!query.keywords.length) return true;
  const matches = query.keywords.map((keyword) => corpus.includes(folded(keyword)));
  return query.keywordMode === 'all' ? matches.every(Boolean) : matches.some(Boolean);
}

module.exports = { rowMatches };
