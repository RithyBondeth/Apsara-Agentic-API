export function chunk(items, size) {
  const chunks = [];
  for (let index = 0; index < items.length - size; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}
