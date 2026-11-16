/** Surface-slope filter for support-enforcer strokes.
 * The angle is measured from the build-plate vertical: a downward horizontal
 * face is a 90-degree overhang, a vertical wall is 0 degrees.
 * Use a normal matrix (inverse transpose) so rotations and nonuniform scaling
 * are respected. The saved polygon representation is unchanged.
 */
export function filterSupportOverhangFaces(faces, normals, normalMatrix, angleDeg=45) {
  if (!Array.isArray(faces) || !Array.isArray(normals) ||
      !Array.isArray(normalMatrix) || normalMatrix.length!==9 ||
      !normalMatrix.every(Number.isFinite) ||
      !Number.isFinite(angleDeg) || angleDeg<0 || angleDeg>90)
    throw new Error("Invalid support overhang selection.");
  const cutoff=-Math.sin(angleDeg*Math.PI/180);
  const result=[];
  for(const face of faces){
    const n=normals[face];
    if(!Array.isArray(n) || n.length!==3 || !n.every(Number.isFinite))continue;
    const x=normalMatrix[0]*n[0]+normalMatrix[3]*n[1]+normalMatrix[6]*n[2];
    const y=normalMatrix[1]*n[0]+normalMatrix[4]*n[1]+normalMatrix[7]*n[2];
    const z=normalMatrix[2]*n[0]+normalMatrix[5]*n[1]+normalMatrix[8]*n[2];
    const length=Math.hypot(x,y,z);
    if(length>1e-9 && z/length<cutoff-1e-9)result.push(face);
  }
  return result;
}
