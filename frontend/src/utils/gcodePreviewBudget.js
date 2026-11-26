/**
 * Limit each HTTP/GPU upload batch, never the total printable model.
 *
 * A large source is still shown from first to last layer. The independent
 * native layer inspection endpoint stays available for exact path review.
 */
export function progressiveLayerBatchSize(layerCount, segmentCount) {
  if (!Number.isFinite(layerCount) || layerCount <= 0) return 1;
  if (!Number.isFinite(segmentCount) || segmentCount <= 0) return 64;
  // Bounded requests protect small devices without silently omitting any
  // part of a completed print. Round down to allow uneven layer densities.
  const averageMoves = segmentCount / layerCount;
  return Math.max(1, Math.min(64, Math.floor(120000 / averageMoves)));
}
