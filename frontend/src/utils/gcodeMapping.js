/** Match a G-code requirement by its original slicer tool number.
 * A filtered "used filaments" array is not indexed by the slicer tool ID.
 */
export function findSlicedRequirement(requirements, toolIndex) {
  return (requirements || []).find(item => item.tool_index === toolIndex);
}
