export const label = (value: string) => value.replaceAll('_', ' ');
export const displayTime = (date: string | null) => date ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(date)) : 'Never';
export const bytes = (value: number) => new Intl.NumberFormat(undefined, { style: 'unit', unit: 'byte', notation: 'compact' }).format(value);
export const incompleteCopy = (value: string) => !value.trim() || /\b(pending|tbd|todo|placeholder)\b/i.test(value);
