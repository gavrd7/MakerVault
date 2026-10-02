// A printer action is a one-shot intent, never a persistent page selection.
export function printerIntent(target, printers, handledToken) {
  if (target?.type !== "printers" || (!target.openLive && !target.openCamera) || target.token === handledToken) return null;
  const printer = printers?.find(item => item.id === target.id);
  return printer ? { printer, camera: Boolean(target.openCamera), token: target.token } : null;
}

export function consumePrinterIntent(current, token) {
  return current?.token === token ? null : current;
}
