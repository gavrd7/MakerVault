/** Only current, enabled connections can enter the existing printer submission workflow. */
export function availableSlicerPrintConnections(printer) {
  return (printer?.live_connections || []).filter(connection => connection?.enabled && connection?.id);
}

/** Prefer the printer's selected live source without silently switching adapters. */
export function preferredSlicerPrintConnection(printer) {
  const candidates = availableSlicerPrintConnections(printer);
  if (!candidates.length) return null;
  const activeId = printer?.live_status?.id || printer?.live_status?.connection_id;
  return candidates.find(item => String(item.id) === String(activeId)) || candidates[0];
}
