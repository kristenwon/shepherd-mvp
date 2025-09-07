"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape from "cytoscape";

/* ---------------- singleton WS by URL ---------------- */
function getSingletonWS(url) {
    if (typeof window === "undefined") return new WebSocket(url);
    const pool = (window.__masWsPool ||= new Map());
    const existing = pool.get(url);
    if (existing && existing.readyState < 2) return existing; // CONNECTING or OPEN
    const ws = new WebSocket(url);
    pool.set(url, ws);
    ws.addEventListener("close", () => {
        if (pool.get(url) === ws) pool.delete(url);
    });
    return ws;
    }

    /* ---------------- constants & helpers ---------------- */
    const AGENT_ID = "agent-root";

    const isHexAddr = (s) => typeof s === "string" && /^0x[a-fA-F0-9]{40}$/.test(s);
    const shortAddr = (a) => (a ? `${a.slice(0, 6)}…${a.slice(-4)}` : "");
    const contractNodeId = (s) => `c-${encodeURIComponent(String(s))}`;
    const contractLabel = (s) => (isHexAddr(s) ? shortAddr(s) : String(s || "Contract"));

    /** Parse either envelope <<<TAG>>>{json}<<<END_TAG>>> or plain JSON */
    function parseWsPayload(raw) {
    if (typeof raw === "string") {
        // Envelope
        const m = raw.match(/^<<<([A-Z_]+)>>>([\s\S]*?)<<<END_\1>>>$/);
        if (m) {
        let inner = {};
        try { inner = JSON.parse(m[2]); } catch {}
        const tag = (inner?.tag_type || m[1]).toString().toLowerCase().replace(/_/g, "-");
        return { type: tag, data: inner };
        }
        // Plain JSON
        try { return JSON.parse(raw); } catch {}
    }
    return null;
    }

    function agentLabelFromData(data) {
    let agent = data?.agent_type || data?.agent || data?.name || "";
    if (!agent && typeof data?.content === "string") {
        const cleaned = data.content.split("<<<END_")[0].trim();
        try { agent = JSON.parse(cleaned)?.agent_type || ""; }
        catch { agent = cleaned.match(/"agent_type"\s*:\s*"([^"]+)"/)?.[1] || ""; }
    }
    return `Agent: ${agent || "Unknown"}`;
    }

    /* ---------------- component ---------------- */
    export default function Diagram({ runId: runIdProp }) {
    const containerRef = useRef(null);
    const cyRef = useRef(null);
    const centerRef = useRef({ x: 300, y: 200 }); // fallback center
    const orderCounterRef = useRef(0); // for stable contract ordering

    // Resolve runId: prop > localStorage > broadcast event
    const [runId, setRunId] = useState(runIdProp || null);
    useEffect(() => {
        if (runIdProp) { setRunId(runIdProp); return; }
        try {
        const v = localStorage.getItem("masRunId");
        if (v) setRunId(v);
        } catch {}
        const onRunId = (e) => { if (e?.detail) setRunId(e.detail); };
        window.addEventListener("mas:runId", onRunId);
        return () => window.removeEventListener("mas:runId", onRunId);
    }, [runIdProp]);

    // Backend base
    const API_BASE = useMemo(() => {
        return (process.env.NEXT_PUBLIC_API_BASE_URL || "https://shepherd-mas-dev.fly.dev").replace(/\/+$/, "");
    }, []);

    // ws(s)://.../ws/{runId}
    const socketUrl = useMemo(() => {
        if (!runId) return null;
        const u = new URL(API_BASE);
        u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
        u.pathname = u.pathname.replace(/\/$/, "") + `/ws/${runId}`;
        return u.toString();
    }, [API_BASE, runId]);

    // Init Cytoscape once
    useEffect(() => {
        if (!containerRef.current || cyRef.current) return;

        // compute initial center
        const rect = containerRef.current.getBoundingClientRect();
        centerRef.current = { x: rect.width / 2, y: rect.height / 2 };

        cyRef.current = cytoscape({
        container: containerRef.current,
        style: [
            /* Nodes */
            {
            selector: "node",
            style: {
                shape: "roundrectangle",
                "background-color": "#0f172a",
                label: "data(label)",
                "text-valign": "center",
                "text-halign": "center",
                color: "#f8fafc",
                "text-wrap": "wrap",
                "text-max-width": 180,
                "font-size": 14,
                "text-outline-width": 1,
                "text-outline-color": "#0f172a",
                padding: "12px",
                width: "label",
                height: "label",
                "border-width": 1,
                "border-color": "#38bdf8",
                "transition-property": "opacity",
                "transition-duration": "0.2s",
                opacity: 1
            }
            },
            { selector: "node.agent", style: { "border-color": "#f43f5e" } },      // agent = pink border
            { selector: "node.contract", style: { "border-color": "#10b981" } },   // contract = green border
            { selector: "node.hidden", style: { opacity: 0 } },

            /* Edges */
            {
            selector: "edge",
            style: {
                width: 2,
                "line-color": "#64748b",
                "target-arrow-color": "#64748b",
                "target-arrow-shape": "triangle",
                "curve-style": "bezier",
                label: "data(label)",
                "font-size": 11,
                color: "#e5e7eb",
                "text-rotation": "autorotate",
                "text-background-color": "#0f172a",
                "text-background-opacity": 0.85,
                "text-background-padding": "2px",
            }
            }
        ],
        elements: [],
        layout: { name: "preset" },
        wheelSensitivity: 0.2
        });

        // on resize, recenter and reflow
        const onResize = () => {
        if (!containerRef.current) return;
        const rect2 = containerRef.current.getBoundingClientRect();
        centerRef.current = { x: rect2.width / 2, y: rect2.height / 2 };
        recenterAgent();
        reflowContracts();
        };
        window.addEventListener("resize", onResize);

        return () => {
        window.removeEventListener("resize", onResize);
        cyRef.current?.destroy();
        cyRef.current = null;
        };
    }, []);

    /* --------- positioning utilities (center + radial rings) --------- */

    const recenterAgent = () => {
        const cy = cyRef.current;
        if (!cy) return;
        const center = centerRef.current;
        const agent = cy.$id(AGENT_ID);
        if (agent.nonempty()) {
        agent.position(center);
        }
    };

    // Given N contracts, position them in rings around center.
    // Ring capacities: 6, 12, 18, ... (6 * ringIndex)
    // Radius grows per ring; clamp radius so everything stays in view.
    const positionForIndex = (idx, center, containerRect) => {
        const ringBaseCap = 6;
        let ring = 1;
        let prevSum = 0;
        for (;;) {
        const cap = ringBaseCap * ring;
        if (idx < prevSum + cap) {
            const posInRing = idx - prevSum;
            const angleStep = (2 * Math.PI) / cap;
            const angle = posInRing * angleStep - Math.PI / 2; // start at top

            // radius: start at 160, then +120 per ring
            let radius = 160 + (ring - 1) * 120;

            // clamp radius to fit container (with padding)
            const pad = 40;
            const maxR = Math.max(
            60,
            Math.min(center.x - pad, center.y - pad, containerRect.width - center.x - pad, containerRect.height - center.y - pad)
            );
            radius = Math.min(radius, maxR);

            return {
            x: center.x + radius * Math.cos(angle),
            y: center.y + radius * Math.sin(angle),
            };
        }
        prevSum += cap;
        ring += 1;
        }
    };

    const reflowContracts = () => {
        const cy = cyRef.current;
        if (!cy || !containerRef.current) return;

        const rect = containerRef.current.getBoundingClientRect();
        const center = centerRef.current;

        // stable ordering by data(order)
        const nodes = cy.nodes(".contract").sort((a, b) => {
        const ao = a.data("order") ?? 0;
        const bo = b.data("order") ?? 0;
        return ao - bo;
        });

        nodes.forEach((n, idx) => {
        const pos = positionForIndex(idx, center, rect);
        n.position(pos);
        });

        // keep agent centered
        recenterAgent();
    };

    /* ---------------- ensure/create nodes ---------------- */

    const ensureAgentNode = (label) => {
        const cy = cyRef.current;
        if (!cy) return null;
        const center = centerRef.current;

        let node = cy.$id(AGENT_ID);
        if (node.nonempty()) {
        if (label) node.data("label", label);
        node.position(center);
        return node;
        }
        node = cy.add({
        group: "nodes",
        data: { id: AGENT_ID, label: label || "Agent" },
        position: center,
        classes: "hidden agent"
        });
        requestAnimationFrame(() => node.removeClass("hidden"));
        return node;
    };

    const ensureContractNode = (contractStr) => {
        const cy = cyRef.current;
        if (!cy) return null;
        const id = contractNodeId(contractStr);
        let node = cy.$id(id);
        if (node.nonempty()) return node;

        const rect = containerRef.current?.getBoundingClientRect() || { width: 800, height: 600 };
        const center = centerRef.current;
        const idx = cy.nodes(".contract").length; // next index in ring placement
        const pos = positionForIndex(idx, center, rect);

        node = cy.add({
        group: "nodes",
        data: { id, label: contractLabel(contractStr), order: orderCounterRef.current++ },
        position: pos,
        classes: "hidden contract"
        });
        requestAnimationFrame(() => node.removeClass("hidden"));
        return node;
    };

    /* ---------------- connect WS and process messages ---------------- */
    useEffect(() => {
        if (!cyRef.current || !socketUrl) return;

        const ws = getSingletonWS(socketUrl);

        const onMessage = async (evt) => {
        let raw = evt.data;
        if (raw instanceof Blob) {
            try { raw = await raw.text(); } catch { return; }
        }
        const msg = parseWsPayload(raw);
        if (!msg) return;

        const t = String(msg.type || "").toLowerCase().replace(/_/g, "-");
        if (t !== "agent" && t !== "executor-tool-call") return;

        const cy = cyRef.current;

        if (t === "agent") {
            // Create/update the single agent node and keep centered
            const label = agentLabelFromData(msg.data || {});
            ensureAgentNode(label);
            recenterAgent();
            return;
        }

        if (t === "executor-tool-call") {
            // Ensure the agent exists
            ensureAgentNode();

            // Pull tool name
            const toolName =
            msg.data?.tool_name ||
            msg.data?.name ||
            (typeof msg.data?.content === "string"
                ? (() => {
                    const cleaned = msg.data.content.split("<<<END_")[0].trim();
                    try { return JSON.parse(cleaned)?.tool_name || ""; }
                    catch { return cleaned.match(/"tool_name"\s*:\s*"([^"]+)"/)?.[1] || ""; }
                })()
                : "") ||
            "tool";

            // Contracts: prefer `contracts`; fallback to tool args.addresses
            let contracts = [];
            if (Array.isArray(msg.data?.contracts)) contracts = msg.data.contracts;
            else if (Array.isArray(msg.data?.args?.addresses)) contracts = msg.data.args.addresses;

            // Create edges Agent -> each Contract, labeled with toolName
            contracts.forEach((cStr) => {
            const cNode = ensureContractNode(cStr);
            if (!cNode) return;

            const edgeId = `e-${AGENT_ID}-${cNode.id()}-${toolName}-${Date.now()}-${Math.random()
                .toString(36)
                .slice(2, 6)}`;
            cy.add({
                group: "edges",
                data: {
                id: edgeId,
                source: AGENT_ID,
                target: cNode.id(),
                label: toolName
                }
            });
            });

            // After any additions, reflow all contracts radially
            reflowContracts();
            return;
        }
        };

        const onError = (e) => {
        // eslint-disable-next-line no-console
        console.error("[Diagram] WS error:", e);
        };

        ws.addEventListener("message", onMessage);
        ws.addEventListener("error", onError);
        return () => {
        ws.removeEventListener("message", onMessage);
        ws.removeEventListener("error", onError);
        };
    }, [socketUrl]);

    return (
        <div
        className="w-full h-[600px] bg-[#0C0C0C] bg-[radial-gradient(circle,_#1e293b_1px,_transparent_1px)] [background-size:20px_20px] rounded-lg shadow-md"
        ref={containerRef}
        />
    );
}
