import { copyFile, mkdir } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
// Use the packaged distribution assets. The source tree also contains these
// files, but the dist tree is the exact runtime layout shipped by webgazer.
const sourceRoot = join(packageRoot, "node_modules", "webgazer", "dist", "mediapipe", "face_mesh");
const destinationRoot = join(packageRoot, "smoke-test", "mediapipe", "face_mesh");

// These are the runtime files referenced by the installed WebGazer/MediaPipe
// FaceMesh solution. Keep the list explicit so the smoke bundle is reproducible.
export const MEDIAPIPE_FACE_MESH_ASSETS = [
  "face_mesh_solution_packed_assets_loader.js",
  "face_mesh_solution_packed_assets.data",
  "face_mesh_solution_simd_wasm_bin.js",
  "face_mesh_solution_simd_wasm_bin.wasm",
  "face_mesh_solution_wasm_bin.js",
  "face_mesh_solution_wasm_bin.wasm",
  "face_mesh.binarypb",
];

export async function copyMediaPipeAssets() {
  await mkdir(destinationRoot, { recursive: true });
  await Promise.all(MEDIAPIPE_FACE_MESH_ASSETS.map(async (asset) => {
    const source = join(sourceRoot, asset);
    const destination = join(destinationRoot, asset);
    await mkdir(dirname(destination), { recursive: true });
    await copyFile(source, destination);
  }));
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  await copyMediaPipeAssets();
}
