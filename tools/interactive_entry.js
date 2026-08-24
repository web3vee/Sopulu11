import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';

// The GLB is inlined as base64 by the build step: no network request is made,
// so the piece renders inside a sandboxed iframe with no external origins.
const GLB_B64 = window.__PEBBLECITY_GLB__;

function b64ToArrayBuffer(b64) {
  const bin = atob(b64);
  const len = bin.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

const canvas = document.getElementById('c');
const statusEl = document.getElementById('status');

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.0;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x000000);

let camera = new THREE.PerspectiveCamera(62, 1, 0.35, 900);
let composer, controls, mixer, bloom;
const clock = new THREE.Clock();

function resize() {
  const w = innerWidth, h = innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  if (composer) composer.setSize(w, h);
  if (bloom) bloom.resolution.set(w, h);
}
addEventListener('resize', resize);

new GLTFLoader().parse(b64ToArrayBuffer(GLB_B64), '', (gltf) => {
  scene.add(gltf.scene);

  // Start from the artwork's own hero camera, then hand control to the viewer.
  const cams = [];
  gltf.scene.traverse(o => { if (o.isCamera) cams.push(o); });
  const hero = cams.find(c => (c.name || (c.parent && c.parent.name)) === 'CineCam_Main') || cams[0];
  if (hero) {
    hero.updateWorldMatrix(true, false);
    camera.position.setFromMatrixPosition(hero.matrixWorld);
    camera.quaternion.setFromRotationMatrix(hero.matrixWorld);
    if (hero.isPerspectiveCamera) camera.fov = hero.fov;
  }

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.rotateSpeed = 0.5;
  controls.maxPolarAngle = Math.PI * 0.495;   // never drop under the ground plane
  controls.minDistance = 4;
  controls.maxDistance = 340;
  const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
  controls.target.copy(camera.position).addScaledVector(fwd, 70);

  mixer = new THREE.AnimationMixer(gltf.scene);
  const clip = gltf.animations.find(a => /AllMotion/.test(a.name)) || gltf.animations[0];
  if (clip) mixer.clipAction(clip).setLoop(THREE.LoopRepeat, Infinity).play();

  composer = new EffectComposer(renderer, new THREE.WebGLRenderTarget(1, 1, {
    samples: 4, type: THREE.HalfFloatType, colorSpace: THREE.LinearSRGBColorSpace }));
  composer.addPass(new RenderPass(scene, camera));
  bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.34, 0.55, 0.3);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  resize();
  statusEl.style.opacity = '0';
  setTimeout(() => statusEl.remove(), 900);
  renderer.setAnimationLoop(() => {
    if (mixer) mixer.update(clock.getDelta());
    if (controls) controls.update();
    composer.render();
  });
}, (err) => {
  statusEl.textContent = 'Failed to load artwork.';
  console.error(err);
});
