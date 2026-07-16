export interface PreparedCsvImport { file: File; fileName: string; fileSizeBytes: number; fileDigest: string; localManifestDigest: string; expectedUploadDigest: string; selectedScope: { columns: string[] }; selectedScopeDigest: string; parserVersion: 'csv-v1'; schemaVersion: 'interview-import-v1'; rowCount: number; }
const hex = (bytes: ArrayBuffer) => [...new Uint8Array(bytes)].map((item) => item.toString(16).padStart(2, '0')).join('');
const digest = async (input: string | ArrayBuffer) => `sha256:${hex(await crypto.subtle.digest('SHA-256', typeof input === 'string' ? new TextEncoder().encode(input) : input))}`;

export async function prepareCsvImport(file: File): Promise<PreparedCsvImport> {
  if (!file.name.toLowerCase().endsWith('.csv') || file.type && file.type !== 'text/csv') throw new Error('Choose a CSV file (text/csv).');
  const text = await file.text(); const rows = parseRfc4180(text.replace(/^\uFEFF/, '')); const header = rows.shift(); if (!header || rows.length === 0) throw new Error('CSV must include a header and at least one data row.');
  const columns = header.map((value) => value.trim()).filter(Boolean); if (columns.length === 0 || rows.some((row) => row.length !== columns.length)) throw new Error('CSV rows must match the RFC4180 header column count.');
  const bytes = await file.arrayBuffer(); const selectedScope = { columns }; const canonicalManifest = JSON.stringify({ file_digest: await digest(bytes), parser_version: 'csv-v1', schema_version: 'interview-import-v1', selected_scope: selectedScope, row_count: rows.length });
  return { file, fileName: file.name, fileSizeBytes: file.size, fileDigest: await digest(bytes), expectedUploadDigest: await digest(bytes), localManifestDigest: await digest(canonicalManifest), selectedScope, selectedScopeDigest: await digest(JSON.stringify(selectedScope)), parserVersion: 'csv-v1', schemaVersion: 'interview-import-v1', rowCount: rows.length };
}

export function parseRfc4180(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  let quoteClosed = false;
  const finishCell = () => { row.push(cell); cell = ''; quoteClosed = false; };
  const finishRow = () => { finishCell(); rows.push(row); row = []; };
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (quoted) {
      if (char === '"' && next === '"') { cell += '"'; index += 1; }
      else if (char === '"') { quoted = false; quoteClosed = true; }
      else cell += char;
      continue;
    }
    if (quoteClosed && char !== ',' && char !== '\r' && char !== '\n') throw new Error('Invalid RFC4180 character after a closing quote.');
    if (char === '"') {
      if (cell.length > 0 || quoteClosed) throw new Error('Invalid RFC4180 quote placement.');
      quoted = true;
    } else if (char === ',') finishCell();
    else if (char === '\r' && next === '\n') { finishRow(); index += 1; }
    else if (char === '\r' || char === '\n') finishRow();
    else cell += char;
  }
  if (quoted) throw new Error('CSV contains an unterminated quoted field.');
  if (cell.length > 0 || quoteClosed || row.length > 0) finishRow();
  return rows.filter((item) => item.some((cellValue) => cellValue.length > 0));
}
