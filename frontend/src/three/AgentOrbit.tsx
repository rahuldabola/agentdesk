import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { AGENTS, type AgentKey } from "../lib/agents";

export interface AgentOrbitProps {
  /** Agent currently working (pulses, particles stream into it). */
  active: AgentKey | null;
  /** How many times each agent has finished in this run. */
  visits: Map<string, number>;
  /** Last agent to finish — its outgoing edge is the one lighting up. */
  lastNode: string | null;
  running: boolean;
  done: boolean;
  /** Attract mode for the landing page: cycles through the pipeline on its own. */
  demo?: boolean;
  /** Agent highlighted from outside the canvas (e.g. hovering a card). */
  highlight?: AgentKey | null;
  onHoverAgent?: (key: AgentKey | null) => void;
  onSelectAgent?: (key: AgentKey) => void;
  compact?: boolean;
  className?: string;
}

interface EdgeDef {
  from: AgentKey | "core";
  to: AgentKey;
  loop?: boolean;
}

const EDGES: EdgeDef[] = [
  { from: "core", to: "planner" },
  { from: "planner", to: "researcher" },
  { from: "researcher", to: "analyst" },
  { from: "analyst", to: "writer" },
  { from: "writer", to: "critic" },
  { from: "critic", to: "writer", loop: true },
  { from: "critic", to: "researcher", loop: true },
];

const PARTICLES_PER_EDGE = 16;
const RING_RADIUS = 3.2;
const DONE_COLOR = new THREE.Color("#34d399");
const DIM_COLOR = new THREE.Color("#3b4060");
const CORE_COLOR = new THREE.Color("#7c6dfa");

function makeGlowTexture(): THREE.Texture {
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.18, "rgba(255,255,255,0.55)");
  g.addColorStop(0.45, "rgba(255,255,255,0.12)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export default function AgentOrbit(props: AgentOrbitProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const labelRefs = useRef<(HTMLDivElement | null)[]>([]);
  const propsRef = useRef(props);
  propsRef.current = props;
  const [failed, setFailed] = useState(false);
  const [hovered, setHovered] = useState<AgentKey | null>(null);
  const [demoActive, setDemoActive] = useState<AgentKey | null>(null);
  const demoActiveRef = useRef<AgentKey | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    } catch {
      setFailed(true);
      return;
    }

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const coarsePointer = window.matchMedia("(pointer: coarse)").matches;

    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x000000, 0);
    renderer.domElement.style.display = "block";
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    container.prepend(renderer.domElement);

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x07080d, 12, 34);
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
    const baseDistance = propsRef.current.compact ? 8.6 : 9.2;
    camera.position.set(0, 3.1, baseDistance);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableZoom = false;
    controls.enablePan = false;
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.rotateSpeed = 0.55;
    controls.autoRotate = !reducedMotion;
    controls.autoRotateSpeed = 0.55;
    controls.minPolarAngle = Math.PI * 0.22;
    controls.maxPolarAngle = Math.PI * 0.58;
    if (coarsePointer) {
      // Let touch drags scroll the page instead of spinning the scene.
      controls.enableRotate = false;
      renderer.domElement.style.touchAction = "pan-y";
    }

    const glowTex = makeGlowTexture();
    const disposables: { dispose: () => void }[] = [glowTex, controls];
    const track = <T extends { dispose: () => void }>(x: T) => {
      disposables.push(x);
      return x;
    };

    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const coreLight = new THREE.PointLight(0x8b7cff, 30, 14, 1.6);
    scene.add(coreLight);
    const keyLight = new THREE.DirectionalLight(0xffffff, 1.2);
    keyLight.position.set(4, 6, 5);
    scene.add(keyLight);

    const world = new THREE.Group();
    world.rotation.x = 0.08;
    scene.add(world);

    // ---- Starfield --------------------------------------------------------
    const starCount = 900;
    const starPos = new Float32Array(starCount * 3);
    for (let i = 0; i < starCount; i++) {
      const r = 14 + Math.random() * 18;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      starPos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      starPos[i * 3 + 1] = r * Math.cos(phi);
      starPos[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
    }
    const starGeo = track(new THREE.BufferGeometry());
    starGeo.setAttribute("position", new THREE.BufferAttribute(starPos, 3));
    const stars = new THREE.Points(
      starGeo,
      track(
        new THREE.PointsMaterial({
          size: 0.09,
          map: glowTex,
          color: 0xc7c9ff,
          transparent: true,
          opacity: 0.75,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        }),
      ),
    );
    scene.add(stars);

    // ---- Orbit guide rings --------------------------------------------------
    for (const [radius, opacity] of [
      [RING_RADIUS, 0.16],
      [RING_RADIUS * 1.45, 0.06],
    ] as const) {
      const ring = new THREE.Mesh(
        track(new THREE.RingGeometry(radius - 0.006, radius + 0.006, 160)),
        track(new THREE.MeshBasicMaterial({ color: 0x8b7cff, transparent: true, opacity, side: THREE.DoubleSide, depthWrite: false })),
      );
      ring.rotation.x = -Math.PI / 2;
      world.add(ring);
    }

    // ---- Core (the orchestrator) -------------------------------------------
    const core = new THREE.Group();
    world.add(core);
    const coreShell = new THREE.Mesh(
      track(new THREE.IcosahedronGeometry(0.95, 1)),
      track(new THREE.MeshBasicMaterial({ color: 0x9b8cff, wireframe: true, transparent: true, opacity: 0.35 })),
    );
    core.add(coreShell);
    const coreInnerMat = track(
      new THREE.MeshStandardMaterial({ color: 0x8b7cff, emissive: 0x7c6dfa, emissiveIntensity: 1.4, roughness: 0.25, metalness: 0.3 }),
    );
    const coreInner = new THREE.Mesh(track(new THREE.IcosahedronGeometry(0.46, 3)), coreInnerMat);
    core.add(coreInner);
    const coreHaloMat = track(
      new THREE.SpriteMaterial({ map: glowTex, color: 0x8b7cff, transparent: true, opacity: 0.8, blending: THREE.AdditiveBlending, depthWrite: false }),
    );
    const coreHalo = new THREE.Sprite(coreHaloMat);
    coreHalo.scale.setScalar(4.2);
    core.add(coreHalo);

    // ---- Agent nodes ----------------------------------------------------------
    const nodePositions = new Map<AgentKey | "core", THREE.Vector3>();
    nodePositions.set("core", new THREE.Vector3(0, 0, 0));

    const nodeGeo = track(new THREE.SphereGeometry(0.3, 40, 40));
    const hitGeo = track(new THREE.SphereGeometry(0.62, 12, 12));
    const hitMat = track(new THREE.MeshBasicMaterial({ visible: false }));
    const ringGeo = track(new THREE.TorusGeometry(0.5, 0.014, 8, 80));

    interface NodeObj {
      key: AgentKey;
      group: THREE.Group;
      mesh: THREE.Mesh;
      mat: THREE.MeshStandardMaterial;
      halo: THREE.Sprite;
      haloMat: THREE.SpriteMaterial;
      ring: THREE.Mesh;
      ringMat: THREE.MeshBasicMaterial;
      baseColor: THREE.Color;
      scale: number;
      glow: number;
    }

    const hitMeshes: THREE.Mesh[] = [];
    const nodes: NodeObj[] = AGENTS.map((agent, i) => {
      const angle = (i / AGENTS.length) * Math.PI * 2 + Math.PI / 2;
      const pos = new THREE.Vector3(Math.cos(angle) * RING_RADIUS, Math.sin(i * 1.7) * 0.35, Math.sin(angle) * RING_RADIUS);
      nodePositions.set(agent.key, pos);

      const baseColor = new THREE.Color(agent.color);
      const group = new THREE.Group();
      group.position.copy(pos);
      world.add(group);

      const mat = track(new THREE.MeshStandardMaterial({ color: baseColor.clone(), emissive: baseColor.clone(), emissiveIntensity: 0.8, roughness: 0.3, metalness: 0.25 }));
      const mesh = new THREE.Mesh(nodeGeo, mat);
      group.add(mesh);

      const haloMat = track(
        new THREE.SpriteMaterial({ map: glowTex, color: baseColor.clone(), transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false }),
      );
      const halo = new THREE.Sprite(haloMat);
      halo.scale.setScalar(2.2);
      group.add(halo);

      const ringMat = track(new THREE.MeshBasicMaterial({ color: baseColor.clone(), transparent: true, opacity: 0.5 }));
      const ring = new THREE.Mesh(ringGeo, ringMat);
      ring.rotation.x = Math.PI / 2.4;
      group.add(ring);

      const hit = new THREE.Mesh(hitGeo, hitMat);
      hit.userData.agent = agent.key;
      group.add(hit);
      hitMeshes.push(hit);

      return { key: agent.key, group, mesh, mat, halo, haloMat, ring, ringMat, baseColor, scale: 1, glow: 0.5 };
    });

    // ---- Edges with flowing particles ----------------------------------------
    interface EdgeObj {
      def: EdgeDef;
      curve: THREE.QuadraticBezierCurve3;
      lineMat: THREE.LineBasicMaterial;
      points: THREE.Points;
      pointsMat: THREE.PointsMaterial;
      positions: Float32Array;
      offsets: number[];
      heat: number;
      trail: number;
    }

    const edges: EdgeObj[] = EDGES.map((def) => {
      const a = nodePositions.get(def.from)!;
      const b = nodePositions.get(def.to)!;
      const mid = a.clone().add(b).multiplyScalar(0.5);
      const control = def.loop
        ? mid.clone().multiplyScalar(0.25).add(new THREE.Vector3(0, def.to === "researcher" ? 1.9 : 1.2, 0))
        : def.from === "core"
          ? mid.clone().add(new THREE.Vector3(0, 0.9, 0))
          : mid.clone().multiplyScalar(1.28).add(new THREE.Vector3(0, 0.55, 0));
      const curve = new THREE.QuadraticBezierCurve3(a.clone(), control, b.clone());

      const lineGeo = track(new THREE.BufferGeometry().setFromPoints(curve.getPoints(80)));
      const fromColor = def.from === "core" ? new THREE.Color(0x8b7cff) : new THREE.Color(AGENTS.find((x) => x.key === def.from)!.color);
      // Feedback loops (Critic -> Writer/Researcher) are dashed to read as "maybe".
      const lineMat: THREE.LineBasicMaterial = track(
        def.loop
          ? new THREE.LineDashedMaterial({ color: fromColor, transparent: true, opacity: 0.1, dashSize: 0.12, gapSize: 0.1, depthWrite: false })
          : new THREE.LineBasicMaterial({ color: fromColor, transparent: true, opacity: 0.1, depthWrite: false, blending: THREE.AdditiveBlending }),
      );
      const line = new THREE.Line(lineGeo, lineMat);
      if (def.loop) line.computeLineDistances();
      world.add(line);
      return makeEdge(def, curve, lineMat, fromColor);
    });

    function makeEdge(def: EdgeDef, curve: THREE.QuadraticBezierCurve3, lineMat: THREE.LineBasicMaterial, color: THREE.Color): EdgeObj {
      const positions = new Float32Array(PARTICLES_PER_EDGE * 3);
      const geo = track(new THREE.BufferGeometry());
      geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      const pointsMat = track(
        new THREE.PointsMaterial({
          size: 0.2,
          map: glowTex,
          color,
          transparent: true,
          opacity: 0,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        }),
      );
      const points = new THREE.Points(geo, pointsMat);
      world.add(points);
      const offsets = Array.from({ length: PARTICLES_PER_EDGE }, (_, i) => i / PARTICLES_PER_EDGE + Math.random() * 0.02);
      return { def, curve, lineMat, points, pointsMat, positions, offsets, heat: 0, trail: 0 };
    }

    // ---- Interaction -------------------------------------------------------------
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let hoveredKey: AgentKey | null = null;
    let pointerInside = false;

    function onPointerMove(e: PointerEvent) {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      pointerInside = true;
    }
    function onPointerLeave() {
      pointerInside = false;
    }
    let downAt = { x: 0, y: 0 };
    function onPointerDown(e: PointerEvent) {
      downAt = { x: e.clientX, y: e.clientY };
    }
    function onClick(e: MouseEvent) {
      // Ignore the click that ends a drag-to-rotate gesture.
      if (Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) > 5) return;
      if (hoveredKey) propsRef.current.onSelectAgent?.(hoveredKey);
    }
    renderer.domElement.addEventListener("pointermove", onPointerMove);
    renderer.domElement.addEventListener("pointerleave", onPointerLeave);
    renderer.domElement.addEventListener("pointerdown", onPointerDown);
    renderer.domElement.addEventListener("click", onClick);

    // ---- Sizing & visibility ------------------------------------------------------
    let visible = true;
    function resize() {
      const w = container!.clientWidth;
      const h = container!.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      // Pull the camera back on narrow screens so the whole ring still fits.
      const fit = Math.min(1.9, Math.max(1, 1.45 / camera.aspect));
      camera.position.setLength(baseDistance * fit * 1.02);
      camera.updateProjectionMatrix();
    }
    const ro = new ResizeObserver(resize);
    ro.observe(container);
    resize();
    const io = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
    });
    io.observe(container);

    // ---- Demo cycle for the landing page ---------------------------------------------
    const demoOrder: AgentKey[] = ["planner", "researcher", "analyst", "writer", "critic"];
    let demoIndex = 0;
    let demoTimer = 0;

    // ---- Render loop ------------------------------------------------------------------
    const clock = new THREE.Clock();
    const tmp = new THREE.Vector3();
    let prevDone = propsRef.current.done;
    let donePulse = 0;
    let frame = 0;

    function tick() {
      frame = requestAnimationFrame(tick);
      const dt = Math.min(clock.getDelta(), 0.05);
      if (!visible || document.hidden) return;
      const t = clock.elapsedTime;
      const p = propsRef.current;

      // Demo mode walks the pipeline on a timer.
      let active = p.active;
      let lastNode = p.lastNode;
      if (p.demo) {
        demoTimer += dt;
        if (demoTimer > 1.7) {
          demoTimer = 0;
          demoIndex = (demoIndex + 1) % demoOrder.length;
        }
        active = demoOrder[demoIndex];
        lastNode = demoIndex === 0 ? null : demoOrder[demoIndex - 1];
        if (demoActiveRef.current !== active) {
          demoActiveRef.current = active;
          setDemoActive(active);
        }
      }

      if (p.done && !prevDone) donePulse = 1;
      prevDone = p.done;
      donePulse = Math.max(0, donePulse - dt * 0.8);

      // Hover picking
      if (pointerInside) {
        raycaster.setFromCamera(pointer, camera);
        const hit = raycaster.intersectObjects(hitMeshes, false)[0];
        const key = (hit?.object.userData.agent as AgentKey | undefined) ?? null;
        if (key !== hoveredKey) {
          hoveredKey = key;
          renderer.domElement.style.cursor = key ? "pointer" : "grab";
          setHovered(key);
          p.onHoverAgent?.(key);
        }
      } else if (hoveredKey) {
        hoveredKey = null;
        setHovered(null);
        p.onHoverAgent?.(null);
      }

      const hasRun = !p.demo && (p.running || p.done || p.visits.size > 0);

      // Core
      coreShell.rotation.y += dt * (p.running ? 0.9 : 0.25);
      coreShell.rotation.x += dt * 0.15;
      coreInner.rotation.y -= dt * 0.4;
      const coreTarget = p.done ? DONE_COLOR : CORE_COLOR;
      coreInnerMat.emissive.lerp(coreTarget, dt * 2);
      coreHaloMat.color.lerp(coreTarget, dt * 2);
      coreLight.color.lerp(coreTarget, dt * 2);
      const coreBreath = 1 + Math.sin(t * (p.running ? 3 : 1.2)) * 0.04 + donePulse * 0.6;
      core.scale.setScalar(coreBreath);
      coreHaloMat.opacity = 0.55 + (p.running ? 0.2 : 0) + donePulse * 0.4;

      // Nodes
      for (const n of nodes) {
        const visits = p.visits.get(n.key) ?? 0;
        const isActive = active === n.key;
        const isHighlighted = hoveredKey === n.key || p.highlight === n.key;
        const isFuture = hasRun && visits === 0 && !isActive;

        const targetScale = isActive ? 1.35 + Math.sin(t * 5) * 0.08 : isHighlighted ? 1.25 : 1;
        n.scale += (targetScale - n.scale) * Math.min(1, dt * 8);
        n.mesh.scale.setScalar(n.scale);

        const targetGlow = isActive ? 1 : isHighlighted ? 0.85 : isFuture ? 0.12 : hasRun ? 0.55 : 0.5;
        n.glow += (targetGlow - n.glow) * Math.min(1, dt * 5);

        const colorTarget = isFuture ? DIM_COLOR : n.baseColor;
        n.mat.color.lerp(colorTarget, dt * 4);
        n.mat.emissive.lerp(colorTarget, dt * 4);
        n.mat.emissiveIntensity = 0.3 + n.glow * 1.6 + donePulse;
        n.haloMat.color.lerp(colorTarget, dt * 4);
        n.haloMat.opacity = 0.1 + n.glow * 0.75 + donePulse * 0.5;
        n.halo.scale.setScalar(1.6 + n.glow * 1.6 + (isActive ? Math.sin(t * 5) * 0.2 : 0));
        n.ring.rotation.z += dt * (isActive ? 3.2 : 0.5);
        n.ringMat.opacity = isFuture ? 0.12 : 0.25 + n.glow * 0.5;
        n.ring.scale.setScalar(isActive ? 1.15 + Math.sin(t * 5) * 0.05 : 1);
        n.group.position.y = nodePositions.get(n.key)!.y + Math.sin(t * 0.9 + n.key.length) * 0.08;
      }

      // Edges
      for (const e of edges) {
        const fromVisited = e.def.from === "core" ? hasRun || !!p.demo : (p.visits.get(e.def.from) ?? 0) > 0;
        const toVisited = (p.visits.get(e.def.to) ?? 0) > 0;
        const hot =
          active === e.def.to &&
          (e.def.from === "core" ? !lastNode || active === "planner" : lastNode === e.def.from) &&
          (!e.def.loop || lastNode === "critic");
        const traversed = !p.demo && fromVisited && toVisited && (!e.def.loop || (p.visits.get("critic") ?? 0) > 0 && (p.visits.get(e.def.to) ?? 0) > 1);
        const idle = !hasRun && !p.demo && !e.def.loop;

        const heatTarget = hot ? 1 : traversed ? 0.35 : idle ? 0.25 : p.demo && !e.def.loop ? 0.18 : 0;
        e.heat += (heatTarget - e.heat) * Math.min(1, dt * 4);
        e.lineMat.opacity = (e.def.loop ? 0.08 : 0.1) + e.heat * 0.55;
        e.pointsMat.opacity = e.heat;
        e.pointsMat.size = 0.14 + e.heat * 0.14;

        const speed = reducedMotion ? 0.05 : hot ? 0.55 : 0.14;
        e.trail = (e.trail + dt * speed) % 1;
        for (let i = 0; i < PARTICLES_PER_EDGE; i++) {
          // Bunch particles toward the head of the stream when an edge is hot.
          let u = (e.offsets[i] + e.trail) % 1;
          if (hot) u = Math.pow(u, 0.85);
          e.curve.getPoint(u, tmp);
          e.positions[i * 3] = tmp.x;
          e.positions[i * 3 + 1] = tmp.y;
          e.positions[i * 3 + 2] = tmp.z;
        }
        (e.points.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
      }

      stars.rotation.y += dt * 0.01;
      controls.autoRotateSpeed = hoveredKey ? 0 : p.running ? 0.9 : 0.55;
      controls.update();
      renderer.render(scene, camera);

      // Project HTML labels onto their nodes.
      const w = container!.clientWidth;
      const h = container!.clientHeight;
      nodes.forEach((n, i) => {
        const el = labelRefs.current[i];
        if (!el) return;
        n.group.getWorldPosition(tmp);
        const depth = tmp.clone().sub(camera.position).length();
        tmp.project(camera);
        const x = (tmp.x * 0.5 + 0.5) * w;
        const y = (-tmp.y * 0.5 + 0.5) * h;
        const near = THREE.MathUtils.clamp(1.25 - (depth - 6) / 8, 0.45, 1);
        el.style.transform = `translate(-50%, 0) translate(${x.toFixed(1)}px, ${(y + 22).toFixed(1)}px) scale(${(0.8 + near * 0.2).toFixed(3)})`;
        el.style.opacity = near.toFixed(2);
        el.style.zIndex = String(Math.round(100 - depth * 5));
      });
    }
    tick();

    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      io.disconnect();
      renderer.domElement.removeEventListener("pointermove", onPointerMove);
      renderer.domElement.removeEventListener("pointerleave", onPointerLeave);
      renderer.domElement.removeEventListener("pointerdown", onPointerDown);
      renderer.domElement.removeEventListener("click", onClick);
      for (const d of disposables) d.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  const { visits, done, demo, highlight } = props;
  const active = demo ? demoActive : props.active;

  if (failed) {
    return (
      <div className={`relative flex items-center justify-center ${props.className ?? ""}`}>
        <div className="h-40 w-40 animate-pulse rounded-full bg-[radial-gradient(circle,var(--accent)_0%,transparent_70%)] opacity-60" />
      </div>
    );
  }

  return (
    <div ref={containerRef} className={`relative overflow-hidden ${props.className ?? ""}`} style={{ cursor: "grab" }}>
      {AGENTS.map((agent, i) => {
        const count = visits.get(agent.key) ?? 0;
        const isActive = active === agent.key;
        const emphasized = isActive || hovered === agent.key || highlight === agent.key;
        const future = !demo && (props.running || done || visits.size > 0) && count === 0 && !isActive;
        return (
          <div
            key={agent.key}
            ref={(el) => {
              labelRefs.current[i] = el;
            }}
            className="pointer-events-none absolute left-0 top-0 select-none whitespace-nowrap will-change-transform"
          >
            <div
              className="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium backdrop-blur-md transition-all duration-300"
              style={{
                borderColor: emphasized ? agent.color : "rgba(255,255,255,0.08)",
                background: emphasized ? `${agent.color}26` : "rgba(12,13,20,0.55)",
                color: future ? "var(--text-faint)" : "var(--text)",
                boxShadow: emphasized ? `0 0 24px -6px ${agent.color}` : "none",
              }}
            >
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: future ? "var(--text-faint)" : agent.color }} />
              {agent.label}
              {isActive && !demo && <span className="text-[10px] text-[var(--text-dim)]">working…</span>}
              {count > 1 && (
                <span className="rounded-full bg-white/10 px-1 text-[9px]">×{count}</span>
              )}
            </div>
            {!props.compact && hovered === agent.key && (
              <div className="mt-1.5 max-w-[200px] whitespace-normal rounded-lg border border-white/10 bg-[#0c0d14]/90 px-2.5 py-1.5 text-center text-[10.5px] leading-snug text-[var(--text-dim)] backdrop-blur-md">
                {agent.blurb}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
