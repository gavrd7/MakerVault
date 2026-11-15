/** Printer reachability takes priority over a cached job state.
 * An offline printer may still have a last-known "complete" job snapshot.
 * A printer error/alarm alone does not mean it is disconnected.
 */
export function isDashboardPrinterOffline(printer) {
  if (!printer) return false;
  if (printer.stale === true || printer.online === false || printer.connected === false) return true;
  const connection = String(printer.connection_status || "").trim().toLowerCase();
  const state = String(printer.state || "").trim().toLowerCase();
  return ["disconnected", "offline", "unavailable", "unreachable", "error", "failed"].includes(connection)
    || ["disconnected", "offline", "unavailable", "unreachable"].includes(state);
}
